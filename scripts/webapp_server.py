# -*- coding: utf-8 -*-
"""MEMS 平台**网页控制台**（本地 Web 应用：在网页上直接运行已有功能）。

设计（对齐仓库红线与 DSH 约定）：
* **只绑 127.0.0.1**；**白名单任务**——前端只能触发 `TASKS` 里登记的任务，无任意命令/代码执行；
* **不跑 COMSOL、不升模型状态、不删数据**：本控制台只做离线分析与门禁；求解仍走用户侧/队列；
* **长任务异步**：提交即返回 `job_id`，前端轮询 `/api/job/<id>`（长任务禁止阻塞单次调用）；
* **每个结果带证据**：脚本路径 + sha256、产物路径 + sha256、退出码/耗时、以及裁决字段
  （`verdict`/`release_allowed`/`publish_allowed`）——`inconclusive`/`None` **不得**被前端渲染成通过；
* **写操作要显式确认**：`writes=true` 的任务需带 `"confirm": true`，避免误点覆盖产物。

用法：
    python -B scripts/webapp_server.py --port 8877            # 前台跑
    python -B scripts/webapp_server.py --port 8877 --selftest  # 只做自检后退出
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[1]
RUN = REPO / "work/runs/remote-exported-20260922"
A6 = RUN / "a6"
SSH_HOST = "ubuntu-10-180-7-46"
REMOTE_ROOT = "/home/lab/projAI4US/autodesign/exported_results"
MAX_BODY = 1 << 20


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def script_sha(rel: str) -> str:
    p = REPO / rel
    return sha256_file(p) if p.is_file() else "MISSING"


def _load(name: str, rel: str):
    """按路径加载模块（scripts/ 不是包，用 importlib）。"""
    p = REPO / rel
    if not p.is_file():
        raise FileNotFoundError(rel)
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _in_work(p: Path) -> bool:
    try:
        Path(p).resolve().relative_to((REPO / "work").resolve())
        return True
    except Exception:
        return False


def _check_path(raw: str | None, *, default: Path | None = None,
                must_exist: bool = False, under_work: bool = False) -> Path:
    p = Path(raw) if raw else default
    if p is None:
        raise ValueError("缺少路径参数")
    if not p.is_absolute():
        p = REPO / p
    if under_work and not _in_work(p):
        raise ValueError("输出目录必须在 work/ 下：%s" % raw)
    inside_repo = True
    try:
        p.resolve().relative_to(REPO.resolve())
    except Exception:
        inside_repo = False
    if not inside_repo and not under_work:
        raise ValueError("路径必须在仓库内：%s" % raw)
    if must_exist and not p.exists():
        raise ValueError("路径不存在：%s" % raw)
    return p


def _artifacts(*paths: Path) -> list[dict]:
    out = []
    for p in paths:
        if p and p.is_file():
            out.append({"path": str(p), "bytes": p.stat().st_size,
                        "sha256": sha256_file(p)})
    return out


# ---------------------------------------------------------------------------
# 任务实现（全部离线；每个任务返回 dict，其中 verdict 类字段不可被前端改写）
# ---------------------------------------------------------------------------
def task_state(args: dict) -> dict:
    sys.path.insert(0, str(REPO / "src"))
    from memsharness import store
    try:
        conn = store.connect(read_only=True)
        try:
            stats = store.store_stats(conn)
        finally:
            conn.close()
    except Exception as exc:
        stats = {"error": "%s: %s" % (type(exc).__name__, str(exc)[:160])}
    roles = []
    for d in sorted((REPO / "agents").glob("*/agent.json")):
        m = json.loads(d.read_text(encoding="utf-8"))
        roles.append({"id": m.get("role_id"), "name": m.get("name"),
                      "kind": m.get("kind"), "status": m.get("status")})
    mcp = REPO / "src/memsharness/mcp_server.py"
    n_tools = mcp.read_text(encoding="utf-8").count("@mcp.tool") if mcp.is_file() else None
    return {"store": stats, "roles": roles, "n_mcp_tools": n_tools,
            "remote": {"host": SSH_HOST, "root": REMOTE_ROOT, "access": "read-only (ssh)"},
            "run_dirs": {"remote_export": str(RUN), "a6": str(A6)},
            "artifacts": _artifacts(RUN / "dataset/exported_manifest.json",
                                    RUN / "a5/scan_analysis.json",
                                    A6 / "a6_round3_result.json")}


def task_dashboard(args: dict) -> dict:
    mod = _load("_dash", "scripts/build_dashboard.py")
    out = _check_path(args.get("out_dir"), default=REPO / "work/reports/mems-dashboard",
                      under_work=True)
    rc = mod.main(["--out-dir", str(out),
                   "--generated-at", args.get("generated_at")] if args.get("generated_at")
                  else ["--out-dir", str(out)])
    return {"rc": rc, "out_dir": str(out),
            "artifacts": _artifacts(out / "index.html", out / "dashboard_data.json"),
            "note": "静态看板已重建（可直接刷新浏览器）"}


def task_sweep_analysis(args: dict) -> dict:
    mod = _load("_sweep_cli", "scripts/run_sweep_analysis.py")
    csv = _check_path(args.get("csv"), default=RUN / "a5/metric_table.csv", must_exist=True)
    out = _check_path(args.get("out_dir"), default=REPO / "work/reports/webapp/sweep",
                      under_work=True)
    argv = ["--csv", str(csv), "--preset", args.get("preset") or "cell_te2-exported",
            "--out-dir", str(out),
            "--min-effective", str(int(args.get("min_effective") or 5)),
            "--top-n", str(int(args.get("top_n") or 10))]
    if args.get("candidate_grid"):
        argv += ["--candidate-grid",
                 str(_check_path(args["candidate_grid"], must_exist=True))]
    if args.get("budget"):
        argv += ["--budget", str(int(args["budget"]))]
    if args.get("model_sha256"):
        argv += ["--model-sha256", str(args["model_sha256"])]
    if args.get("precheck"):
        argv += ["--precheck", str(_check_path(args["precheck"], must_exist=True))]
    rc = mod.main(argv)
    scan = json.loads((out / "scan_analysis.json").read_text(encoding="utf-8"))
    tops = [{"family": r["family"], "metric": r["metric"], "caliber": r["caliber"],
             "n_available": r["n_available"], "n_excluded": r["n_excluded"],
             "top": (r["top"] or [None])[0]} for r in scan["rankings"]]
    return {"rc": rc, "verdict": scan["verdict"],
            "release_allowed": scan["release_allowed"], "provisional": scan["provisional"],
            "verdict_by_family": scan["verdict_by_family"],
            "stop_reasons": scan["stop_reasons"],
            "exclusion_rate": scan["quality"]["exclusion_rate"],
            "tops": tops, "n_rankings": len(tops),
            "artifacts": _artifacts(out / "scan_analysis.json", out / "scan_analysis.md",
                                    out / "next_batch.json"),
            "script": {"path": "scripts/run_sweep_analysis.py",
                       "sha256": script_sha("scripts/run_sweep_analysis.py")}}


def task_report_gate(args: dict) -> dict:
    mod = _load("_report_cli", "scripts/run_report_augment.py")
    bundle = _check_path(args.get("bundle"), default=RUN / "a5/../bundle_platform.json",
                         must_exist=True)
    out = _check_path(args.get("out_dir"), default=REPO / "work/reports/webapp/report",
                      under_work=True)
    argv = ["--bundle", str(bundle), "--out-dir", str(out)]
    for key, flag in (("gate", "--gate"), ("known_ids", "--known-ids")):
        if args.get(key):
            argv += [flag, str(_check_path(args[key], must_exist=True))]
    rc = mod.main(argv)
    doc = json.loads((out / "report_bundle.json").read_text(encoding="utf-8"))
    return {"rc": rc, "verdict": doc["verdict"], "publish_allowed": doc["publish_allowed"],
            "blocking": [{"name": c["name"], "passed": c["passed"], "reason": c["reason"]}
                         for c in doc["checks"] if c["passed"] is not True],
            "gate_binding": next((c["detail"] for c in doc["checks"]
                                  if c["name"] == "gate_binding"), None),
            "n_claims": len(doc["claims"]), "gaps": len(doc["gaps"]),
            "artifacts": _artifacts(out / "analysis_report.md", out / "report_bundle.json"),
            "script": {"path": "scripts/run_report_augment.py",
                       "sha256": script_sha("scripts/run_report_augment.py")}}


def task_freeze_gate(args: dict) -> dict:
    sys.path.insert(0, str(REPO / "src"))
    from memsharness.freeze_gate import run_gate
    target = _check_path(args.get("target_dir"),
                         default=REPO / ("work/runs/phase0-field-holdout-20260915/freezes/"
                                         "freeze_phase1-executor-20260915-06"),
                         must_exist=True)
    v = run_gate(target)
    return {"verdict": v["verdict"], "release_allowed": v["release_allowed"],
            "freeze_id": v.get("freeze_id"), "n_checks": v["n_checks"],
            "failed_or_unknown": [{"name": c["name"], "passed": c["passed"],
                                   "reason": c["reason"]}
                                  for c in v["checks"] if c["passed"] is not True],
            "target_dir": str(target), "writes": "none（只读门禁）",
            "script": {"path": "scripts/verify_and_freeze.py",
                       "sha256": script_sha("scripts/verify_and_freeze.py")}}


def task_a6_eval(args: dict) -> dict:
    rnd = int(args.get("round") or 3)
    files = {1: ("a6_surrogate_debug.py", "a6_debug_result.json"),
             2: ("a6_round2_eval.py", "a6_round2_result.json"),
             3: ("a6_round3_eval.py", "a6_round3_result.json")}
    if rnd not in files:
        raise ValueError("round 只能是 1/2/3")
    script, out_json = files[rnd]
    mod = _load("_a6_%d" % rnd, str((A6 / script).relative_to(REPO)))
    t0 = time.time()
    rc = mod.main()
    doc = json.loads((A6 / out_json).read_text(encoding="utf-8"))
    summ = []
    for split, rows in (doc.get("splits") or {}).items():
        if split.startswith("R2-S1"):
            for r in rows:
                if r.get("skipped"):
                    continue
                for m in ("M1_ridge", "M2_krr", "M3_mlp", "M4_nn_resid", "M5_local_lin",
                          "M6_stratum_x", "B3_nn"):
                    sc = r.get(m + "_scalars")
                    if isinstance(sc, dict) and sc:
                        summ.append({"split": split, "model": m,
                                     "spl_max_dB": (sc.get("spl_max_dB") or {}).get("max_rel_err"),
                                     "spectrum_relL2": r.get(m + "_spectrum_relL2")})
    return {"rc": rc, "round": rnd, "duration_s": round(time.time() - t0, 1),
            "summary": summ,
            "artifacts": _artifacts(A6 / out_json, A6 / out_json.replace("_result", "_result")),
            "script": {"path": str((A6 / script).relative_to(REPO)),
                       "sha256": script_sha(str((A6 / script).relative_to(REPO)))},
            "note": "判定带见各轮预注册；inconclusive/fail 不得读成通过"}


def task_x_plan(args: dict) -> dict:
    mod = _load("_xplan", str((A6 / "x_densify_plan.py").relative_to(REPO)))
    rc = mod.main()
    plan = json.loads((A6 / "X_DENSIFY_PLAN.json").read_text(encoding="utf-8"))
    return {"rc": rc, "n_candidates_total": plan["n_candidates_total"],
            "recommended": [{"priority": c["priority"], "family": c["family"],
                             "n1": c["N_w_te1"], "x_mid": c["x_mid"],
                             "d_spl20": (c["basis"] or {}).get("delta_spl_20MHz_dB"),
                             "branch": c["branch_jump"], "role": c["role"]}
                            for c in plan["recommended"]],
            "stop_conditions": plan["stop_conditions"],
            "artifacts": _artifacts(A6 / "X_DENSIFY_PLAN.json", A6 / "X_DENSIFY_PLAN.md"),
            "note": "只出清单，不触发任何求解（执行在数据侧）"}


def task_fpeak_stats(args: dict) -> dict:
    mod = _load("_fpeak", str((A6 / "first_mode_distribution.py").relative_to(REPO)))
    rc = mod.main()
    d = json.loads((A6 / "first_mode_distribution.json").read_text(encoding="utf-8"))
    return {"rc": rc, "n_total": d["n_total"], "n_with_first_peak": d["n_with_first_peak"],
            "median_MHz": d["median_MHz"], "hist_MHz": d["hist_MHz"],
            "within_18_22MHz": d["within_18_22MHz"], "by_family": d["by_family"],
            "definition": d["definition"],
            "artifacts": _artifacts(A6 / "first_mode_distribution.json"),
            "script": {"path": str((A6 / "first_mode_distribution.py").relative_to(REPO)),
                       "sha256": script_sha(str((A6 / "first_mode_distribution.py").relative_to(REPO)))}}


def task_verify_mirror(args: dict) -> dict:
    mod = _load("_vmir", str((RUN / "verify_mirror.py").relative_to(REPO)))
    rc = mod.main()
    return {"rc": rc, "verdict": "passed" if rc == 0 else "failed",
            "note": "本地镜像 vs 远端 sha256 清单（269 条）逐文件比对",
            "artifacts": _artifacts(RUN / "remote_sha256.txt"),
            "script": {"path": str((RUN / "verify_mirror.py").relative_to(REPO)),
                       "sha256": script_sha(str((RUN / "verify_mirror.py").relative_to(REPO)))}}


def task_ingest_dataset(args: dict) -> dict:
    """解析镜像 → 数据集 CSV（**不写数据库**）。"""
    mod = _load("_ing", str((RUN / "ingest_exported_results.py").relative_to(REPO)))
    rc = mod.main()
    man = json.loads((RUN / "dataset/exported_manifest.json").read_text(encoding="utf-8"))
    return {"rc": rc, "counts": man["counts"], "flag_counts": man["flag_counts"],
            "caliber": man["caliber"],
            "artifacts": _artifacts(RUN / "dataset/points.csv", RUN / "dataset/combos.csv",
                                    RUN / "dataset/exported_manifest.json"),
            "note": "只写 work/ 下的数据集文件；**不写元数据库**（入库见 store_ingest 任务）"}


def task_store_ingest(args: dict) -> dict:
    """把数据集写进元数据库（append-only、幂等）——writes=true，需 confirm。"""
    mod = _load("_sing", str((RUN / "ingest_to_store.py").relative_to(REPO)))
    rc = mod.main()
    rep = json.loads((RUN / "store_ingest_report.json").read_text(encoding="utf-8"))
    return {"rc": rc, "report": {k: {"new": v["new"], "noop": v["noop"],
                                     "conflict": len(v["conflict"])}
                                 for k, v in rep.items()},
            "artifacts": _artifacts(RUN / "store_ingest_report.json"),
            "note": "append-only：同 id 内容不同会被拒收（conflict），不覆盖既有记录"}


def task_role_payload(args: dict) -> dict:
    mod = _load("_roles", "scripts/spawn_role.py")
    role = str(args.get("role") or "a8-verification-freeze")
    task = str(args.get("task") or "").strip()
    if not task:
        raise ValueError("必须给任务文本（空任务会被拒）")
    if args.get("dry_run"):
        return mod.main(["build", role, "--task", task, "--dry-run"]) == 0 and {
            "note": "dry-run"} or {"rc": 2}
    rc = mod.main(["build", role, "--task", task, "--record"])
    latest = max(mod.SPAWN_ROOT.glob("spawn-*"), key=lambda p: p.stat().st_mtime)
    rec = json.loads((latest / "spawn_record.json").read_text(encoding="utf-8"))
    return {"rc": rc, "spawn_id": rec["spawn_id"], "role_id": rec["role_id"],
            "contract_sha256": rec["contract_sha256"], "payload_sha256": rec["payload_sha256"],
            "payload_path": str(latest / "prompt.md"),
            "artifacts": _artifacts(latest / "prompt.md", latest / "spawn_record.json"),
            "not_spawned": "本控制台**不 spawn**：请把 payload 全文注入 subagent",
            "script": {"path": "scripts/spawn_role.py", "sha256": script_sha("scripts/spawn_role.py")}}


def task_remote_inventory(args: dict) -> dict:
    """只读远端清单（ssh + sha256sum）；不下载、不改远端。"""
    import subprocess
    t0 = time.time()
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", SSH_HOST,
           "cd %s && ls -d */ | wc -l && find . -type f | wc -l && du -sh . && "
           "cat _batch_*/status.txt 2>/dev/null" % REMOTE_ROOT]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return {"verdict": "failed", "rc": r.returncode, "stderr": r.stderr[:400],
                "note": "远端只读查询失败（网络/凭据），不影响本地分析"}
    lines = [x for x in r.stdout.splitlines() if x.strip()]
    return {"verdict": "passed", "duration_s": round(time.time() - t0, 1),
            "host": SSH_HOST, "root": REMOTE_ROOT, "raw": lines,
            "parsed": {"n_dirs": int(lines[0]) if lines else None,
                       "n_files": int(lines[1]) if len(lines) > 1 else None,
                       "size": lines[2] if len(lines) > 2 else None,
                       "batch_status": lines[3] if len(lines) > 3 else None},
            "note": "只读（ssh ls/find/du/cat）；不下载、不触发求解"}


def task_selfcheck(args: dict) -> dict:
    """跑离线测试子集（不含需要 COMSOL 的用例）。"""
    import subprocess
    t0 = time.time()
    cmd = [sys.executable, "-B", "-m", "pytest", "tests", "-q",
           "--ignore=tests/test_comsol_queue.py", "--ignore=tests/test_modelio.py",
           "-p", "no:cacheprovider"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO), timeout=900)
    tail = [x for x in r.stdout.splitlines() if x.strip()][-1:] or [""]
    return {"rc": r.returncode, "verdict": "passed" if r.returncode == 0 else "failed",
            "duration_s": round(time.time() - t0, 1), "summary": tail[0][:200],
            "stdout_tail": r.stdout.splitlines()[-8:]}


# ---------------------------------------------------------------------------
# 对话（主界面）：LLM + 工具调用；无凭据/不可达时退化为**本地指令路由**
# ---------------------------------------------------------------------------
CRED_FILE = Path.home() / ".dsh" / ".credentials.yaml"
LLM_CANDIDATES = [("https://api.deepseek.com", "deepseek-chat"),
                  ("https://api.deepseek.com", "deepseek-v4-flash")]
SYSTEM_PROMPT = (
    "你是 MEMS Harness 平台的**控制台助手**，运行在用户本机。"
    "你能调用平台里已登记的任务（工具）来真正执行分析，而不是只描述。"
    "铁律：① 没有证据不出数字——每个数值都要给出来源（文件/哈希/脚本）；"
    "② 裁决类字段（verdict/release_allowed/publish_allowed）**以代码产出为准**，"
    "不得把 inconclusive/provisional/None 说成通过；③ 不触发 COMSOL 求解（求解在用户侧）；"
    "④ 写产物的任务你只能**提议**——**必须真的发起该工具调用**"
    "（前端靠这个调用渲染『允许执行』卡片；只在文字里描述参数＝用户点不到，视为失职）；"
    "读类任务可直接执行；"
    "⑤ 数据族不得混用（cell_te2_* 与 b_GE_task3_2new 是不同族）。"
    "回答用中文，简洁；需要数字时先调工具再复述工具返回的结果与来源。"
)


def load_api_key() -> tuple[str | None, str]:
    """取 API key：环境变量优先，其次 `~/.dsh/.credentials.yaml`（**只在服务端使用，绝不下发**）。"""
    import os
    for env in ("DEEPSEEK_API_KEY", "DEEPSEEKAGENT_API_API_KEY"):
        v = os.environ.get(env)
        if v:
            return v.strip(), "env:%s" % env
    if CRED_FILE.is_file():
        import re
        txt = CRED_FILE.read_text(encoding="utf-8", errors="replace")
        for name in ("DEEPSEEK_API_KEY", "DEEPSEEKAGENT_API_API_KEY"):
            m = re.search(r"^\s*%s:\s*(\S+)\s*$" % name, txt, re.M)
            if m:
                return m.group(1).strip(), "file:%s#%s" % (CRED_FILE, name)
    return None, "none"


def _tool_specs() -> list[dict]:
    out = []
    for k, v in TASKS.items():
        props, required = {}, []
        for p in v["params"]:
            t = {"path": "string", "text": "string", "textarea": "string",
                 "int": "integer"}.get(p["type"], "string")
            d = {"type": t, "description": "默认 %s" % (p.get("default") or "")}
            if p["type"] == "select":
                d["enum"] = list(p["options"])
            props[p["name"]] = d
        out.append({"type": "function", "function": {
            "name": k, "description": "%s%s" % (v["title"],
                                               "（写产物：只能提议，需用户确认）"
                                               if v.get("writes") else "（只读，可直接执行）"),
            "parameters": {"type": "object", "properties": props, "required": required}}})
    return out


def _llm_call(messages: list[dict], tools: list[dict] | None, *, timeout: int = 90) -> dict:
    """调用 OpenAI 兼容的 chat/completions；失败抛异常（调用方决定是否退化）。"""
    import urllib.request
    key, _src = load_api_key()
    if not key:
        raise RuntimeError("no_api_key")
    last = None
    for base, model in LLM_CANDIDATES:
        body = {"model": model, "messages": messages, "temperature": 0.2, "stream": False}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions",
                                     data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": "Bearer " + key},
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            data["_used"] = {"base": base, "model": model}
            return data
        except urllib.error.HTTPError as e:
            last = "HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:200])
            continue
        except Exception as exc:
            last = "%s: %s" % (type(exc).__name__, str(exc)[:200])
            continue
    raise RuntimeError("llm_unavailable: %s" % last)


LOCAL_ROUTES = [
    (("谐振", "一阶", "f_peak", "fpeak", "20mhz", "20 mhz", "峰值频率"), "fpeak_stats"),
    (("排名", "a5", "扫描分析", "分族", "口径"), "sweep_analysis"),
    (("报告", "a9", "溯源", "缺口"), "report_gate"),
    (("冻结", "a8", "门禁", "freeze"), "freeze_gate"),
    (("ai 求解器", "ai求解器", "代理", "a6", "预测误差"), "a6_eval"),
    (("加密", "x 方向", "选点", "下一批"), "x_plan"),
    (("远端", "服务器", "ssh", "清单"), "remote_inventory"),
    (("镜像", "校验", "哈希", "sha256"), "verify_mirror"),
    (("入库", "写库", "数据库"), "store_ingest"),
    (("数据集", "解析", "csv"), "ingest_dataset"),
    (("角色", "点名", "子智能体", "载荷"), "role_payload"),
    (("自检", "测试", "回归"), "selfcheck"),
    (("看板", "静态页"), "dashboard"),
    (("状态", "总览", "库表", "多少"), "state"),
]


def _run_task_inprocess(task: str, args: dict) -> dict:
    """在**本进程内**跑一个任务（读类直接跑；写类必须先有 confirm）。

    ⚠️ 只应由 `--exec-task` 子进程入口调用。HTTP/对话路径一律走 `_run_task_sync`
    （子进程 + 真超时 + 可取消），否则超时只能"报告"而不能"终止"。
    """
    if task not in TASKS:
        return {"error": "未登记任务：%s" % task}
    if task == "role_payload" and not (args.get("task") or "").strip():
        return {"error": "role_payload 需要 task 文本（空任务会被拒）"}
    args = dict(args)
    if TASKS[task].get("writes") and not args.get("confirm"):
        return {"needs_confirmation": True, "task": task,
                "title": TASKS[task]["title"], "args": args}
    buf = io.StringIO()
    t0 = time.time()
    try:
        with EXEC_LOCK, redirect_stdout(buf):
            res = TASKS[task]["fn"](args)
        return {"task": task, "title": TASKS[task]["title"],
                "duration_s": round(time.time() - t0, 1), "result": res,
                "stdout": buf.getvalue()[-4000:]}
    except Exception as exc:
        return {"task": task, "error": "%s: %s" % (type(exc).__name__, str(exc)[:300]),
                "traceback": traceback.format_exc()[-1200:],
                "stdout": buf.getvalue()[-1200:]}


# ---------------------------------------------------------------------------
# 任务执行：**子进程 + 真超时 + 可取消 + 可审计**
#
# 为什么必须换子进程（2026-09-29 实测结论）：
#   * 线程无法被安全终止 ⇒ 在线程里做超时只能"报告超时"，任务其实还在跑，
#     这种 `timed_out` **不可验证**，属红线 1「没有证据就不出数字」的同类问题；
#   * 子进程可以被真正杀掉，于是 `timed_out` 与"已终止"都能给出证据（taskkill 回码）。
# 为什么必须杀**进程树**：控制台任务自己常再起子进程（pytest / COMSOL / ssh），
#   只杀直接子进程会留下孤儿继续占资源。
# ---------------------------------------------------------------------------
TASK_TIMEOUT_DEFAULT = 300
#: 逐任务超时（秒）。给"已知很慢"的任务放宽，其余用缺省。
TASK_TIMEOUTS = {
    "selfcheck": 900,          # 跑整个离线测试子集
    "dashboard": 600,
    "sweep_analysis": 600,
    "report_gate": 300,
    "a6_eval": 900,
    "freeze_gate": 300,
    "ingest_dataset": 600,
    "store_ingest": 300,
    "verify_mirror": 300,
    "role_payload": 120,
    "state": 120,
    "fpeak_stats": 300,
    "x_plan": 300,
    "mc_export": 300,
}
TASK_LOG = REPO / "work/logs/task_runs.jsonl"


def task_timeout(task: str) -> int:
    """该任务的超时秒数（注册表优先，缺省 `TASK_TIMEOUT_DEFAULT`）。"""
    if task in TASKS and TASKS[task].get("timeout_s"):
        return int(TASKS[task]["timeout_s"])
    return int(TASK_TIMEOUTS.get(task, TASK_TIMEOUT_DEFAULT))


def _kill_tree(pid: int) -> dict:
    """连子进程一起终止；返回**可核查的证据**（命令 + 回码）。"""
    if os.name == "nt":
        r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, text=True)
        return {"method": "taskkill /PID %d /T /F" % pid, "rc": r.returncode,
                "out": ((r.stdout or "") + (r.stderr or "")).strip()[:200]}
    try:
        os.kill(pid, 9)
        return {"method": "SIGKILL", "rc": 0}
    except Exception as exc:
        return {"method": "SIGKILL", "error": "%s: %s" % (type(exc).__name__, exc)}


#: 正在跑的任务（供 `/api/tasks/active` 与取消用）；键 = job_id
ACTIVE: dict[str, dict] = {}
ACTIVE_LOCK = threading.Lock()


def _append_task_log(rec: dict) -> None:
    """任务执行台账：**append-only**，超时/取消必须留痕（可事后审计）。

    ⚠️ **测试期不得写生产台账**（2026-09-29 实测踩到）：控制台的 `selfcheck` 任务会跑
    `pytest`，而测试本身又会调用任务/`submit` ⇒ 生产审计台账被测试行污染，
    真出现超时反而分不清是"线上超时"还是"测试造出来的"。
    判据用 pytest 自己设的 `PYTEST_CURRENT_TEST`：测试期把记录写到**临时目录**，
    仍然真实走一遍 append（行为照样被检验），只是不落在仓库里。
    """
    under_test = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    rec = {**rec, "source": "pytest" if under_test else "console"}
    try:
        target = (Path(tempfile.gettempdir()) / "memshop-task-runs-under-test.jsonl"
                  if under_test else TASK_LOG)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _exec_task_child(task: str, args: dict, *, job_id: str | None = None,
                     timeout_s: int | None = None) -> dict:
    """在子进程里执行任务；**超时即终止进程树**，并如实报告是否真的终止了。"""
    tmo = int(timeout_s or task_timeout(task))
    tmp = tempfile.mkdtemp(prefix="memstask-")
    out_json = Path(tmp) / "result.json"
    cmd = [sys.executable, "-B", str(Path(__file__).resolve()),
           "--exec-task", task, "--args-json", json.dumps(args, ensure_ascii=False),
           "--out-json", str(out_json)]
    t0 = time.time()
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, cwd=str(REPO))
    except OSError as exc:
        return {"task": task, "error": "无法启动子进程：%s" % exc, "timed_out": False,
                "duration_s": 0.0}
    if job_id:
        with ACTIVE_LOCK:
            ACTIVE[job_id] = {"job_id": job_id, "task": task, "pid": p.pid,
                              "started_at": t0, "timeout_s": tmo}
    timed_out, killed = False, None
    try:
        stdout, _ = p.communicate(timeout=tmo)
    except subprocess.TimeoutExpired:
        timed_out = True
        killed = _kill_tree(p.pid)
        try:
            stdout, _ = p.communicate(timeout=30)
        except Exception:
            stdout = ""
    finally:
        if job_id:
            with ACTIVE_LOCK:
                ACTIVE.pop(job_id, None)
    dur = round(time.time() - t0, 2)

    if timed_out:
        out = {"task": task, "timed_out": True, "timeout_s": tmo, "duration_s": dur,
               "kill": killed,
               "error": ("任务超过 %ds 未完成，已终止其进程树。**没有结果可用**；"
                         "可能是任务本身很慢，或卡在外部调用（COMSOL/ssh）。"
                         "若确认需要更长时间，请在任务注册表里调大 timeout_s。" % tmo),
               "stdout": (stdout or "")[-4000:],
               "note": "超时任务一律**不产出结果**，也不写入任何'完成'状态"}
    elif out_json.is_file():
        try:
            out = json.loads(out_json.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            out = {"task": task, "error": "子进程结果无法解析：%s" % exc,
                   "stdout": (stdout or "")[-2000:]}
        out.setdefault("duration_s", dur)
        out["timed_out"] = False
    else:
        out = {"task": task, "timed_out": False, "duration_s": dur,
               "error": ("子进程退出码 %s 且未产出结果文件（**不假装成功**）"
                         % getattr(p, "returncode", "?")),
               "stdout": (stdout or "")[-4000:]}
    out["pid"] = p.pid
    _append_task_log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "job_id": job_id,
                      "task": task, "timeout_s": tmo, "duration_s": dur,
                      "timed_out": bool(out.get("timed_out")),
                      "verdict": ("timeout" if out.get("timed_out")
                                  else ("error" if out.get("error") else "done")),
                      "kill": killed})
    # 失败通道：只有**非成功**终态才登记（取消已由 cancel_job 登记过，这里不重复）
    with JOBS_LOCK:
        was_cancelled = bool((JOBS.get(job_id) or {}).get("cancel_requested")) if job_id else False
    if not was_cancelled:
        _capture_task_incident(task, args, out, tmo)
    return out


def _exec_task_entry(task: str, args_json: str, out_json: str) -> int:
    """`--exec-task` 子进程入口：跑完把结果 JSON 写文件（日志走 stdout，两者分离）。"""
    try:
        args = json.loads(args_json or "{}")
    except ValueError as exc:
        Path(out_json).write_text(json.dumps({"error": "args-json 非法：%s" % exc},
                                            ensure_ascii=False), encoding="utf-8")
        return 2
    res = _run_task_inprocess(task, args)
    Path(out_json).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return 0


def _mc():
    """懒加载多通道代理运行时（`memsharness.multichannel_surrogate`）。"""
    global _MC_MOD
    if _MC_MOD is None:
        try:
            from memsharness import multichannel_surrogate as mod
            _MC_MOD = mod
        except Exception as exc:                      # 导入失败要显式说，不静默
            return None, "%s: %s" % (type(exc).__name__, exc)
    return _MC_MOD, None


_MC_MOD = None


def _mc_card() -> dict:
    mod, err = _mc()
    if mod is None:
        return {"error": "多通道代理不可用：%s" % err}
    try:
        return mod.model_card()
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def _mc_predict(q: dict) -> dict:
    """多通道一阶峰代理预测。**拒答时不返回任何数字**（只给原因）。"""
    mod, err = _mc()
    if mod is None:
        return {"error": "多通道代理不可用：%s" % err}
    try:
        chans = q.get("channels")
        if isinstance(chans, str):
            chans = [c for c in chans.split(",") if c]
        alpha = q.get("alpha")
        alpha = float(alpha) if alpha not in (None, "") else 0.05
        return mod.predict(q.get("x"), q.get("n1"), q.get("n2"),
                           channels=chans, alpha=alpha)
    except mod.Refused as exc:
        _capture_refusal("多通道预测 /api/mc/predict", exc,
                         params={"x": q.get("x"), "n1": q.get("n1"), "n2": q.get("n2"),
                                 "alpha": q.get("alpha")},
                         endpoint="/api/mc/predict")
        return {"refused": True, "reason": str(exc), "model_id": None,
                "action": "请改参数到适用域内，或改用 COMSOL / 一阶峰标签表核对"}
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


# ---------------------------------------------------------------------------
# 子智能体（离线可用）：**生成契约化载荷 + 落 append-only 台账**
#
# 离线模式能做什么、不能做什么（**必须在界面与文档里写清**）：
#   ✅ 能：列出 9 个角色 → 按角色契约生成**可注入载荷**（契约原文逐字节 + 任务 + 交付要求）
#          → 落 `work/role-spawns/spawn_ledger.jsonl`（append-only）→ 输出可复制的 prompt。
#   ❌ 不能：**离线模式绝不调用 LLM**，所以它**不会真跑一个子智能体**。
#          真正的 spawn 要么在 DSH 里由模型侧执行，要么切到 DeepSeek 模式（会联网）。
#   这条边界不是限制，是红线：离线模式的承诺就是"不发任何网络请求"。
# ---------------------------------------------------------------------------
def _agents_mod():
    """复用 `scripts/spawn_role.py`（与 MCP 的 role_payload **同一份实现**，不复制逻辑）。"""
    global _AGENTS_MOD
    if _AGENTS_MOD is None:
        try:
            _AGENTS_MOD = _load("_spawn_role_web", "scripts/spawn_role.py")
        except Exception:
            return None
    return _AGENTS_MOD


_AGENTS_MOD = None


def _agents_list() -> dict:
    mod = _agents_mod()
    if mod is None:
        return {"error": "spawn_role.py 不可用"}
    try:
        roles = mod.find_roles()
        rows = []
        for key, d in sorted(roles.items()):
            meta = json.loads((d / "agent.json").read_text(encoding="utf-8"))
            rows.append({"key": key, "role_id": mod._canon_id(meta, d),
                         "name": meta.get("name"), "kind": meta.get("kind"),
                         "status": meta.get("status"), "one_liner": meta.get("one_liner"),
                         "dir": mod.rel(d)})
        return {"n_roles": len(rows), "roles": rows,
                "offline_capability": ("离线模式可：生成契约化载荷 + 落 append-only 台账 + 输出可复制 prompt；"
                                       "**不可**：真正 spawn（那需要模型侧执行或 DeepSeek 模式联网）"),
                "boundary": "离线模式**绝不调用 LLM**——这是红线，不是功能缺失。"}
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def _agents_payload(body: dict) -> dict:
    """生成子智能体载荷（离线可用；**不 spawn、不联网**）。"""
    mod = _agents_mod()
    if mod is None:
        return {"error": "spawn_role.py 不可用"}
    role = str(body.get("role") or "").strip()
    task = str(body.get("task") or "").strip()
    if not role:
        return {"error": "必须指定角色（可用 /api/agents/list）"}
    if not task:
        return {"error": "必须给任务文本（空任务会被拒 —— 契约要求说清交付物）"}
    try:
        body_txt, rec = mod.build_payload(role, task, fields={})
        # 允许测试/其他调用方把产物与**台账**落到 work/ 下的别处，
        # 否则测试会污染真实的 spawn_ledger.jsonl（MCP 侧同款保护）。
        out_root = str(body.get("out_root") or "").strip()
        led_rel = str(body.get("ledger_path") or "").strip()
        if out_root:
            try:
                root = _check_path(out_root, under_work=True)
            except ValueError as exc:
                return {"error": "out_root 必须在 work/ 下：%s" % exc}
        else:
            root = mod.SPAWN_ROOT
        if led_rel:
            try:
                ledger = _check_path(led_rel, under_work=True)
            except ValueError as exc:
                return {"error": "ledger_path 必须在 work/ 下：%s" % exc}
        else:
            ledger = mod.LEDGER
        out = root / rec["spawn_id"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "prompt.md").write_text(body_txt, encoding="utf-8")
        (out / "spawn_record.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        led = mod.append_ledger(rec, ledger)
        return {"spawn_id": rec["spawn_id"], "role_id": rec["role_id"],
                "contract_path": rec["contract_path"],
                "contract_sha256": rec["contract_sha256"],
                "payload_sha256": rec["payload_sha256"],
                "prompt_path": str(out / "prompt.md"),
                "ledger_path": str(ledger),
                "prompt": body_txt,
                "ledger": led,
                "not_spawned": ("本控制台**不 spawn**（离线模式绝不调 LLM）："
                                "请把上面的 prompt 全文注入 DSH 的 subagent，"
                                "或切到 DeepSeek 模式让模型侧执行。"),
                "is_llm_involved": False}
    except SystemExit as exc:
        return {"error": "spawn_role 拒绝：%s" % exc}
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def _agents_ledger(q: dict) -> dict:
    """读 append-only 台账尾部（只读，用于核对「谁被点名过」）。"""
    mod = _agents_mod()
    if mod is None:
        return {"error": "spawn_role.py 不可用"}
    try:
        n = int(q.get("tail") or 20)
    except (TypeError, ValueError):
        n = 20
    led = mod.LEDGER
    if not led.is_file():
        return {"n_total": 0, "tail": [], "path": str(led),
                "note": "台账尚未创建（还没生成过任何载荷）"}
    lines = [l for l in led.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    tail = []
    for ln in lines[-max(1, min(n, 200)):]:
        try:
            r = json.loads(ln)
            tail.append({k: r.get(k) for k in ("spawn_id", "role_id", "created",
                                               "contract_sha256", "payload_sha256")})
        except ValueError:
            tail.append({"raw": ln[:200]})
    return {"n_total": len(lines), "tail": tail, "path": str(led),
            "append_only": "本台账 append-only；同 spawn_id 同内容幂等、内容不同拒收"}


def _mc_screen(q: dict) -> dict:
    """多通道代理的**网格筛查**（逐目标排名；不含加权总分）。"""
    mod, err = _mc()
    if mod is None:
        return {"error": "多通道代理不可用：%s" % err}

    def _f(key, default, cast=float):
        v = q.get(key)
        return default if v in (None, "") else cast(v)

    try:
        return mod.screen(
            x_min=_f("x_min", 0.20), x_max=_f("x_max", 1.00), x_step=_f("x_step", 0.05),
            n1_min=_f("n1_min", 1, int), n1_max=_f("n1_max", 7, int),
            n2_min=_f("n2_min", 5, int), n2_max=_f("n2_max", 8, int),
            channels=([c for c in str(q["channels"]).split(",") if c] if q.get("channels") else None),
            alpha=_f("alpha", 0.05), top=_f("top", 5, int))
    except mod.Refused as exc:
        # 网格筛查的 `Refused` = **整张网都与适用域无交集**（逐点拒答不抛异常，属正常结果）
        # ⇒ 只登记这一种，否则一次筛查会往台账里灌几百条
        _capture_refusal("网格筛查 /api/mc/screen 整张网不可预测", exc,
                         params={k: q.get(k) for k in
                                 ("x_min", "x_max", "x_step", "n1_min", "n1_max",
                                  "n2_min", "n2_max", "alpha")},
                         endpoint="/api/mc/screen")
        return {"refused": True, "reason": str(exc),
                "action": "把参数改回适用域内（x∈[0.20,1.00]、N1<N2∈[5,9]）"}
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def _glossary() -> dict:
    """数据字典：**只解释、不计算**（每个参数与结果名字的说明）。"""
    global _GLOSS_MOD
    if _GLOSS_MOD is None:
        try:
            from memsharness import glossary as mod
            _GLOSS_MOD = mod
        except Exception as exc:
            return {"error": "数据字典不可用：%s: %s" % (type(exc).__name__, exc)}
    try:
        return _GLOSS_MOD.payload()
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


_GLOSS_MOD = None


# ---------------------------------------------------------------------------
# 失败通道（2026-09-30）：把「平台没做成的这件事」变成**可发送的分析包**
#
# 用户口径（当场选定，别擅自扩大）：
#   * 收哪些：任务失败/超时/取消、代理拒答、页面脚本异常、服务不可用、接口异常 + 人工上报；
#   * 发到哪：**只生成自包含包**（md + json，一键复制），由人发给 Codex 或助手；
#     **本控制台不外发**（不调任何外部 API）⇒ 离线模式功能完整；
#   * 包里放什么：现象 + **原始错误全文（含堆栈）** + 当时的输入与调用（端点/参数/复现命令）。
#     日志尾部、环境事实、其它在跑任务 —— 用户明确没勾，**不加**。
#
# ⚠️ 一处刻意的**不**采集：MCP 侧看到 `console_unavailable` 时**不登记**。
#   本仓库的既定策略是控制台"按需启动、不常驻"（docs/WEB_SERVICES.md §3.3）
#   ⇒ 「控制台没在跑」是**正常状态**，登记它会把失败通道淹掉。
#   只有"人正在用页面、请求却没应答"才算失败 ⇒ 由页面侧的 fetch 失败来登记。
# ---------------------------------------------------------------------------
_INC_MOD = None
#: 每个请求一个（ThreadingHTTPServer 每个连接一个 Handler 实例），标记"别登记失败"
_REQ = threading.local()


def _inc_suppressed() -> bool:
    """本次请求是否声明了「不要登记失败通道」。

    为什么要这个开关：**例行复检本身会制造拒答**（`verify_web_services.py` 每轮都跑一个
    域外预测用例）。实测：一次两轮复检就往生产台账塞了 2 条 refusal —— 它们不是
    任何人遇到的问题，却会把失败通道的质量稀释掉。诊断方（复检脚本、页面运行时探针）
    用 `X-MEMS-No-Incident: 1` 或 `?no_incident=1` **如实声明**自己不是人的操作。

    ⚠️ 覆盖面**仅限于同步采集**（拒答、接口异常）；任务类事件发生在**别的线程**里，
    thread-local 传不过去 —— 按设计仍会登记（任务失败本来就是值得看的事件）。
    """
    return bool(getattr(_REQ, "no_incident", False))


def _inc():
    """惰性取失败通道模块；不可用时返回 (None, 原因)。"""
    global _INC_MOD
    if _INC_MOD is None:
        try:
            sys.path.insert(0, str(REPO / "src"))
            from memsharness import incidents as mod
            _INC_MOD = mod
        except Exception as exc:
            return None, "%s: %s" % (type(exc).__name__, exc)
    return _INC_MOD, None


def _capture_task_incident(task: str, args: dict, out: dict, tmo: int) -> None:
    """任务**非成功终态**才登记（成功不登记）；本函数自身出错绝不掩盖原始失败。"""
    try:
        mod, err = _inc()
        if mod is None:
            return
        if out.get("timed_out"):
            kind = "task_timeout"
            sym = ("任务超过 %ds 未完成，已终止其进程树 ⇒ **没有结果可用**。"
                   "可能是任务本身很慢，或卡在外部调用（COMSOL/ssh）。" % tmo)
        elif out.get("error"):
            kind = "task_failed"
            sym = "任务返回错误、未产出可用结果（**不假装成功**）。"
        else:
            return
        raw = "\n".join(x for x in (str(out.get("error") or ""),
                                    str(out.get("stdout") or "")) if x.strip())
        mod.record(kind, sym, source="console", task=task, args=args,
                   endpoint="/api/run", method="POST",
                   params={"task": task, "confirm": bool(args.get("confirm"))},
                   error_text=raw)
    except Exception:
        return


def _inc_list(q: dict) -> dict:
    mod, err = _inc()
    if mod is None:
        return {"error": "失败通道不可用：%s" % err}
    try:
        limit = int(q.get("limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    r = mod.load(limit=limit)
    r["counts"] = mod.counts()
    r["package_root"] = str(mod.package_root())
    r["ledger"] = str(mod.ledger_path().relative_to(REPO)).replace("\\", "/") \
        if str(mod.ledger_path()).startswith(str(REPO)) else str(mod.ledger_path())
    r["no_send"] = ("包本身**只落本机**（`work/runs/incidents/`），控制台不直接调用任何外部 API。"
                    "要不要交给 DSH 分析由**你按按钮**决定：那会在本机启动一次 "
                    "`dsh --profile headless` 做**只读分析**（它可能联网调模型）——"
                    "离线模式下这个动作被禁用。")
    r["what_is_collected"] = {k: v for k, v in mod.KINDS.items()}
    return r


def _inc_one(q: dict) -> dict:
    mod, err = _inc()
    if mod is None:
        return {"error": "失败通道不可用：%s" % err}
    iid = str(q.get("incident_id") or "")
    rec = mod.get(iid) if iid else None
    if rec is None:
        return {"error": "没有这条记录：%s" % iid}
    return {"record": rec, "md": mod.render_md(rec)}


def _inc_record(q: dict) -> dict:
    mod, err = _inc()
    if mod is None:
        return {"error": "失败通道不可用：%s" % err}
    # 诊断/探针请求（`?no_incident=1` 或 `X-MEMS-No-Incident`）**连显式上报也不落库**：
    # 否则"跑一次页面探针"就会往生产台账里塞一条人工上报（实测发生过）。
    if _inc_suppressed():
        return {"recorded": False, "diagnostic": True,
                "incident_id": "inc-diagnostic-%s" % mod.new_id("manual")[4:],
                "kind": str(q.get("kind") or "manual"), "redacted_hits": 0,
                "note": "诊断请求：**没有写入台账**（这是探针，不是人的操作）"}
    try:
        rec = mod.record(
            str(q.get("kind") or "manual"), str(q.get("symptom") or ""),
            source=str(q.get("source") or "page"),
            endpoint=str(q.get("endpoint") or ""), method=str(q.get("method") or ""),
            params=q.get("params"), task=str(q.get("task") or ""), args=q.get("args"),
            error_text=str(q.get("error_text") or ""), stack=str(q.get("stack") or ""),
            repro=str(q.get("repro") or ""))
    except ValueError as exc:
        return {"error": str(exc), "valid_kinds": sorted(mod.KINDS)}
    return {"recorded": True, "incident_id": rec["incident_id"], "kind": rec["kind"],
            "kind_zh": rec["kind_zh"], "redacted_hits": rec["redacted_hits"],
            "repro": rec["repro"]}


def _inc_package(q: dict) -> dict:
    mod, err = _inc()
    if mod is None:
        return {"error": "失败通道不可用：%s" % err}
    iid = str(q.get("incident_id") or "")
    if not iid:
        return {"error": "缺少 incident_id"}
    if q.get("write"):
        return mod.write_package(iid, out_root=q.get("out_dir"))
    return mod.package(iid)


# ---------------------------------------------------------------------------
# 上报给 DSH（2026-09-30）：**只读分析**、**只在人点按钮时**、**离线模式禁止**
#
# 用户口径（当场选定）：① DSH 只给根因与修复建议，**不改任何文件**；
# ② 不做自动触发；③ 离线模式不许可 —— 控制台离线时承诺"不发任何网络请求"，
# 而 headless DSH 会联网调模型。三条都必须是**代码里的门禁**，不是界面上的提示。
# ---------------------------------------------------------------------------
_DSH_MOD = None


def _dsh():
    global _DSH_MOD
    if _DSH_MOD is None:
        try:
            sys.path.insert(0, str(REPO / "src"))
            from memsharness import dsh_report as mod
            _DSH_MOD = mod
        except Exception as exc:
            return None, "%s: %s" % (type(exc).__name__, exc)
    return _DSH_MOD, None


def _dsh_start(q: dict) -> dict:
    """启动一次 headless DSH 只读分析。门禁：模式 / confirm / 去重 / dsh 可解析。"""
    mod, err = _dsh()
    if mod is None:
        return {"error": "上报模块不可用：%s" % err}
    inc, ierr = _inc()
    if inc is None:
        return {"error": "失败通道不可用：%s" % ierr}
    iid = str(q.get("incident_id") or "")
    if not iid:
        return {"error": "缺少 incident_id"}
    # ① 离线模式禁止（用户选的第三条）—— **放在查记录之前**：这是安全门禁，
    #    不该因为"这条记录恰好不存在"而绕过（自检正是用不存在的 id 抓到这一点的）。
    if STATE.get("mode") != "deepseek":
        return {"error": "离线模式不发起上报：本控制台离线时承诺不发任何网络请求，"
                         "而 headless DSH 会联网调模型。请先切到 DeepSeek 模式。",
                "mode": STATE.get("mode"), "blocked_by": "offline_mode"}
    # ② 花 token 的动作必须显式确认（与写产物任务同款约定）
    if not q.get("confirm"):
        return {"error": "上报会真的启动一次 headless DSH（消耗 token），需要 confirm=true",
                "needs_confirmation": True, "incident_id": iid}
    rec = inc.get(iid)
    if rec is None:
        return {"error": "没有这条记录：%s" % iid}
    # ③ 同一条失败不许并行重复跑
    run = mod.running(iid)
    if run:
        return {"error": "这条失败已有一个上报在跑（%s），等它结束再发起。"
                 % run.get("report_id"), "running": run}
    # ④ dsh 必须先能解析出来（解析不了就如实说，不猜路径）
    pre, how = mod.find_dsh()
    if pre is None:
        return {"error": how, "hint": "设环境变量 DSH_BIN 指向 dsh 可执行文件或 lib/bin.js"}
    pk = inc.package(iid)
    if "error" in pk:
        return pk
    started = mod.start_report(iid, pk["md"], timeout_s=int(q.get("timeout_s") or 1800),
                              confirm_spawn=True)
    if "error" in started:
        return started
    jid = "dsh-" + str(started.get("report_id"))
    with JOBS_LOCK:
        JOBS[jid] = {"task": "dsh_report", "status": "running", "args": {"incident_id": iid},
                     "started_at": time.time(), "report_id": started.get("report_id"),
                     "job_id": jid}
    threading.Thread(target=_dsh_wait, args=(jid, started), daemon=True).start()
    started.update({"job_id": jid, "how": how, "mode": STATE.get("mode"),
                    "readonly": True,
                    "note": "已在后台启动 headless DSH 做**只读分析**（不改任何文件）；"
                            "结果写进上报目录的 stdout.txt / analysis.md，并记入台账。"})
    return started


def _dsh_wait(jid: str, started: dict) -> None:
    """后台等 headless DSH 结束（超时杀进程树），并把结论回填台账。"""
    mod, err = _dsh()
    if mod is None:
        return
    try:
        upd = mod.finish_report(started.get("report_id"),
                               timeout_s=int(started.get("timeout_s") or 1800))
        with JOBS_LOCK:
            if jid in JOBS:
                JOBS[jid]["status"] = upd.get("status")
                JOBS[jid]["finished_at"] = upd.get("finished_at")
                JOBS[jid]["exit_code"] = upd.get("exit_code")
    except Exception as exc:               # 回填失败也必须留痕，不能静默
        with JOBS_LOCK:
            if jid in JOBS:
                JOBS[jid]["status"] = "failed"
                JOBS[jid]["error"] = "%s: %s" % (type(exc).__name__, exc)


def _dsh_reports(q: dict) -> dict:
    mod, err = _dsh()
    if mod is None:
        return {"error": "上报模块不可用：%s" % err}
    r = mod.load_reports(incident_id=(str(q.get("incident_id")) if q.get("incident_id") else None),
                         limit=int(q.get("limit") or 20))
    pre, how = mod.find_dsh()
    r["dsh_available"] = pre is not None
    r["dsh_how"] = how
    r["mode"] = STATE.get("mode")
    r["allowed"] = STATE.get("mode") == "deepseek"
    r["readonly"] = True
    r["rules"] = list(mod.READONLY_RULES)
    r["boundary"] = ("上报 = 在本机启动一次 `dsh --profile headless`（DSH 自带的一次性任务接口，"
                     "不开端口、不留后台服务）。它做**只读分析**：只给根因与修复建议，"
                     "**不改仓库里任何文件**。离线模式下这个动作被禁用。")
    return r


def _capture_refusal(where: str, exc: object, *, params: dict, method: str = "GET",
                     endpoint: str = "") -> None:
    """代理**拒答**也要能被送去分析（用户明确要求收这一面）。

    拒答本身是**正常的 fail-closed 行为**，所以包里不写"错误"，写清它是拒答：
    `error_text` 留空、`symptom` 说明原因 ⇒ 免得接收方把"正确地拒答"当成 bug 去"修"。
    """
    try:
        if _inc_suppressed():
            return
        mod, err = _inc()
        if mod is None:
            return
        mod.record("refusal", "代理拒答（**这是设计中的 fail-closed 行为**，不是崩溃）：%s"
                   % exc, source="console", endpoint=endpoint or where, method=method,
                   params=params, error_text="")
    except Exception:
        return


def _record_api_error(exc: BaseException, method: str, path: str = "",
                      tb: str = "") -> None:
    """接口未处理异常 ⇒ 登记（带完整堆栈），供人一键生成分析包。

    刻意**不接收 `self`**：处理函数里拿 `self` 容易把"记录失败"和"回应失败"耦合在一起，
    这里只要路径 + 堆栈两样事实（初版写成从 `self` 取路径，直接引用了不存在的变量）。
    """
    try:
        if _inc_suppressed():
            return
        mod, err = _inc()
        if mod is None:
            return
        mod.record("api_error",
                   "接口 %s %s 抛出未处理异常，请求未完成（**没有结果**）。" % (method, path),
                   source="console", endpoint=path, method=method,
                   error_text="%s: %s" % (type(exc).__name__, exc),
                   stack=tb or traceback.format_exc())
    except Exception:
        return


def _run_task_sync(task: str, args: dict) -> dict:
    """同步跑一个任务（HTTP/对话路径的统一入口，**子进程 + 真超时**）。"""
    if task not in TASKS:
        return {"error": "未登记任务：%s" % task}
    if task == "role_payload" and not (args.get("task") or "").strip():
        return {"error": "role_payload 需要 task 文本（空任务会被拒）"}
    args = dict(args)
    if TASKS[task].get("writes") and not args.get("confirm"):
        return {"needs_confirmation": True, "task": task,
                "title": TASKS[task]["title"], "args": args}
    with EXEC_LOCK:                      # 保持「求解/写产物单实例串行」的既有约束
        return _exec_task_child(task, args)


def _summarize(tool_res: dict) -> str:
    """把任务结果压成一段给模型/用户看的摘要（**只复述代码给的裁决**）。"""
    r = tool_res.get("result") or {}
    if tool_res.get("error"):
        return "任务 %s 失败：%s" % (tool_res.get("task"), tool_res["error"])
    if r.get("needs_confirmation"):
        return "需要用户确认：%s（%s）" % (r.get("title"), r.get("task"))
    bits = []
    for k in ("verdict", "release_allowed", "publish_allowed", "provisional"):
        if k in r:
            bits.append("%s=%s" % (k, r[k]))
    if r.get("verdict_by_family"):
        bits.append("逐族=" + json.dumps(r["verdict_by_family"], ensure_ascii=False))
    if r.get("stop_reasons"):
        bits.append("停止条件=" + "；".join(r["stop_reasons"])[:200])
    if r.get("median_MHz") is not None:
        bits.append("一阶峰中位=%s MHz（有峰 %s/%s，18–22MHz 内 %s 个）"
                    % (r["median_MHz"], r.get("n_with_first_peak"), r.get("n_total"),
                       r.get("within_18_22MHz")))
    if r.get("parsed"):
        bits.append("远端=" + json.dumps(r["parsed"], ensure_ascii=False))
    if r.get("report"):
        bits.append("入库=" + json.dumps(r["report"], ensure_ascii=False)[:200])
    if r.get("tops"):
        bits.append("排名条目 %d 条" % len(r["tops"]))
    if r.get("recommended"):
        bits.append("推荐候选 %d 个" % len(r["recommended"]))
    if r.get("counts"):
        bits.append("计数=" + json.dumps(r["counts"], ensure_ascii=False))
    if r.get("summary"):
        bits.append(str(r["summary"])[:120])
    if r.get("raw"):
        bits.append("原始=" + " | ".join(r["raw"])[:160])
    src = [a["path"].split("\\")[-1] + "@" + a["sha256"][:8] for a in (r.get("artifacts") or [])]
    if src:
        bits.append("产物=" + ", ".join(src))
    if r.get("script"):
        bits.append("脚本=%s@%s" % (r["script"]["path"], (r["script"].get("sha256") or "")[:8]))
    return "；".join(bits) if bits else json.dumps(r, ensure_ascii=False)[:300]


def _default_args(task: str) -> dict:
    """从任务声明的 `params` 默认值拼出参数（**不猜**：声明里没有就不给）。"""
    return {p["name"]: p.get("default") for p in TASKS[task]["params"] if p.get("default") is not None}


def _route(user: str) -> str | None:
    """关键词路由：**按命中关键字的个数取最高分**，同分按声明顺序取先者。

    为什么不用"第一个命中就返回"：一句话常同时提到两件事
    （实测「本地镜像和远端哈希对不对得上」同时命中 `远端` 与 `镜像`+`哈希`），
    先到先得会选错任务；按命中数打分才符合"用户到底在问哪个"。"""
    low = user.lower()
    best, best_n = None, 0
    for keys, task in LOCAL_ROUTES:
        n = sum(1 for k in keys if k in low)
        if n > best_n:
            best, best_n = task, n
    return best


RUN_VERB = re.compile(r"(跑|执行|运行|重跑|重算|重新|生成|重建|更新|刷新|开始|来一?[下份])")


def _preroute(user: str) -> tuple[list[dict], list[dict], str | None]:
    """**确定性**预路由：用户若显式说"跑/执行 X"，就先替他把工具跑起来/挂上确认卡。

    为什么要它：实测模型会**只在文字里描述参数**而不真的发起工具调用，
    于是前端渲染不出『允许执行』卡片（用户点不到），但文字又说"等你确认"——口径不一致。
    这里把"该不该动工具"从模型的自觉，改成代码的事实：
    * 只读任务 → 直接跑（拿真结果）；
    * 写产物任务 → **不跑**，返回 `needs_confirmation` 供前端渲染确认卡（红线不变）。
    返回 `(trace, pending, hint)`。"""
    task = _route(user)
    if not task or not RUN_VERB.search(user):
        return [], [], None
    args = _default_args(task)
    if task == "role_payload":
        args["task"] = user
    if not TASKS[task].get("writes"):
        args["confirm"] = True
    res = _run_task_sync(task, args)
    if res.get("needs_confirmation"):
        return [], [res], "已为用户挂上确认卡：%s（参数 %s）。用户尚未确认，不要声称它已执行。" % (
            task, json.dumps(res.get("args"), ensure_ascii=False))
    return [res], [], "已代用户执行只读任务 %s，摘要：%s。直接基于该结果回答，不要重复调用。" % (
        task, _summarize(res)[:600])


def do_chat(payload: dict) -> dict:
    """一轮对话：LLM 决定调哪些工具；读类直接执行，写类只提议。"""
    user = str(payload.get("message") or "").strip()
    history = list(payload.get("history") or [])[-12:]
    if not user:
        return {"error": "消息为空"}
    pre_trace, pre_pending, hint = _preroute(user)
    handled = {t.get("task") for t in pre_trace} | {p.get("task") for p in pre_pending}
    key, src = load_api_key()
    # **显式模式**：默认离线（绝不默认联网）。只有用户切到 DeepSeek 且服务端确有凭据才走 LLM。
    if STATE["mode"] == "deepseek" and key:
        mode = "llm"
    elif STATE["mode"] == "deepseek" and not key:
        return {"error": "已请求 DeepSeek 模式，但服务端此刻取不到 API key（来源：%s）⇒ "
                         "请配置环境变量 DEEPSEEK_API_KEY 或 ~/.dsh/.credentials.yaml，"
                         "或切回离线模式。" % src}
    else:
        mode = "local"
    used = None
    if mode == "llm":
        sysmsg = SYSTEM_PROMPT + (("\n【平台预路由】" + hint) if hint else "")
        messages = [{"role": "system", "content": sysmsg}] + history + \
                   [{"role": "user", "content": user}]
        trace, pending = list(pre_trace), list(pre_pending)
        try:
            for _step in range(4):
                resp = _llm_call(messages, _tool_specs())
                used = resp.get("_used")
                msg = (resp.get("choices") or [{}])[0].get("message") or {}
                calls = msg.get("tool_calls") or []
                if calls:
                    messages.append(msg)
                    for c in calls:
                        fn = (c.get("function") or {})
                        name = fn.get("name") or ""
                        try:
                            args = json.loads(fn.get("arguments") or "{}")
                        except Exception:
                            args = {}
                        if name not in TASKS:
                            body = "未登记任务 %s" % name
                        elif name in handled:
                            # 预路由已经处理过：别重复跑 / 别重复挂卡，把已有结果回给它
                            body = "该任务已处理（%s），结果已在本轮返回给用户，请勿重复调用。" % (
                                "等待用户确认" if any(p.get("task") == name for p in pending)
                                else "已执行")
                        else:
                            res = _run_task_sync(name, args)
                            handled.add(name)
                            if res.get("needs_confirmation"):
                                pending.append(res)
                                body = "已提议执行 %s（等待用户确认），参数 %s" % (
                                    name, json.dumps(args, ensure_ascii=False))
                            else:
                                trace.append(res)
                                body = _summarize(res)
                        messages.append({"role": "tool", "tool_call_id": c.get("id"),
                                         "content": body[:4000]})
                    continue
                reply = (msg.get("content") or "").strip()
                if not reply and not trace and not pending:
                    reply = "（模型没有给出回答，也没有调用任何工具。）"
                # 兜底：模型一次工具都没调 → 至少把命中的本地路由跑掉，别让回答悬空
                if not trace and not pending:
                    fb = _fallback_route(user)
                    if fb:
                        trace, pending = fb
                        reply += "\n\n" + ("（模型未调用工具；已按本地路由%s：%s）"
                                           % ("执行只读任务" if trace else "挂上确认卡",
                                              _summarize(trace[0]) if trace else
                                              TASKS[pending[0]["task"]]["title"]))
                return {"mode": "llm", "reply": reply, "tool_trace": trace,
                        "pending": pending, "llm": used, "key_source": src}
            return {"mode": "llm", "reply": "（工具调用步数达上限，未继续）",
                    "tool_trace": trace, "pending": pending, "llm": used}
        except Exception as exc:
            mode = "local"
            note = "LLM 不可用（%s），已切到本地指令模式。" % str(exc)[:160]
    else:
        note = "**离线模式**：不发任何网络请求，按本地关键词路由处理（非 LLM 生成）。"
    # ---- 本地指令路由 ----
    res = _local_route_run(user, note)
    if res is not None:
        return res
    return {"mode": "local", "reply": note + "\n我能直接跑这些：\n" + "\n".join(
        "- %s：%s" % (k, v["title"]) for k, v in TASKS.items())
        + "\n\n试试：『一阶谐振在哪』『跑 A5 排名』『远端清单』『校验镜像』。",
        "tool_trace": [], "pending": []}


def _extra_info(user: str) -> str:
    """离线模式下的补充说明：明确「没有 LLM 参与」，避免把关键词路由当成理解。"""
    return ("（离线：仅本地关键词路由，**非 LLM 生成**；如需自然语言理解请在右上角切到 "
            "DeepSeek 模式。拒答/裁决类字段一律以代码输出为准。）")


def _local_route_run(user: str, note: str) -> dict | None:
    """本地关键词路由：命中就真的跑（读类）或挂确认卡（写类）；未命中返回 None。"""
    task = _route(user)
    if not task:
        return None
    args = _default_args(task)
    if task == "role_payload":
        args["task"] = user
    args.setdefault("confirm", True)
    res = _run_task_sync(task, args)
    tail = "" if STATE["mode"] == "deepseek" else "\n\n" + _extra_info(user)
    if res.get("needs_confirmation"):
        return {"mode": "local", "reply": "「%s」会写产物，已挂上确认卡，点『允许执行』才会跑。"
                % TASKS[task]["title"] + tail, "pending": [res], "tool_trace": []}
    return {"mode": "local", "reply": "%s\n\n%s%s" % (note, _summarize(res), tail),
            "tool_trace": [res], "pending": []}


def _fallback_route(user: str) -> tuple[list[dict], list[dict]] | None:
    """LLM 一次工具都没调时的兜底：把命中的路由**真的**跑掉/挂卡。

    保证"回答有工具支撑"这条红线不因为模型的自觉而失守；未命中路由返回 None。
    复用 `_local_route_run`（同一套白名单 + confirm 规则），**不另开旁路**。"""
    res = _local_route_run(user, "")
    if res is None:
        return None
    return res["tool_trace"], res["pending"]


# ---------------------------------------------------------------------------
# 任务注册表（白名单）：前端据此渲染表单
# ---------------------------------------------------------------------------
TASKS: dict[str, dict] = {
    "state": {"fn": task_state, "title": "平台状态", "group": "总览", "writes": False,
              "params": []},
    "dashboard": {"fn": task_dashboard, "title": "重建静态看板", "group": "展示", "writes": True,
                  "params": [{"name": "out_dir", "type": "path", "default": "work/reports/mems-dashboard"},
                             {"name": "generated_at", "type": "text", "default": ""}]},
    "sweep_analysis": {"fn": task_sweep_analysis, "title": "A5 扫描分析（分族分指标排名）",
                       "group": "分析", "writes": True, "role": "A5",
                       "params": [{"name": "csv", "type": "path", "default": "work/runs/remote-exported-20260922/a5/metric_table.csv"},
                                  {"name": "preset", "type": "select",
                                   "options": ["cell_te2-exported", "pmut-structure-summary"],
                                   "default": "cell_te2-exported"},
                                  {"name": "candidate_grid", "type": "path",
                                   "default": "work/runs/remote-exported-20260922/a5/candidate_grid.json"},
                                  {"name": "budget", "type": "int", "default": 6},
                                  {"name": "min_effective", "type": "int", "default": 5},
                                  {"name": "out_dir", "type": "path",
                                   "default": "work/reports/webapp/sweep"}]},
    "report_gate": {"fn": task_report_gate, "title": "A9 报告门禁", "group": "分析", "writes": True,
                    "role": "A9",
                    "params": [{"name": "bundle", "type": "path",
                                "default": "work/runs/remote-exported-20260922/bundle_platform.json"},
                               {"name": "known_ids", "type": "path",
                                "default": "work/runs/remote-exported-20260922/known_ids.json"},
                               {"name": "gate", "type": "path", "default": ""},
                               {"name": "out_dir", "type": "path",
                                "default": "work/reports/webapp/report"}]},
    "freeze_gate": {"fn": task_freeze_gate, "title": "A8 冻结门禁（只读）", "group": "验证",
                    "writes": False, "role": "A8",
                    "params": [{"name": "target_dir", "type": "path",
                                "default": "work/runs/phase0-field-holdout-20260915/freezes/freeze_phase1-executor-20260915-06"}]},
    "a6_eval": {"fn": task_a6_eval, "title": "A6 代理评估（第 1/2/3 轮）", "group": "AI 求解器",
                "writes": True, "role": "A6",
                "params": [{"name": "round", "type": "select", "options": ["1", "2", "3"],
                            "default": "3"}]},
    "fpeak_stats": {"fn": task_fpeak_stats, "title": "谐振频率统计（两种口径）", "group": "分析",
                    "writes": True, "params": []},
    "x_plan": {"fn": task_x_plan, "title": "x 加密清单（只出清单）", "group": "优化",
               "writes": True, "params": []},
    "verify_mirror": {"fn": task_verify_mirror, "title": "镜像哈希校验（269 文件）",
                      "group": "数据", "writes": False, "role": "A4", "params": []},
    "ingest_dataset": {"fn": task_ingest_dataset, "title": "解析镜像 → 数据集（不写库）",
                       "group": "数据", "writes": True, "role": "A4", "params": []},
    "store_ingest": {"fn": task_store_ingest, "title": "入库（append-only，写数据库）",
                     "group": "数据", "writes": True, "role": "A4", "params": []},
    "role_payload": {"fn": task_role_payload, "title": "角色点名（生成注入载荷）",
                     "group": "子智能体", "writes": True,
                     "params": [{"name": "role", "type": "select",
                                 "options": ["a1-contract-governance", "a2-model-onboarding-audit",
                                             "a3-comsol-execution", "a4-data-provenance",
                                             "a5-sweep-analysis-optimization",
                                             "a6-scalar-surrogate", "a7-ai-field-solver",
                                             "a8-verification-freeze", "a9-report-augment"],
                                 "default": "a8-verification-freeze"},
                                {"name": "task", "type": "textarea", "default": ""}]},
    "remote_inventory": {"fn": task_remote_inventory, "title": "远端只读清单（ssh）",
                         "group": "数据", "writes": False, "params": []},
    "selfcheck": {"fn": task_selfcheck, "title": "离线自检（跑测试子集）", "group": "验证",
                  "writes": False, "params": []},
    # ---- 响应级代理（**不是 AI 求解器**）：只读，供侧栏与对话里的 LLM 调用 ----
    # `fn` 在文件后面定义后**补挂**（见 `_register_surrogate_tasks()`），避免前向引用。
    "surrogate_card": {"fn": None, "title": "代理模型卡（身份/区间/红线）", "group": "响应级代理",
                       "writes": False, "role": "A6", "params": []},
    "surrogate_coverage": {"fn": None, "title": "代理可答域普查（含拒答）", "group": "响应级代理",
                           "writes": False, "role": "A6", "params": []},
    # ---- 多通道一阶峰代理：只读查询 + 一个"重导出模型"的写任务 ----
    "mc_export": {"fn": None, "title": "重导出多通道模型（用全部数据重拟合）",
                  "group": "多通道代理", "writes": True, "params": []},
    "mc_card": {"fn": None, "title": "多通道模型卡（8 通道/适用域/短板）",
                "group": "多通道代理", "writes": False, "params": []},
}

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
#: 任务**执行**串行化：`contextlib.redirect_stdout` 是**进程级**的（会把别的线程的打印也吞掉），
#: 而且本平台要求写库/写产物单实例串行 ⇒ 用一把全局锁把执行段串起来（前端仍异步轮询）。
EXEC_LOCK = threading.Lock()


def submit(task: str, args: dict) -> dict:
    if task not in TASKS:
        return {"error": "未登记的任务：%r" % task, "allowed": sorted(TASKS)}
    spec = TASKS[task]
    if spec.get("writes") and not args.get("confirm"):
        return {"error": "该任务会写产物，需带 confirm=true", "task": task, "writes": True}
    jid = "%s-%d" % (task, int(time.time() * 1000) % 1000000)
    with JOBS_LOCK:
        JOBS[jid] = {"id": jid, "task": task, "title": spec["title"], "status": "running",
                     "submitted_local": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "args": {k: v for k, v in args.items() if k != "confirm"}}

    def _run() -> None:
        t0 = time.time()
        try:
            with EXEC_LOCK:                     # 串行（写产物/写库单实例）
                out = _exec_task_child(task, args, job_id=jid)
            with JOBS_LOCK:
                if JOBS[jid].get("cancel_requested"):
                    JOBS[jid].update({"status": "cancelled", "duration_s": out.get("duration_s"),
                                      "stdout": out.get("stdout", ""),
                                      "result": None})
                    return
                if out.get("timed_out"):
                    JOBS[jid].update({"status": "timeout", "timed_out": True,
                                      "timeout_s": out.get("timeout_s"),
                                      "kill": out.get("kill"),
                                      "duration_s": out.get("duration_s"),
                                      "error": out.get("error"),
                                      "stdout": out.get("stdout", "")})
                    return
                if out.get("error"):
                    JOBS[jid].update({"status": "error", "error": out["error"],
                                      "duration_s": out.get("duration_s"),
                                      "stdout": out.get("stdout", "")})
                    return
                JOBS[jid].update({"status": "done", "result": out.get("result"),
                                  "duration_s": out.get("duration_s"),
                                  "stdout": out.get("stdout", "")})
        except Exception as exc:
            with JOBS_LOCK:
                JOBS[jid].update({"status": "error",
                                  "error": "%s: %s" % (type(exc).__name__, str(exc)[:400]),
                                  "traceback": traceback.format_exc()[-1500:],
                                  "duration_s": round(time.time() - t0, 1)})

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": jid, "task": task, "status": "running",
            "timeout_s": task_timeout(task), "poll": "/api/job/%s" % jid,
            "cancel": "/api/job/%s/cancel" % jid}


def jobs_snapshot() -> dict:
    """任务可见性：每个 job 的**耗时/超时额度/剩余**，外加"正在跑"的进程信息。

    为什么需要它：界面此前只能等，看不出"跑了多久、还能跑多久、超时了没有"
    （用户要求"任务超时可见性"）。这里把三类信息一次给全：
      * 已完成/失败/超时/取消 —— 状态 + 实际耗时 + 是否真的被终止；
      * 正在跑 —— 已耗时、超时额度、剩余秒数、pid；
      * 超时台账行数（append-only，可审计）。
    """
    now = time.time()
    with ACTIVE_LOCK:
        active = [{**a, "elapsed_s": round(now - a["started_at"], 1),
                   "remaining_s": max(0, round(a["timeout_s"] - (now - a["started_at"]), 1))}
                  for a in ACTIVE.values()]
    by_id = {a["job_id"]: a for a in active}
    with JOBS_LOCK:
        items = []
        for jid, j in JOBS.items():
            a = by_id.get(jid)
            items.append({**j, "job_id": jid,
                          # 正在跑的 job：给出**实时**已耗时与剩余额度（否则只有终态耗时）
                          "elapsed_s": (a["elapsed_s"] if a else j.get("duration_s")),
                          "timeout_s": j.get("timeout_s") or task_timeout(j.get("task", "")),
                          "remaining_s": (a["remaining_s"] if a else None)})
    n_timeout = 0
    if TASK_LOG.is_file():
        try:
            for ln in TASK_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
                if ln.strip() and json.loads(ln).get("timed_out"):
                    n_timeout += 1
        except (OSError, ValueError):
            pass
    return {"active": active, "n_active": len(active),
            "jobs": items[-40:], "n_jobs": len(items),
            "n_timeouts_logged": n_timeout,
            "timeouts": {k: task_timeout(k) for k in sorted(TASKS)},
            "default_timeout_s": TASK_TIMEOUT_DEFAULT,
            "log": str(TASK_LOG.relative_to(REPO)).replace("\\", "/")}


def cancel_job(jid: str) -> dict:
    """取消一个正在跑的 job：**真杀进程树**，并留痕。

    若该 job 已在终态，则返回"无可取消"（不伪造取消成功）。
    """
    with ACTIVE_LOCK:
        a = ACTIVE.get(jid)
    if not a:
        with JOBS_LOCK:
            st = (JOBS.get(jid) or {}).get("status")
        return {"cancelled": False, "job_id": jid, "status": st,
                "reason": "该任务不在运行中（没有可终止的进程）"}
    killed = _kill_tree(a["pid"])
    with JOBS_LOCK:
        if jid in JOBS:
            JOBS[jid]["cancel_requested"] = True
    _append_task_log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "job_id": jid,
                      "task": a["task"], "verdict": "cancel_requested",
                      "elapsed_s": round(time.time() - a["started_at"], 1), "kill": killed})
    # 失败通道：取消也是"没做成这件事"，且这里才有**终止证据**（进程树命令 + 回码）
    try:
        mod, err = _inc()
        if mod is not None:
            mod.record("task_cancelled",
                       "任务被人工取消，已终止其进程树 ⇒ **没有结果可用**（不是任务本身失败）。",
                       source="console", task=a["task"], endpoint="/api/job/%s/cancel" % jid,
                       method="POST", params={"job_id": jid, "force_kill": True},
                       error_text="kill=%s" % json.dumps(killed, ensure_ascii=False))
    except Exception:
        pass
    return {"cancelled": True, "job_id": jid, "task": a["task"], "kill": killed,
            "note": "已请求终止并杀掉进程树；任务状态会在下一次轮询变为 cancelled"}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
PAGE = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MEMS 平台控制台</title><style>
:root{--bg:#0e1116;--card:#161b22;--fg:#e6edf3;--dim:#8b949e;--acc:#4aa3ff;--bad:#ff6b6b;--ok:#3fb950;--warn:#d29922}
*{box-sizing:border-box}html,body{height:100%}body{margin:0;background:var(--bg);color:var(--fg);
 font:14px/1.55 "Segoe UI","Microsoft YaHei",system-ui,sans-serif;display:flex;flex-direction:column}
header{padding:10px 16px;border-bottom:1px solid #22282f;display:flex;justify-content:space-between;align-items:center}
h1{margin:0;font-size:16px}
main{flex:1;display:grid;grid-template-columns:290px 1fr;min-height:0}
@media(max-width:860px){main{grid-template-columns:1fr}aside{display:none}}
aside{border-right:1px solid #22282f;overflow:auto;padding:10px}
.grp{color:#586069;font-size:11px;margin:10px 0 4px;text-transform:uppercase;letter-spacing:.5px}
.tb{display:block;width:100%;text-align:left;background:#1b2129;border:1px solid #2a313a;color:var(--fg);
 border-radius:7px;padding:6px 9px;margin:4px 0;cursor:pointer;font-size:12.5px}
.tb:hover{background:#222b36;border-color:#3a4450}
.tb b{display:block;font-weight:600}.tb span{color:#7d8792;font-size:11px}
#chat{display:flex;flex-direction:column;min-height:0}
#log{flex:1;overflow:auto;padding:16px 18px}
.msg{max-width:900px;margin:0 0 12px;padding:9px 12px;border-radius:10px;white-space:pre-wrap;word-break:break-word}
.msg.user{background:#1f6feb22;border:1px solid #1f6feb55;margin-left:auto}
.msg.bot{background:var(--card);border:1px solid #22282f}
.msg.sys{background:#2a1f0a;border:1px solid #9e6a0344;color:#e3b341;font-size:12.5px}
.msg .who{font-size:11px;color:#7d8792;margin-bottom:4px}
.pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;border:1px solid #30363d;color:var(--dim);margin:0 6px 4px 0}
.pill.ok{border-color:#238636;color:var(--ok)}.pill.bad{border-color:#8b2c2c;color:var(--bad)}
.pill.warn{border-color:#9e6a03;color:var(--warn)}
table{border-collapse:collapse;width:100%;font-size:12px;margin:6px 0}
th,td{border-bottom:1px solid #22282f;padding:3px 6px;text-align:left}th{color:var(--dim)}
code{background:#0b0f14;padding:1px 4px;border-radius:4px;font-size:11.5px}
pre{background:#0b0f14;border:1px solid #22282f;border-radius:6px;padding:7px;overflow:auto;max-height:220px;font-size:11.5px}
.src{color:#586069;font-size:10.5px;margin-top:5px}
#composer{border-top:1px solid #22282f;padding:10px 14px;display:flex;gap:8px}
#inp{flex:1;background:#0b0f14;color:var(--fg);border:1px solid #30363d;border-radius:8px;padding:9px 11px;font-size:13.5px;resize:vertical;min-height:44px;max-height:160px}
button{background:#1f6feb;color:#fff;border:0;border-radius:7px;padding:8px 14px;cursor:pointer;font-size:13px}
button.ghost{background:#21262d;border:1px solid #30363d}button:disabled{opacity:.5}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
</style></head><body>
<header><h1>MEMS 平台控制台 <span style="color:#586069;font-size:11.5px">对话式 · 本地 · 不触发 COMSOL</span></h1>
<div class="row"><span id="mode" class="pill">…</span><span id="st" class="pill">…</span>
<button class="ghost" onclick="reset()">清空对话</button></div></header>
<main>
 <aside><div class="grp">功能（点一下即运行）</div><div id="tasks">…</div></aside>
 <section id="chat"><div id="log"></div>
  <div id="composer"><textarea id="inp" placeholder="问我任何事，例如：一阶谐振在多少 MHz？／跑 A5 排名／校验镜像／远端清单（Enter 发送，Shift+Enter 换行）"></textarea>
  <button id="send" onclick="send()">发送</button></div></section>
</main>
<script>
const VC={passed:'ok',ranked:'ok',proposed:'warn',provisional:'warn',inconclusive:'warn',blocked:'warn',failed:'bad',error:'bad',done:'ok',running:'warn'};
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const pill=v=>'<span class="pill '+(VC[v]||'')+'">'+esc(v)+'</span>';
let HIST=[],TASKS={};
function add(cls,html,who){const d=document.createElement('div');d.className='msg '+cls;
  d.innerHTML=(who?'<div class="who">'+esc(who)+'</div>':'')+html;document.getElementById('log').appendChild(d);
  d.scrollIntoView({block:'end'});return d;}
function sys(t){add('sys',esc(t));}
function reset(){document.getElementById('log').innerHTML='';HIST=[];greet();}
function greet(){add('bot','你好，我是这个平台的控制台助手。左边是已登记的功能（点一下就直接跑）；'
 +'也可以直接在下面用中文问，我会**真的去调平台工具**再把结果（含来源哈希）告诉你。<br><br>'
 +'试试：<code>一阶谐振在多少 MHz</code> · <code>跑 A5 排名</code> · <code>校验镜像</code> · <code>远端清单</code>');}
async function boot(){
  const j=await (await fetch('/api/jobs')).json(); TASKS=j.tasks;
  const g={}; Object.entries(TASKS).forEach(([k,v])=>{(g[v.group]=g[v.group]||[]).push([k,v]);});
  document.getElementById('tasks').innerHTML=Object.keys(g).map(grp=>
    '<div class="grp">'+esc(grp)+'</div>'+g[grp].map(([k,v])=>
      '<button class="tb" onclick="runTask(\\''+k+'\\')" title="'+esc(k)+'"><b>'+esc(v.title)+'</b>'
      +'<span>'+(v.writes?'写产物（会确认）':'只读')+'</span></button>').join('')).join('');
  const s=await (await fetch('/api/task/state')).json();
  document.getElementById('st').textContent='服务在线';
  document.getElementById('mode').textContent='对话模式检测中…';
  document.getElementById('mode').className='pill';
  const c=await (await fetch('/api/chat/mode')).json();
  document.getElementById('mode').textContent='模式：'+(c.mode==='llm'?'LLM 对话 + 工具调用':'本地指令（无 key）');
  document.getElementById('mode').className='pill '+(c.mode==='llm'?'ok':'warn');
  greet();
}
function renderRes(r){
  let h='';
  if(r.verdict!==undefined) h+=pill(r.verdict)+' <span class="src" style="border:0">release_allowed='+esc(r.release_allowed)+'</span><br>';
  if(r.stop_reasons&&r.stop_reasons.length) h+='<div class="src" style="border:0">停止条件：'+r.stop_reasons.map(esc).join('；')+'</div>';
  if(r.note) h+='<div class="src" style="border:0">'+esc(r.note)+'</div>';
  if(r.blocking&&r.blocking.length) h+='<table><tr><th>未通过</th><th>passed</th><th>理由</th></tr>'
    +r.blocking.map(b=>'<tr><td>'+esc(b.name)+'</td><td>'+esc(b.passed)+'</td><td>'+esc(b.reason||'')+'</td></tr>').join('')+'</table>';
  if(r.tops&&r.tops.length) h+='<table><tr><th>族</th><th>指标</th><th>口径</th><th>有效/排除</th><th>榜首</th></tr>'
    +r.tops.map(t=>'<tr><td>'+esc(t.family)+'</td><td>'+esc(t.metric)+'</td><td>'+esc(t.caliber)+'</td><td>'
      +t.n_available+'/'+t.n_excluded+'</td><td>'+esc(JSON.stringify(t.top&&t.top.params||{}))+'</td></tr>').join('')+'</table>';
  if(r.recommended&&r.recommended.length) h+='<table><tr><th>#</th><th>族</th><th>N1</th><th>x</th><th>ΔSPL dB</th><th>角色</th></tr>'
    +r.recommended.slice(0,12).map(c=>'<tr><td>'+c.priority+'</td><td>'+esc(c.family)+'</td><td>'+esc(c.n1)+'</td><td>'
      +esc(c.x_mid)+'</td><td>'+esc(c.d_spl20)+'</td><td>'+esc(c.role)+'</td></tr>').join('')+'</table>';
  if(r.hist_MHz) h+='<div class="src" style="border:0">一阶峰直方图 <code>'+esc(JSON.stringify(r.hist_MHz))+'</code> 中位 '+esc(r.median_MHz)+' MHz</div>';
  if(r.report) h+='<div class="src" style="border:0">入库 <code>'+esc(JSON.stringify(r.report))+'</code></div>';
  if(r.parsed) h+='<div class="src" style="border:0">远端 <code>'+esc(JSON.stringify(r.parsed))+'</code></div>';
  if(r.store) h+='<div class="src" style="border:0">'+Object.entries(r.store).map(([k,v])=>'<code>'+esc(k)+'='+esc(v)+'</code>').join(' ')+'</div>';
  if(r.artifacts&&r.artifacts.length) h+='<div class="src">产物：'+r.artifacts.map(a=>'<code>'+esc(a.path.split('\\\\').pop())+'</code> '+esc((a.sha256||'').slice(0,10))).join('　')+'</div>';
  if(r.script) h+='<div class="src">脚本 <code>'+esc(r.script.path)+'</code> '+esc((r.script.sha256||'').slice(0,10))+'</div>';
  return h||'<span class="src" style="border:0">（无摘要）</span>';
}
async function runTask(k){
  const spec=TASKS[k];
  if(spec.writes && !confirm('「'+spec.title+'」会写产物，确定运行？')) return;
  const card=add('bot','<div class="who">侧边栏 · '+esc(spec.title)+'</div>'+pill('running'));
  const j=await (await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({task:k,args:{confirm:true}})})).json();
  if(j.error){card.innerHTML='<div class="who">'+esc(spec.title)+'</div>'+pill('error')+' '+esc(j.error);return;}
  for(let i=0;i<900;i++){
    const s=await (await fetch('/api/job/'+j.job_id)).json();
    if(s.status!=='running'){
      card.innerHTML='<div class="who">侧边栏 · '+esc(spec.title)+'（'+esc(s.status)+'，'+(s.duration_s||'')+'s）</div>'
        +(s.error?('<span class="pill bad">error</span> '+esc(s.error)):renderRes(s.result||{}))
        +(s.stdout?('<pre>'+esc(s.stdout)+'</pre>'):'')
        +'<div class="src">原始 <code>/api/job/'+esc(s.id)+'</code></div>';
      card.scrollIntoView({block:'end'});return;
    }
    await new Promise(r=>setTimeout(r,500));
  }
}
async function send(){
  const box=document.getElementById('inp'); const text=box.value.trim(); if(!text) return;
  box.value=''; add('user',esc(text),'你'); HIST.push({role:'user',content:text});
  const card=add('bot','<div class="who">助手</div>思考中…');
  let j;
  try{ j=await (await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({message:text,history:HIST.slice(0,-1)})})).json(); }
  catch(e){ card.innerHTML='<span class="pill bad">error</span> '+esc(String(e)); return; }
  if(j.error){ card.innerHTML='<span class="pill bad">error</span> '+esc(j.error); return; }
  let h='<div class="who">助手'+(j.mode==='llm'?(' · '+esc((j.llm||{}).model||'LLM')):' · 本地指令模式')+'</div>'
      +esc(j.reply||'').replace(/\\n/g,'<br>');
  (j.tool_trace||[]).forEach(t=>{
    h+='<div style="margin-top:8px;border-top:1px dashed #22282f;padding-top:6px">'
      +'<div class="row">'+pill('done')+'<b>'+esc(t.title||t.task)+'</b><span class="src" style="border:0">'+(t.duration_s||'')+'s</span></div>'
      +(t.error?('<span class="pill bad">error</span> '+esc(t.error)):renderRes(t.result||{}))+'</div>';});
  (j.pending||[]).forEach(p=>{
    h+='<div style="margin-top:8px;border:1px solid #9e6a03;border-radius:8px;padding:8px">'
      +pill('warn')+'<b>'+esc(p.title)+'</b> 需要你确认才会执行（写产物）'
      +'<div class="src" style="border:0">参数 <code>'+esc(JSON.stringify(p.args))+'</code></div>'
      +'<button style="margin-top:6px" onclick="runTask(\\''+esc(p.task)+'\\')">允许执行</button></div>';});
  card.innerHTML=h; card.scrollIntoView({block:'end'});
  HIST.push({role:'assistant',content:(j.reply||'')});
}
document.getElementById('inp').addEventListener('keydown',e=>{
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}});
boot();
</script></body></html>
"""

# ---------------------------------------------------------------------------
# 新单页 UI（2026-09-29）：`scripts/webapp_page.html`
# 内容 = 顶部**显式双模式开关**（离线 / DeepSeek）+ 侧栏分区 + 代理全部功能 + 数据浏览 + 内联 SVG 出图。
# 旧的内嵌页面保留为 `_LEGACY_PAGE` **仅作历史参考**，运行时不再使用（可安全删除）。
# ---------------------------------------------------------------------------
_LEGACY_PAGE = PAGE
PAGE_FILE = Path(__file__).resolve().parent / "webapp_page.html"
#: 页面必备声明（fail-closed：缺任一条即拒绝启动，防止"代理"被悄悄说成"求解器"）
PAGE_MUST_HAVE = ("响应级代理", "不是 AI 求解器", "拒答", "model_id", "离线")


def _load_page() -> str:
    if not PAGE_FILE.is_file():
        raise SystemExit("[FAIL] 缺少页面文件：%s" % PAGE_FILE)
    text = PAGE_FILE.read_text(encoding="utf-8")
    missing = [m for m in PAGE_MUST_HAVE if m not in text]
    if missing:
        raise SystemExit("[FAIL] 页面缺少必备声明：%s" % missing)
    return text


PAGE = _load_page()

# ---------------------------------------------------------------------------
# 工作模式：**默认离线**（绝不默认联网）；切换 DeepSeek 需服务端确有凭据
# ---------------------------------------------------------------------------
STATE: dict[str, Any] = {"mode": "offline"}
VALID_MODES = ("offline", "deepseek")
#: 访问令牌（仅非回环绑定时启用；默认空 = 不鉴权）
TOKEN: dict[str, Any] = {"value": None}


def mode_payload() -> dict:
    key, src = load_api_key()
    return {"mode": STATE["mode"], "key_present": bool(key), "key_source": src,
            "valid_modes": list(VALID_MODES),
            "network_allowed": STATE["mode"] == "deepseek",
            "note": ("离线：不发任何网络请求；对话降级为本地关键词路由"
                     if STATE["mode"] == "offline" else
                     "DeepSeek：对话由 LLM 驱动；密钥只在服务端，LLM 不参与裁决")}


def set_mode(m: str) -> dict:
    if m not in VALID_MODES:
        return {"error": "未知模式 %r（可选 %s）" % (m, list(VALID_MODES))}
    if m == "deepseek":
        key, src = load_api_key()
        if not key:
            return {"error": "服务端未检测到 API key（环境变量 DEEPSEEK_API_KEY 或 "
                             "~/.dsh/.credentials.yaml）⇒ 拒绝切到 DeepSeek 模式"}
    STATE["mode"] = m
    return mode_payload()


# ---------------------------------------------------------------------------
# 响应级代理（**不是 AI 求解器**）：懒加载 + 单例
# ---------------------------------------------------------------------------
SURR_DIR = REPO / "work/runs/surrogate-response-20260929"
_SURR: dict[str, Any] = {"obj": None, "err": None}
#: 一阶峰数据层（Pareto / 热力图）懒加载
_FP: dict[str, Any] = {"mod": None, "err": None}


def surrogate():
    """懒加载 `memsharness.surrogate.ResponseSurrogate`；失败时**记住错误**而不是反复重试。"""
    if _SURR["obj"] is not None or _SURR["err"] is not None:
        return _SURR["obj"], _SURR["err"]
    try:
        sys.path.insert(0, str(REPO / "src"))
        from memsharness.surrogate import ResponseSurrogate
        _SURR["obj"] = ResponseSurrogate.load(SURR_DIR)
    except Exception as exc:
        _SURR["err"] = "%s: %s" % (type(exc).__name__, exc)
    return _SURR["obj"], _SURR["err"]


def _surrogate_card() -> dict:
    s, err = surrogate()
    if s is None:
        return {"error": "代理不可用：%s" % err, "not_a_solver": "拒答（不升级为求解器）"}
    card = s.model_card()
    rows = []
    for mode in ("in_layer", "n2_extrap"):
        for k, v in ((s.conformal or {}).get(mode) or {}).items():
            rows.append({"mode": mode, "alpha": k.replace("alpha=", ""),
                         "target": v["target"], "q_worst_db": v["q_median_db_dims_worst"],
                         "q_p20_Pa": v["q_median_p20_Pa"], "q_sim_db": v["q_simultaneous_max_over_db_dims"],
                         "coverage_sim": v["coverage_simultaneous"],
                         "n_cal": v["n_calibration_per_split"]})
    card["conformal_table"] = rows
    card["data_version_sha256"] = _version_sha(card.get("data_version"))
    return card


def _version_sha(label: str | None) -> str | None:
    if not label:
        return None
    p = REPO / "work/runs/x-densify-20260928/data_versions" / ("%s.json" % label)
    return sha256_file(p) if p.is_file() else None


def _capture_if_refused(where: str, endpoint: str, params: dict, res: object) -> object:
    """响应代理的拒答是**返回值里的 `refused: true`**（不是抛异常）⇒ 在出口兜一层。

    （多通道代理是抛 `Refused`，两条路都要收 —— 用户的「代理拒答」不区分是哪个代理。）
    """
    if isinstance(res, dict) and res.get("refused"):
        _capture_refusal(where, res.get("reason") or "（未给原因）",
                         params=params, endpoint=endpoint)
    return res


def _predict(payload: dict) -> dict:
    s, err = surrogate()
    if s is None:
        return {"error": "代理不可用：%s" % err}
    try:
        res = s.predict(float(payload["x"]), float(payload["N1"]), float(payload["N2"]),
                        alpha=float(payload.get("alpha", 0.10)))
        return _capture_if_refused(
            "响应代理预测 /api/surrogate/predict", "/api/surrogate/predict",
            {"x": payload.get("x"), "N1": payload.get("N1"), "N2": payload.get("N2"),
             "alpha": payload.get("alpha")}, res)
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def _coverage(payload: dict) -> dict:
    s, err = surrogate()
    if s is None:
        return {"error": "代理不可用：%s" % err}
    n1s = payload.get("n1_choices") or (1, 2, 3, 4, 5, 6, 7, 8)
    return s.coverage(n1_choices=tuple(float(v) for v in n1s))


def _compare(payload: dict) -> dict:
    s, err = surrogate()
    if s is None:
        return {"error": "代理不可用：%s" % err}
    try:
        res = s.compare({"x": float(payload["a"]["x"]), "N1": float(payload["a"]["N1"]),
                         "N2": float(payload["a"]["N2"])},
                        {"x": float(payload["b"]["x"]), "N1": float(payload["b"]["N1"]),
                         "N2": float(payload["b"]["N2"])},
                        alpha=float(payload.get("alpha", 0.10)))
        return _capture_if_refused("响应代理两点对比 /api/surrogate/compare",
                                   "/api/surrogate/compare",
                                   {"a": payload.get("a"), "b": payload.get("b"),
                                    "alpha": payload.get("alpha")}, res)
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def _screen(payload: dict) -> dict:
    s, err = surrogate()
    if s is None:
        return {"error": "代理不可用：%s" % err}
    try:
        res = s.screen(n2=float(payload["n2"]),
                       n1_choices=tuple(float(v) for v in payload.get("n1_choices") or (1,)),
                       alpha=float(payload.get("alpha", 0.10)))
        return _capture_if_refused("响应代理筛查 /api/surrogate/screen",
                                   "/api/surrogate/screen",
                                   {"n2": payload.get("n2"),
                                    "n1_choices": payload.get("n1_choices"),
                                    "alpha": payload.get("alpha")}, res)
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def _fp():
    """懒加载一阶峰数据层（`memsharness.first_peak`）。"""
    if _FP["mod"] is not None or _FP["err"] is not None:
        return _FP["mod"], _FP["err"]
    try:
        sys.path.insert(0, str(REPO / "src"))
        from memsharness import first_peak as fp
        _FP["mod"] = fp
    except Exception as exc:
        _FP["err"] = "%s: %s" % (type(exc).__name__, exc)
    return _FP["mod"], _FP["err"]


def _peaks_summary() -> dict:
    fp, err = _fp()
    if fp is None:
        return {"error": "一阶峰数据层不可用：%s" % err}
    try:
        return fp.summary()
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def _peaks_filter(q: dict, allow: tuple = ()) -> tuple[dict, str | None]:
    """解析筛选参数（`fp.parse_filter`）。未知参数一律报错，**绝不静默忽略**。

    ⚠️ 这里的坑（2026-09-29 实测踩到）：不能"先把非筛选键滤掉、再交给 parse_filter"——
    那样 `?n1=3` 这种拼错的筛选名会被**提前丢掉**，于是 parse_filter 永远看不到它、
    永远不报错，缺陷照样存在（第一版正是如此，`n1=3` 返回 None 而非报错）。
    正确做法：把该端点**允许的非筛选参数**（batch/metric/objectives）显式传进来，
    其余任何键都算未知 ⇒ 报错。
    """
    fp, err = _fp()
    if fp is None:
        return {}, "一阶峰数据层不可用：%s" % err
    good = set(fp.FILTER_KEYS) | set(allow)
    unknown = sorted(set(q) - good)
    if unknown:
        return {}, ("不支持参数 %s；筛选参数：%s；本端点允许：%s"
                    % (unknown, list(fp.FILTER_KEYS), list(allow)))
    sub = {k: v for k, v in q.items() if k in fp.FILTER_KEYS}
    return fp.parse_filter(sub)


def _peaks_pareto(q: dict) -> dict:
    fp, err = _fp()
    if fp is None:
        return {"error": "一阶峰数据层不可用：%s" % err}
    try:
        objs = q.get("objectives") or None
        if isinstance(objs, str):
            objs = [x for x in objs.split(",") if x]
        flt, ferr = _peaks_filter(q, allow=("batch", "objectives"))
        if ferr:
            return {"error": ferr}
        return fp.pareto(str(q.get("batch") or "C"), objectives=objs, flt=flt)
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def _peaks_heatmap(q: dict) -> dict:
    fp, err = _fp()
    if fp is None:
        return {"error": "一阶峰数据层不可用：%s" % err}
    try:
        flt, ferr = _peaks_filter(q, allow=("batch", "metric"))
        if ferr:
            return {"error": ferr}
        n2 = flt.pop("n2", None)
        return fp.heatmap(str(q.get("batch") or "C"), str(q.get("metric") or "bandwidth_Hz"),
                          n2=n2, flt=flt)
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def _grid(payload: dict) -> dict:
    s, err = surrogate()
    if s is None:
        return {"error": "代理不可用：%s" % err}
    try:
        n2s = payload.get("n2_list") or list(s.n2_fitted) + [s.n2_extrap_max]
        return s.grid(n2_list=[float(v) for v in n2s],
                      n1_max=int(payload.get("n1_max") or 7),
                      x_lo=(None if payload.get("x_lo") in (None, "") else float(payload["x_lo"])),
                      x_hi=(None if payload.get("x_hi") in (None, "") else float(payload["x_hi"])),
                      x_step=float(payload.get("x_step") or 0.01),
                      alpha=float(payload.get("alpha", 0.10)))
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def _sentinel(payload: dict) -> dict:
    s, err = surrogate()
    if s is None:
        return {"error": "代理不可用：%s" % err}
    try:
        return s.sentinel(float(payload["x"]), float(payload["N1"]), float(payload["N2"]),
                          spl20=(None if payload.get("spl20") is None
                                 else float(payload["spl20"])),
                          spectrum_dB=payload.get("spectrum_dB"),
                          alpha=float(payload.get("alpha", 0.10)))
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


# ---------------------------------------------------------------------------
# 数据浏览（只读）
# ---------------------------------------------------------------------------
def _data_versions() -> dict:
    d = REPO / "work/runs/x-densify-20260928/data_versions"
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if j.get("kind") != "immutable_data_version":
            continue
        fg = j.get("freq_grid") or {}
        out.append({"label": j.get("label"), "sha256": sha256_file(p),
                    "n_runs": j.get("n_runs"), "n_combos": (j.get("combos") or {}).get("n"),
                    "grid": "%s 点 / %.0f–%.0f MHz" % (fg.get("n_points"),
                                                       (fg.get("scan_fmin_Hz") or 0) / 1e6,
                                                       (fg.get("scan_fmax_Hz") or 0) / 1e6),
                    "n_models": len(j.get("models") or []), "prereg": j.get("prereg"),
                    "frozen_utc": j.get("frozen_utc")})
    out.sort(key=lambda x: str(x["label"]))
    return {"versions": out,
            "semantics": "不可变版本：旧结论对旧快照继续成立、**不称作废**；"
                         "引用某版本时必须同时读隔离表修订 ledger"}


def _data_quarantine() -> dict:
    led = REPO / "work/runs/x-densify-20260928/data_versions/QUARANTINE_AMENDMENTS.jsonl"
    recs = []
    if led.is_file():
        for ln in led.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                recs.append(json.loads(ln))
    corner = {}
    cj = REPO / "work/runs/x-densify-20260928/a6/corner_anomaly.json"
    if cj.is_file():
        j = json.loads(cj.read_text(encoding="utf-8"))
        dip = j.get("dip_profile") or {}
        rows = []
        for n2key, byf in sorted(dip.items()):
            r = byf.get("5.0MHz")
            if r:
                rows.append({"N2": n2key, "line": r.get("neighbour_line_at_0.20_dB"),
                             "a": r.get("A_measured_dB"), "new": r.get("new_measured_dB"),
                             "dip_a": r.get("dip_A_dB"), "dip_new": r.get("dip_new_dB"),
                             "diff": r.get("batches_agree_dB")})
        att = j.get("attribution") or {}
        corner = {"dip_rows": rows, "reading": att.get("reading"),
                  "note": ("这是「证据指向批 A」，**不是**已证明 A 错；定论需 mesh_fingerprint 与解索引。"
                           "（见 a6/CORNER_ANOMALY.md 与 ROUND5_ANOMALY_ATTRIBUTION_RETRACTION.md）")}
    return {"records": recs, "corner": corner,
            "semantics": "append-only：被绑定的版本 manifest 一字未动；隔离只增不删"}


def _data_dataset() -> dict:
    s, err = surrogate()
    if s is None:
        return {"error": "代理不可用：%s" % err}
    layers = []
    for (n2, n1), rec in sorted(s._layers.items()):
        layers.append({"N2": n2, "N1": n1, "n_x": int(rec["x"].size),
                       "x_min": float(rec["x"].min()), "x_max": float(rec["x"].max())})
    by_n2: dict[float, list] = {}
    for l in layers:
        by_n2.setdefault(l["N2"], []).append(l["N1"])
    return {"n_combos": sum(l["n_x"] for l in layers), "n_layers": len(layers),
            "layers": [{"N2": n2, "N1": sorted(v), "n_x": int(s._layers[(n2, v[0])]["x"].size)}
                       for n2, v in sorted(by_n2.items())],
            "x_predictable": [s.x_lo, s.x_hi], "model_id": s.model_id,
            "data_version": s.data_version}


def _surrogate_coverage_task(args: dict) -> dict:
    return _coverage({})


def _surrogate_card_task(args: dict) -> dict:
    c = _surrogate_card()
    if "error" in c:
        return c
    return {"model_id": c["model_id"], "status": c["status"], "data_version": c["data_version"],
            "n2_fitted": c["n2_fitted"], "n2_extrap_allowed_max": c["n2_extrap_allowed_max"],
            "x_predictable": c["x_predictable"], "n_layers": c["n_layers"],
            "quarantined": c["quarantined"], "not_a_solver": c["not_a_solver"],
            "red_lines": c["red_lines"], "conformal_table": c.get("conformal_table")}


def task_mc_export(args: dict) -> dict:
    """用**全部** C 数据重拟合并导出可服务的多通道模型（写产物）。"""
    mod = _load("_mc_export", "work/runs/multichannel-surrogate-20260929/"
                              "export_multichannel_model.py")
    rc = mod.main()
    mc = _mc_card()
    return {"rc": rc,
            "model_id": mc.get("model_id"), "n_channels": len(mc.get("channels") or []),
            "path": "work/runs/multichannel-surrogate-20260929/multichannel_model.json",
            "note": ("部署模型用**全部数据**重拟合；评估数字来自**折**（见预注册）。"
                     "两者不可混用——混用就是数据泄漏。")}


def task_mc_card(args: dict) -> dict:
    """多通道模型卡（只读）。"""
    return _mc_card()


def _register_surrogate_tasks() -> None:
    """把上面几个函数挂到任务注册表（`TASKS` 在文件前部定义，函数在文件后部 ⇒ 此处补挂）。"""
    TASKS["surrogate_card"]["fn"] = _surrogate_card_task
    TASKS["surrogate_coverage"]["fn"] = _surrogate_coverage_task
    TASKS["mc_export"]["fn"] = task_mc_export
    TASKS["mc_card"]["fn"] = task_mc_card


_register_surrogate_tasks()


class Handler(BaseHTTPRequestHandler):
    server_version = "mems-console/1"

    def log_message(self, fmt, *args):    # 静音默认日志（避免刷屏）
        return

    #: 允许的 CORS 来源：**只允许本机回环**（页面可能被别的本地端口/界面内嵌打开，
    #: 那时相对路径会打到错的服务器；允许回环来源即可让页面用绝对 URL 回落到 8877）。
    #: ⚠️ 不写 `*`：本服务能在本机执行**写产物**任务，不能让任意网页跨源调用。
    _LOOPBACK_ORIGIN = re.compile(r"^http://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$")

    def _cors(self):
        origin = self.headers.get("Origin") or ""
        if origin and self._LOOPBACK_ORIGIN.match(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send(self, obj: Any, code: int = 200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")     # 见 _html 的说明
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text: str):
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # ⚠️ **必须 no-store**：本响应没有 Last-Modified/ETag，浏览器会**启发式缓存** HTML。
        # 实测教训：改了前端后用户刷新仍拿到旧页，表现为"点按钮没反应"（旧页根本没有那个按钮）。
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        """CORS 预检：只对回环来源放行，其余不回 CORS 头（浏览器会自行拒绝）。"""
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self._cors()
        self.end_headers()

    def _token_ok(self) -> bool:
        """令牌校验：未设 `--token` 时放行（本机模式）；设了就**所有**端点都要带令牌。"""
        t = TOKEN["value"]
        if not t:
            return True
        got = self.headers.get("Authorization") or ""
        if got.startswith("Bearer ") and got[7:].strip() == t:
            return True
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        return (q.get("token") or [""])[0] == t

    def _no_incident(self) -> bool:
        """本请求是否声明「不登记失败通道」（见 `_inc_suppressed`）。"""
        if (self.headers.get("X-MEMS-No-Incident") or "").strip() in ("1", "true", "yes"):
            return True
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        return (q.get("no_incident") or [""])[0].strip() in ("1", "true", "yes")

    def do_GET(self):
        _REQ.no_incident = self._no_incident()
        # 未处理异常 ⇒ 登记进失败通道（否则前端只看到连接被断，什么也拿不到）
        try:
            return self._do_GET()
        except Exception as exc:
            return self._fail_soft(exc, "GET")

    def _fail_soft(self, exc: BaseException, method: str):
        path = urllib.parse.urlparse(self.path).path
        tb = traceback.format_exc()
        _record_api_error(exc, method, path, tb)
        try:
            return self._send({"error": "服务端未处理异常（已登记到「失败通道」）",
                               "detail": "%s: %s" % (type(exc).__name__, exc),
                               "path": path,
                               "hint": "到「失败通道」分区一键生成分析包，发给 Codex / 助手"}, 500)
        except Exception:
            return None       # 连回应都发不出去（对端已断开）⇒ 不再抛，台账已留痕

    def _do_GET(self):
        if not self._token_ok():
            return self._send({"error": "需要令牌（Authorization: Bearer … 或 ?token=…）"}, 401)
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._html(PAGE)
        if path == "/api/mode":
            return self._send(mode_payload())
        if path == "/api/surrogate/model":
            return self._send(_surrogate_card())
        if path == "/api/surrogate/coverage":
            return self._send(_coverage({}))
        if path == "/api/peaks/summary":
            return self._send(_peaks_summary())
        if path == "/api/peaks/pareto":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._send(_peaks_pareto({k: v[0] for k, v in qs.items()}))
        if path == "/api/peaks/heatmap":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._send(_peaks_heatmap({k: v[0] for k, v in qs.items()}))
        if path == "/api/tasks/active":
            return self._send(jobs_snapshot())
        if path == "/api/mc/model":
            return self._send(_mc_card())
        if path == "/api/mc/predict":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._send(_mc_predict({k: v[0] for k, v in qs.items()}))
        if path == "/api/mc/screen":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._send(_mc_screen({k: v[0] for k, v in qs.items()}))
        if path == "/api/agents/list":
            return self._send(_agents_list())
        if path == "/api/glossary":
            return self._send(_glossary())
        if path == "/api/incidents":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._send(_inc_list({k: v[0] for k, v in qs.items()}))
        if path == "/api/incidents/one":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            r = _inc_one({k: v[0] for k, v in qs.items()})
            return self._send(r, 404 if "error" in r else 200)
        if path == "/api/incidents/dsh_reports":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._send(_dsh_reports({k: v[0] for k, v in qs.items()}))
        if path == "/api/agents/ledger":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._send(_agents_ledger({k: v[0] for k, v in qs.items()}))
        if path == "/api/data/versions":
            return self._send(_data_versions())
        if path == "/api/data/quarantine":
            return self._send(_data_quarantine())
        if path == "/api/data/dataset":
            return self._send(_data_dataset())
        if path == "/api/jobs":
            # 带上**每个任务的超时额度**（用户要求"任务超时可见性"：先说清能跑多久）
            return self._send({"tasks": {k: {**{kk: vv for kk, vv in v.items() if kk != "fn"},
                                            "timeout_s": task_timeout(k)}
                                         for k, v in TASKS.items()},
                               "default_timeout_s": TASK_TIMEOUT_DEFAULT})
        if path == "/api/jobs/run":
            return self._send({"error": "该端点为 POST"})
        if path == "/api/task/state":
            # 轻量健康探针：**不跑** state 任务（避免每次开页都扫库）
            key, src = load_api_key()
            return self._send({"ok": True, "n_tasks": len(TASKS),
                               "n_writes": sum(1 for v in TASKS.values() if v.get("writes")),
                               "chat_mode": "llm" if key else "local",
                               "key_source": src})
        if path == "/api/chat/mode":
            # 兼容别名（新页面用 `/api/mode`）：**必须反映真实 STATE**，
            # 不能只看"有没有 key"——那会在离线模式下谎称 llm。
            p = mode_payload()
            return self._send({"mode": "llm" if p["mode"] == "deepseek" else "local",
                               "state_mode": p["mode"], "key_present": p["key_present"],
                               "key_source": p["key_source"]})
        if path.startswith("/api/task/"):
            return self._send(submit(path[len("/api/task/"):], {"confirm": True}))
        if path.startswith("/api/job/") and path.endswith("/cancel"):
            # ⚠️ 必须排在下面的通用 `/api/job/` 之前：否则 jid 会被解析成 "xxx/cancel"
            return self._send(cancel_job(path[len("/api/job/"):-len("/cancel")]))
        if path.startswith("/api/job/"):
            jid = path[len("/api/job/"):]
            with JOBS_LOCK:
                job = JOBS.get(jid)
            return self._send(job or {"error": "无此 job：%s" % jid}, 200 if job else 404)
        if path == "/api/state":
            return self._send(submit("state", {"confirm": True}))
        return self._send({"error": "未知路径", "path": path}, 404)

    def do_POST(self):
        _REQ.no_incident = self._no_incident()
        # 未处理异常 ⇒ 登记进失败通道；注意**先把请求体排空**再回应，
        # 否则套接字里残留未读 body，客户端会收到 RST（WinError 10053，实测踩过）
        try:
            return self._do_POST()
        except Exception as exc:
            self._drain_body()
            return self._fail_soft(exc, "POST")

    def _drain_body(self) -> None:
        if getattr(self, "_body_drained", False):
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        try:
            if n > 0:
                self.rfile.read(min(n, MAX_BODY))
        except Exception:
            pass
        self._body_drained = True

    def _do_POST(self):
        if not self._token_ok():
            return self._send({"error": "需要令牌（Authorization: Bearer … 或 ?token=…）"}, 401)
        path = urllib.parse.urlparse(self.path).path
        POST_ROUTES = {"/api/run", "/api/chat", "/api/mode", "/api/surrogate/predict",
                       "/api/surrogate/compare", "/api/surrogate/screen",
                       "/api/surrogate/grid",
                       "/api/surrogate/sentinel", "/api/surrogate/coverage",
                       "/api/agents/payload",
                       "/api/incidents/record", "/api/incidents/package",
                       "/api/incidents/report_to_dsh"}
        # ⚠️ **先把请求体读完再判路由**：若直接回 404 就关连接，套接字里还有未读的请求体，
        # 客户端会收到 RST（实测 `WinError 10053 你的主机中的软件中止了一个已建立的连接`），
        # 表现为"偶发失败的测试/偶发的前端报错"。先排空（上限 MAX_BODY）再回应。
        unknown = path not in POST_ROUTES
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n > MAX_BODY:
            return self._send({"error": "body 过大"}, 413)
        raw = self.rfile.read(n) if n > 0 else b""
        self._body_drained = True       # 已排空：`_fail_soft` 不会再读一次
        if unknown:
            return self._send({"error": "未知路径", "path": path}, 404)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception as exc:
            return self._send({"error": "请求体不是 JSON：%s" % exc}, 400)
        if path == "/api/incidents/record":
            r = _inc_record(payload)
            return self._send(r, 400 if "error" in r else 200)
        if path == "/api/incidents/package":
            r = _inc_package(payload)
            return self._send(r, 400 if "error" in r else 200)
        if path == "/api/incidents/report_to_dsh":
            r = _dsh_start(payload)
            return self._send(r, 400 if "error" in r else 200)
        if path == "/api/chat":
            res = do_chat(payload)
            return self._send(res, 400 if "error" in res else 200)
        if path == "/api/mode":
            r = set_mode(str(payload.get("mode") or ""))
            return self._send(r, 400 if "error" in r else 200)
        if path == "/api/surrogate/predict":
            r = _predict(payload)
            return self._send(r, 400 if "error" in r else 200)
        if path == "/api/surrogate/compare":
            r = _compare(payload)
            return self._send(r, 400 if "error" in r else 200)
        if path == "/api/surrogate/screen":
            r = _screen(payload)
            return self._send(r, 400 if "error" in r else 200)
        if path == "/api/surrogate/grid":
            r = _grid(payload)
            return self._send(r, 400 if "error" in r else 200)
        if path == "/api/surrogate/sentinel":
            r = _sentinel(payload)
            return self._send(r, 400 if "error" in r else 200)
        if path == "/api/surrogate/coverage":
            return self._send(_coverage(payload))
        if path == "/api/agents/payload":
            r = _agents_payload(payload)
            return self._send(r, 400 if "error" in r else 200)
        res = submit(str(payload.get("task") or ""), dict(payload.get("args") or {}))
        return self._send(res, 400 if "error" in res else 200)


def selftest() -> int:
    """自检入口：**先把失败通道整体重定向到临时目录**，再跑正文。

    ⚠️ 为什么必须整体重定向（2026-09-30 实测）：自检会**故意**制造失败面 ——
    域外预测（拒答）、取消不存在的 job、坏路径……这些都会被失败通道**自动**登记。
    只重定向最后那一段不够：一次自检就把一条 `refusal` 写进了生产台账
    `work/logs/incidents.jsonl`，那份台账会因此把"演示"当成"真事故"。
    `try/finally` 保证无论正文怎么退出都恢复现场。
    """
    keys = ("MEMS_INCIDENTS_LEDGER", "MEMS_INCIDENTS_ROOT", "MEMS_DSH_REPORT_LOG")
    old = {k: os.environ.get(k) for k in keys}
    tmpd = tempfile.mkdtemp(prefix="memsselftest-")
    os.environ["MEMS_INCIDENTS_LEDGER"] = str(Path(tmpd) / "inc.jsonl")
    os.environ["MEMS_INCIDENTS_ROOT"] = str(Path(tmpd) / "packages")
    # 上报台账**也要**重定向：它的终态回填发生在后台线程里，写错地方很难被发现
    os.environ["MEMS_DSH_REPORT_LOG"] = str(Path(tmpd) / "dsh_reports.jsonl")
    try:
        return _selftest_body()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _selftest_body() -> int:
    """自检正文：**同步**跑（不开线程、不重定向 stdout，避免把自检输出吞进任务缓冲）。"""
    out: list[tuple[str, bool]] = []
    # ① 白名单：未登记任务必须被拒
    r = submit("rm -rf /", {})
    out.append(("未登记任务被拒（无任意命令执行）", "error" in r and "allowed" in r))
    # ② 写任务必须带 confirm
    r = submit("sweep_analysis", {})
    out.append(("写产物任务需 confirm=true", "error" in r and r.get("writes") is True))
    # ③ 只读任务同步可跑（直接调函数，不经线程）
    v = task_freeze_gate({})
    out.append(("A8 冻结门禁（只读）返回裁决", v.get("verdict") in ("passed", "failed",
                                                              "inconclusive")
                and "release_allowed" in v))
    # ④ 路径守卫：输出必须在 work/ 下
    try:
        _check_path("C:/Windows/system32", under_work=True)
        out.append(("路径守卫拦下越界输出", False))
    except ValueError:
        out.append(("路径守卫拦下越界输出", True))
    # ⑤ 未知任务不进线程、不产生 job
    before = len(JOBS)
    submit("nope", {"confirm": True})
    out.append(("未知任务不产生 job", len(JOBS) == before))
    # ⑥ 默认离线：绝不能默认联网
    STATE["mode"] = "offline"
    out.append(("模式默认离线（不默认联网）", mode_payload()["network_allowed"] is False))
    # ⑦ 无 key 时拒绝切到 DeepSeek（不能"切了但其实没网/没凭据"）
    ok_no_key = True
    try:
        key, _ = load_api_key()
        if not key:
            ok_no_key = "error" in set_mode("deepseek")
    except Exception:
        ok_no_key = False
    out.append(("无凭据时拒绝切 DeepSeek", ok_no_key))
    # ⑧ 代理可加载且**拒答域内不给数字**
    s, err = surrogate()
    if s is None:
        out.append(("响应级代理可加载", False))
    else:
        r = s.predict(0.20, 1, 8)
        out.append(("代理可加载", True))
        out.append(("拒答时不含任何数字",
                    bool(r.get("refused")) and "spl_dB" not in r and "spl20_dB" not in r))
        p = s.predict(0.55, 1, 6)
        out.append(("正常预测带 model_id + certified + 区间",
                    bool(p.get("accepted")) and p.get("model_id") and "certified" in p
                    and p.get("band_simultaneous_dB") is not None))
    # ⑨ 绑定守卫：非回环无令牌必须被拒
    out.append(("非回环绑定无令牌被拒", check_bind("0.0.0.0", None) is not None))
    out.append(("回环绑定无需令牌", check_bind("127.0.0.1", None) is None))
    out.append(("短令牌被拒", check_bind("0.0.0.0", "short") is not None))
    # ⑩ 页面必备声明齐全（fail-closed 的措辞锁）
    out.append(("页面含必备声明", all(m in PAGE for m in PAGE_MUST_HAVE)))
    # ⑪ 多通道代理：可加载、拒答不给数字、正常预测带 model_id 与区间
    mc = _mc_card()
    if "error" in mc:
        out.append(("多通道代理可加载", False))
    else:
        out.append(("多通道代理可加载", bool(mc.get("model_id"))))
        out.append(("多通道模型卡声明「不是求解器」", "不是 AI 求解器" in (mc.get("not_a_solver") or "")))
        out.append(("多通道模型卡不认约束量为目标",
                    bool(mc.get("constraint_only_not_predictable"))))
        rr = _mc_predict({"x": "1.5", "n1": "1", "n2": "8"})
        out.append(("多通道拒答时不含任何数字",
                    bool(rr.get("refused")) and "channels" not in rr))
        rp = _mc_predict({"x": "0.55", "n1": "1", "n2": "8"})
        out.append(("多通道正常预测带 model_id 与区间",
                    bool(rp.get("model_id")) and all(
                        v.get("interval") for v in (rp.get("channels") or {}).values())))
    # ⑫ 子智能体：离线只能生成载荷，**绝不能**涉 LLM
    al = _agents_list()
    out.append(("子智能体角色列表可读（9 个）", al.get("n_roles") == 9))
    out.append(("界面明确「离线不 spawn」", "不" in (al.get("offline_capability") or "")))
    # ⑬ 任务超时可见性：注册表必须有 timeout，且快照能给出额度
    snap = jobs_snapshot()
    out.append(("任务超时额度可见", bool(snap.get("timeouts")) and snap.get("default_timeout_s") > 0))
    out.append(("每个登记任务都有超时额度",
                set(snap["timeouts"]) == set(TASKS)))
    # ⑭ 取消不存在的 job 不得伪造成功
    cx = cancel_job("no-such-job")
    out.append(("取消不存在的 job 不伪造成功", cx.get("cancelled") is False))
    # ⑮ 失败通道（**绝不写生产台账**：只做不落盘的检查 + 显式重定向）
    #    自检会调用 record 的**拒收**路径（不写台账）与 render/redact（纯函数）。
    inc, inc_err = _inc()
    if inc is None:
        out.append(("失败通道可加载", False))
    else:
        out.append(("失败通道可加载", True))
        # 未登记类别必须拒收（否则前端能往台账里灌没人认识的 kind）
        try:
            inc.record("nonsense_kind", "x", source="selftest")
            out.append(("未登记的失败类别被拒收", False))
        except ValueError:
            out.append(("未登记的失败类别被拒收", True))
        # 包必须自带「不含分析结论 + 不得改变裁定」的声明（红线 5）
        demo = {"incident_id": "inc-selftest", "kind": "task_timeout", "kind_zh": "任务超时",
                "ts": "2026-01-01T00:00:00", "source": "selftest", "symptom": "演示",
                "error_text": "boom", "stack": "", "params": {"token": "SHOULD-NOT-APPEAR"},
                "args": {}, "repro": "python -c print(1)", "redacted_hits": 1, "truncated": {}}
        md = inc.render_md(demo)
        out.append(("分析包声明「不含分析结论／不改裁定」",
                    "不得" in md and "不含任何分析结论" in md))
        out.append(("分析包含现象与原始错误全文", "## 1. 现象" in md and "## 2. 原始错误全文" in md))
        out.append(("分析包含输入与复现命令", "## 3. 当时的输入与调用" in md and "python -c print(1)" in md))
        # 脱敏：明文密钥绝不能出现在包里（这条是**功能**，不是措辞）。
        # 台账与包目录的重定向已由 `selftest()` 的外层 try/finally 完成（见其说明）。
        out.append(("失败通道台账可重定向（自检不写生产台账）",
                    "memsselftest-" in str(inc.ledger_path())))
        r2 = inc.record("manual", "演示：密钥不得外泄", source="selftest",
                        params={"api_key": "SK-SHOULD-NOT-APPEAR-1234"},
                        error_text="key=SHOULD-NOT-APPEAR-1234")
        leaked = ("SHOULD-NOT-APPEAR-1234" in inc.render_md(r2)
                  or "SHOULD-NOT-APPEAR-1234" in json.dumps(r2, ensure_ascii=False))
        out.append(("失败通道脱敏（明文密钥不进包）", not leaked))
        out.append(("失败通道可读回刚写入的那条", inc.get(r2["incident_id"]) is not None))
        first = inc.write_package(r2["incident_id"])
        again = inc.write_package(r2["incident_id"])
        out.append(("失败通道包文件拒绝覆盖（append-only）",
                    "md_path" in first and "拒绝覆盖" in str(again.get("error"))))
        out.append(("自检不往生产包目录写东西",
                    "memsselftest-" in str(first.get("dir") or "")))
        out.append(("失败通道拒答也是可分析的条目", "refusal" in inc.KINDS))
        # ⑯ 上报给 DSH 的三条门禁（**不启动任何东西**：只验拒绝路径与 prompt 组装）
        dsh, derr = _dsh()
        if dsh is None:
            out.append(("上报模块可加载", False))
        else:
            out.append(("上报模块可加载", True))
            was = STATE.get("mode")
            STATE["mode"] = "offline"
            blocked = _dsh_start({"incident_id": "inc-nope", "confirm": True})
            out.append(("离线模式拒绝上报（用户口径）",
                        blocked.get("blocked_by") in ("offline_mode",)))
            STATE["mode"] = "deepseek"
            need = _dsh_start({"incident_id": "inc-nope"})
            out.append(("上报需显式 confirm（花 token 的动作）",
                        bool(need.get("needs_confirmation")) or "没有这条记录" in str(need.get("error"))))
            # 无 confirm_spawn 时必须拒绝启动（实测被这条救过：冒烟测试真起了 DSH）
            nospawn = dsh.start_report("inc-selftest", "# 包", confirm_spawn=False)
            out.append(("未显式 confirm_spawn 拒绝启动真实 DSH",
                        nospawn.get("blocked_by") == "confirm_spawn_required"))
            prompt = dsh.build_prompt("inc-selftest", "# 包",
                                      prompt_path=Path(tempfile.gettempdir()) / "analysis.md")
            out.append(("上报 prompt 含逐条只读约束",
                        all(r in prompt for r in dsh.READONLY_RULES)))
            out.append(("上报 prompt 要求说清不确定处",
                        "你不确定的地方" in prompt and "不许猜" in prompt))
            STATE["mode"] = was
    for name, ok in out:
        print(("[OK]   " if ok else "[FAIL] ") + name, flush=True)
    return 0 if all(ok for _, ok in out) else 2


def _is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


def _read_or_create_lan_token(path: Path) -> str:
    """读取或一次性创建局域网访问令牌；令牌只落在 gitignored 的 work/ 中。"""
    path = path.resolve()
    if path.is_file():
        token = path.read_text(encoding="utf-8").strip()
        if len(token) < 16:
            raise ValueError("局域网令牌文件内容过短（至少 16 字符）：%s" % path)
        return token
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(24)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token


def _local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET):
            address = item[4][0]
            if address and not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)


def check_bind(host: str, token: str | None) -> str | None:
    """绑定守卫（**fail-closed**）：非回环地址必须带 `--token`，否则拒绝启动。

    为什么：当前阶段只允许本机访问；将来要开局域网/对外时，**必须**同时带上鉴权，
    不能"顺手把 host 改成 0.0.0.0" 就把控制台暴露出去（它能在本机跑写产物的任务）。
    """
    if _is_loopback(host):
        return None
    if not token:
        return ("拒绝绑定非回环地址 %s：必须同时给 --token（本控制台能在本机执行写产物任务，"
                "裸暴露等于把写权限交出去）。" % host)
    if len(token) < 16:
        return "拒绝：--token 太短（至少 16 字符）"
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MEMS 平台网页控制台（默认本机）")
    ap.add_argument("--port", type=int, default=8877)
    ap.add_argument("--host", default="127.0.0.1",
                    help="默认 127.0.0.1；非回环地址必须同时给 --token（fail-closed）")
    ap.add_argument("--token", default=None,
                    help="访问令牌（非回环绑定时必填）；请求需带 Authorization: Bearer <token>")
    ap.add_argument("--token-file", default=None,
                    help="从文件读取访问令牌；文件不存在时安全生成并复用（默认 work/runtime/lan-access-token.txt）")
    ap.add_argument("--lan", action="store_true",
                    help="一键局域网模式：绑定 0.0.0.0，自动生成/复用令牌并打印可复制网址")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--exec-task", default=None,
                    help="内部用：在子进程里执行一个已登记任务（配合 --args-json/--out-json）")
    ap.add_argument("--args-json", default="{}")
    ap.add_argument("--out-json", default=None)
    args = ap.parse_args(argv)
    # ⚠️ 子进程入口必须在**任何服务启动/绑定检查之前**返回，
    #    否则子进程会试图再绑一次端口（或触发 fail-closed 退出）。
    if args.exec_task:
        if not args.out_json:
            print("[FAIL] --exec-task 需要 --out-json")
            return 2
        return _exec_task_entry(args.exec_task, args.args_json, args.out_json)
    if args.selftest:
        return selftest()
    host = "0.0.0.0" if args.lan else args.host
    token = args.token
    token_path = Path(args.token_file) if args.token_file else REPO / "work/runtime/lan-access-token.txt"
    if not token and (args.lan or not _is_loopback(host)):
        if not token_path.is_absolute():
            token_path = REPO / token_path
        try:
            token = _read_or_create_lan_token(token_path)
        except (OSError, ValueError) as exc:
            print("[FAIL] 无法准备局域网令牌：%s" % exc)
            return 2
    guard = check_bind(host, token)
    if guard:
        print("[FAIL] " + guard)
        return 2
    if token:
        TOKEN["value"] = token
    # 允许"在 npx 缓存里自动发现 dsh"——**只有控制台自己打开这个开关**，
    # 免得测试/脚本在没设 DSH_BIN 时顺手把真实 dsh 拉起来（实测发生过，真花 token）。
    os.environ.setdefault("MEMS_DSH_ALLOW_DISCOVERED", "1")
    srv = ThreadingHTTPServer((host, args.port), Handler)
    print("MEMS 控制台：http://%s:%d/  （Ctrl+C 停止）" % (host, args.port))
    print("工作模式默认 **离线**（不发网络请求）；页面右上角可切到 DeepSeek。")
    if token:
        print("已启用令牌鉴权（Authorization: Bearer …）")
    if not _is_loopback(host):
        encoded = urllib.parse.quote(token or "", safe="")
        print("局域网访问地址（把其中一个完整地址复制到其他电脑）：")
        for address in _local_ipv4_addresses():
            print("  http://%s:%d/?token=%s" % (address, args.port, encoded))
        print("令牌文件：%s（不要提交、不要发给不受信任的人）" % token_path.resolve())
    print("已登记任务 %d 个：%s" % (len(TASKS), ", ".join(sorted(TASKS))))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
