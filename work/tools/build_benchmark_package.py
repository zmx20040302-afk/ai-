# -*- coding: utf-8 -*-
"""M4：构建**匿名可复现 benchmark 包** `work/dist/peakguard-bench-v1-20261013/`。

原则：
  * 数据**逐字节复制**（4 个 CSV 经侦察确认**无**身份/路径泄漏）；不改数据内容；
  * 代码**逐字复制 + 少量单命中字面替换**（把内部绝对/相对路径换成包内相对路径、内联 `_identity_key`），
    每处替换都必须**恰好命中 1 次**，否则 fail-closed；
  * 期望值**从注册件提取**（不是凭记忆写）；
  * 构建后对**整包**做身份/双盲审计（用户名、主机、绝对路径、仓库相对路径、`.mph`、邮箱、ssh 键）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
N2 = REPO / "work/runs/eda64-20261010/n2_baselines"
SRC_RUNNER = N2 / "run_n2_baselines.py"
SRC_FITTER = REPO / "work/runs/multichannel-surrogate-20260929/fit_multichannel_surrogate.py"
SRC_SWEEP = REPO / "src/memsharness/sweep_analysis.py"
DATA = {
    "labels_two_batch_v3.csv": REPO / "work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv",
    "channels_multichannel.csv": REPO / "work/runs/first-peak-20260929/multichannel_labels.csv",
    "labels_v2_frozen.csv": REPO / "work/runs/remote-exported-v2-20260922/v2_labels_frozen_20261008T143151.csv",
    "splits_grouped_five_seeds.csv": REPO / "work/runs/grouped-split-20261009/grouped_split_assignments.csv",
}
QUAR = REPO / "work/runs/multichannel-surrogate-20260929/multichannel_model.json"
REG = N2 / "baselines_by_seed.json"
PKG = REPO / "work/dist/peakguard-bench-v1-20261013"

# ---- 任务套件（v2 新增）------------------------------------------------------
DEV = REPO / "work/runs/ai11-m4-20261013/tasks_dev"
PKG_SRC = REPO / "work/runs/ai11-m4-20261013/pkg_src"
ORACLE_SRC = REPO / "work/runs/ai11-t7-multiseed-20261013/dse/points"
EXPECTED_TASKS = REPO / "work/runs/ai11-m4-20261013/EXPECTED_TASKS.json"
TASK_FILES = {  # 包内相对路径 → 源文件（逐字复制；路径清洗已在各移植件内完成并自证）
    "tasks/label_validity.py": DEV / "label_validity/label_validity.py",
    "tasks/m1_m2_m3.py": DEV / "m1_m2_m3/m1_m2_m3.py",
    "tasks/t1_t2.py": DEV / "t1_t2/tasks/t1_t2.py",
    "tasks/t1_t2_spacing.py": DEV / "t1_t2/tasks/t1_t2_spacing.py",
    "tasks/t5.py": DEV / "t5/tasks/t5.py",
    "tasks/t7_scheduling.py": DEV / "t7/tasks/t7_scheduling.py",
    "check_tasks.py": DEV / "_harness/check_tasks.py",
    "run_tasks.py": DEV / "_harness/run_tasks.py",
    "verify_package.py": DEV / "_harness/verify_package.py",
    "tasks/_text.py": PKG_SRC / "_text.py",
    "tasks/t7_frozen_protocol.py": PKG_SRC / "t7_frozen_protocol.py",
    "tasks/ref_ledger.json": DEV / "t7/tasks/ref_ledger.json",
    "REPRODUCIBILITY.md": PKG_SRC / "REPRODUCIBILITY.md",
    "requirements.txt": PKG_SRC / "requirements.txt",
}
# vendored 件里**出现即失败**的串：包面向匿名评审，任何内部痕迹都会泄漏作者/基础设施
FORBIDDEN = [("内路径", re.compile(r"work[/\\]runs")),
             ("仓库名", re.compile(r"memsharness")),
             ("用户名", re.compile(r"\bzmx\b|zhangmx", re.I)),
             ("主机名", re.compile(r"node0\d|10\.180\.7\.46|ubuntu-10-180-7-46")),
             ("绝对路径", re.compile(r"[A-Za-z]:[\\/]")),
             ("COMSOL 安装", re.compile(r"COMSOL64|comsolbatch|comsolcompile")),
             ("桌面路径", re.compile(r"Desktop|桌面")),
             ("unix home", re.compile(r"/home/|/Users/")),
             ("邮箱", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
             ("ssh 痕迹", re.compile(r"\.ssh|id_rsa|codex_ubuntu")),
             ("模型文件", re.compile(r"[A-Za-z0-9_\-]+\.mph\b"))]

RISK = {
    "user": re.compile(r"\bzmx\b|zhangmx", re.I),
    "abs_drive": re.compile(r"[A-Za-z]:[\\/]"),
    "unix_home": re.compile(r"/home/|/Users/"),
    "desktop": re.compile(r"Desktop|桌面"),
    "host": re.compile(r"\bnode0\d\b|ubuntu-10-180-7-46"),
    "repo_name": re.compile(r"memsharness"),
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "ssh": re.compile(r"\.ssh|id_rsa|codex_ubuntu"),
    "workruns": re.compile(r"work[/\\]runs"),
    "mph": re.compile(r"[A-Za-z0-9_\-]+\.mph\b"),
}


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rel_posix(p: pathlib.Path, root: pathlib.Path) -> str:
    """清单键一律用 **POSIX 正斜杠**：包面向匿名评审，很可能在 Linux 上被读。"""
    return p.relative_to(root).as_posix()


def rep_once(t: str, old: str, new: str, label: str) -> str:
    n = t.count(old)
    if n != 1:
        raise SystemExit(f"[FAIL] {label} 命中 {n} 次（要求 1）")
    return t.replace(old, new)


def runtime_paragraph() -> str:
    """**从实测事实件**生成运行时长段落（规则 #34：时长是负载敏感量，不许手写单点值）。

    读取所有 `smoke_run_*.json`；缺件时明确写「未记录」，而不是编一个数。
    """
    import glob
    facts = []
    for p in sorted((REPO / "work/runs/ai11-m4-20261013").glob("smoke_run_*.json")):
        try:
            facts.append(json.loads(p.read_text(encoding="utf-8-sig")))
        except Exception:
            continue
    if not facts:
        return ("Not recorded: this build had no packaged full-chain run available, so no timing is "
                "claimed here. Run `python run_benchmark.py --check` and `python run_tasks.py --check` "
                "and time them yourself.")
    bench = [f["steps"][1]["wall_seconds"] for f in facts if len(f.get("steps") or []) > 2]
    tasks = [f["steps"][2]["wall_seconds"] for f in facts if len(f.get("steps") or []) > 2]
    tot = [f["wall_seconds_total"] for f in facts if f.get("wall_seconds_total")]
    # m1_m2_m3 自己的墙钟只在任务阶段日志里，**解析**而不是手写
    m13 = []
    evid = REPO / "work/runs/ai11-m4-20261013"
    for f in facts:
        for s in (f.get("steps") or []):
            if "任务套件" not in str(s.get("name", "")):
                continue
            lp = evid / str(s.get("log_file", ""))
            if lp.is_file():
                mm = re.search(r"--\s*m1_m2_m3:\s*ok\s*\(([\d.]+)\s*s\)",
                               lp.read_text(encoding="utf-8", errors="replace"))
                if mm:
                    m13.append(float(mm.group(1)))
    n = len(bench)
    stage_txt = ("`m1_m2_m3` dominates the task suite (it refits eight methods for the random-split arm and "
                 "recomputes the risk-coverage curves); the other five stages together finish in seconds to "
                 "tens of seconds.")
    if m13:
        stage_txt += (" That single stage measured **%.0f-%.0f s** (%.1f-%.1f minutes) across these runs, "
                      "i.e. the same stage varied by %.0f%% purely from concurrent load."
                      % (min(m13), max(m13), min(m13) / 60.0, max(m13) / 60.0,
                         100.0 * (max(m13) - min(m13)) / min(m13)))
    return ("**Timings drift with machine load and are not a promise.** Across **%d** recorded packaged "
            "full-chain runs on the authors' machine the baseline stage took **%.0f-%.0f s** and the task "
            "suite **%.0f-%.0f s** (full chain **%.0f-%.0f s**, i.e. up to **%.1f minutes**). %s "
            "So budget **25 minutes** for a full reproduction and do not treat any single figure here as a "
            "bound. No caching, subsampling or convergence-limit shortcut was taken to speed this up, because "
            "each would change the numbers."
            % (n, min(bench), max(bench), min(tasks), max(tasks), min(tot), max(tot), max(tot) / 60.0,
               stage_txt))


def main() -> int:
    # ---------- 0. 源码体检
    for p in (SRC_RUNNER, SRC_FITTER, SRC_SWEEP):
        if not p.is_file():
            raise SystemExit(f"[FAIL] 缺源文件 {p}")
    t_sweep = SRC_SWEEP.read_text(encoding="utf-8")
    f_num = re.search(r"(?ms)^def _num\(.*?(?=^def |\Z)", t_sweep).group(0).rstrip() + "\n"
    f_key = re.search(r"(?ms)^def _identity_key\(.*?(?=^def |\Z)", t_sweep).group(0).rstrip() + "\n"

    # ---------- 1. 目录
    if PKG.exists():
        shutil.rmtree(PKG)
    for d in ("data", "config", "expected", "results"):
        (PKG / d).mkdir(parents=True, exist_ok=True)

    # ---------- 2. 数据（逐字节复制）
    for name, src in DATA.items():
        shutil.copy2(src, PKG / "data" / name)
        if sha(PKG / "data" / name) != sha(src):
            raise SystemExit(f"[FAIL] 数据复制后哈希不一致：{name}")
    mq = json.loads(QUAR.read_text(encoding="utf-8"))
    (PKG / "data/excluded_quarantine.json").write_bytes(
        (json.dumps({"excluded_quarantine": mq["excluded_quarantine"],
                     "note": "the frozen quarantine list; this package takes only this field and "
                             "contains no internal model file"}, ensure_ascii=False, indent=2) + "\n")
        .encode("utf-8"))
    spec = json.loads((REPO / "work/runs/solver/pmut-f1/solver_spec.json").read_text(encoding="utf-8"))
    (PKG / "config/thresholds.json").write_bytes(
        (json.dumps({"thresholds": spec["thresholds"],
                     "note": "S0-S5 thresholds taken verbatim from the frozen solver specification; "
                             "no value was changed"}, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print("数据：4 个 CSV 逐字节复制 + 2 个派生配置")

    # ---------- 3. pchip_fitter.py（vendored，2 处替换）
    fit = SRC_FITTER.read_text(encoding="utf-8")
    fit = rep_once(fit, "用法：python -B work/runs/multichannel-surrogate-20260929/fit_multichannel_surrogate.py",
                   "用法：`import pchip_fitter`（本包内置的既有 PCHIP 口径实现）", "fitter-doc")
    fit = rep_once(fit, 'REPO = HERE.parents[2]\nLABELS = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"',
                   'PKG = HERE.parent\nLABELS = PKG / "data" / "channels_multichannel.csv"  # 仅供独立使用时读取；本包的评估把行直接传入',
                   "fitter-path")
    (PKG / "pchip_fitter.py").write_bytes(fit.encode("utf-8"))
    print("代码：pchip_fitter.py（2 处替换）")

    # ---------- 4. bench.py（vendored runner，逐处替换）
    t = SRC_RUNNER.read_text(encoding="utf-8")
    t = rep_once(t, "* 切分**只用** `work/runs/grouped-split-20261009/grouped_split_assignments.csv`",
                 "* 切分**只用** `data/splits_grouped_five_seeds.csv`", "runner-doc1")
    t = rep_once(t, "* 标签主表 = `work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv`（2255×30）。",
                 "* 标签主表 = `data/labels_two_batch_v3.csv`（2255×30）。", "runner-doc2")
    t = rep_once(t, "REPO = pathlib.Path(__file__).resolve().parents[4]",
                 "PKG = pathlib.Path(__file__).resolve().parent", "runner-pkg")
    t = rep_once(t, 'sys.path.insert(0, str(REPO / "src"))\n', "", "runner-syspath")
    t = rep_once(t, 'str(p.relative_to(REPO)).replace("\\\\", "/")',
                 'str(p.relative_to(PKG)).replace("\\\\", "/")', "runner-meta-rel")
    t = rep_once(t, "from memsharness.sweep_analysis import _identity_key  # noqa: E402",
                 "# --- 以下两个小助手从既有实现**逐字内联**（使本包自包含）---\n"
                 "from collections.abc import Mapping, Sequence  # noqa: E402\n"
                 "from typing import Any  # noqa: E402\n\n\n" + f_num + "\n\n" + f_key, "runner-import")
    t = rep_once(t, 'V3 = REPO / "work/runs/labels-two-batch-v3/20261008T170618/labels_two_batch.csv"',
                 'V3 = PKG / "data" / "labels_two_batch_v3.csv"', "runner-v3")
    t = rep_once(t, 'AC = REPO / "work/runs/first-peak-20260929/multichannel_labels.csv"',
                 'AC = PKG / "data" / "channels_multichannel.csv"', "runner-ac")
    t = rep_once(t, 'V2L = REPO / "work/runs/remote-exported-v2-20260922/v2_labels_frozen_20261008T143151.csv"',
                 'V2L = PKG / "data" / "labels_v2_frozen.csv"', "runner-v2")
    t = rep_once(t, 'ASSIGN = REPO / "work/runs/grouped-split-20261009/grouped_split_assignments.csv"',
                 'ASSIGN = PKG / "data" / "splits_grouped_five_seeds.csv"', "runner-assign")
    t = rep_once(t, 'FITTER = REPO / "work/runs/multichannel-surrogate-20260929/fit_multichannel_surrogate.py"',
                 'FITTER = PKG / "pchip_fitter.py"', "runner-fitter")
    t = rep_once(t, 'MODEL = REPO / "work/runs/multichannel-surrogate-20260929/multichannel_model.json"',
                 'QUARANTINE = PKG / "data" / "excluded_quarantine.json"', "runner-model")
    t = rep_once(t, 'SPEC = REPO / "work/runs/solver/pmut-f1/solver_spec.json"',
                 'THRESHOLDS = PKG / "config" / "thresholds.json"', "runner-spec")
    t = rep_once(t, 'OUT = REPO / "work/runs/eda64-20261010/n2_baselines"',
                 'OUT = PKG / "results"', "runner-out")
    t = rep_once(t, "    for p in (V3, AC, V2L, ASSIGN, FITTER, MODEL, SPEC):",
                 "    for p in (V3, AC, V2L, ASSIGN, FITTER, QUARANTINE, THRESHOLDS):", "runner-inputs")
    t = rep_once(t, 'qlist = json.loads(MODEL.read_text(encoding="utf-8")).get("excluded_quarantine") or []',
                 'qlist = json.loads(QUARANTINE.read_text(encoding="utf-8")).get("excluded_quarantine") or []',
                 "runner-qlist")
    t = rep_once(t, 'spec = json.loads(SPEC.read_text(encoding="utf-8"))',
                 'spec = {"thresholds": json.loads(THRESHOLDS.read_text(encoding="utf-8")).get("thresholds") or {}}',
                 "runner-specthr")
    t = rep_once(t, '"quarantine_source": {"file": str(MODEL.relative_to(REPO)).replace("\\\\", "/"),',
                 '"quarantine_source": {"file": "data/excluded_quarantine.json",', "runner-qsrc")
    t = rep_once(t, '"> 切分：`work/runs/grouped-split-20261009/grouped_split_assignments.csv` 的 "',
                 '"> 切分：`data/splits_grouped_five_seeds.csv` 的 "', "runner-md1")
    t = rep_once(t, '"pchip": "既有口径：**直接 import** work/runs/multichannel-surrogate-20260929/"',
                 '"pchip": "既有口径：**直接 import** 本包内置的 `pchip_fitter.py`（"', "runner-md2")
    left = [l for l in t.split("\n") if re.search(r"\bREPO\b|memsharness|work[/\\]runs", l)]
    if left:
        raise SystemExit("[FAIL] bench.py 仍残留内部引用（%d 行）：%s" % (len(left), left[:4]))
    lf = "\r\n" in t or "\r\n" in fit
    if lf:
        raise SystemExit("[FAIL] vendored 源码含 CRLF")
    (PKG / "bench.py").write_bytes(t.encode("utf-8"))
    print("代码：bench.py（17 处替换，REPO 引用已清空）")

    # ---------- 5. 期望值（从注册件提取）
    reg = json.loads(REG.read_text(encoding="utf-8"))
    exp_cells = {}
    for b, seeds in reg["per_seed"].items():
        for s, cell in seeds.items():
            for ch, cd in cell["channels"].items():
                for m, md in (cd.get("methods") or {}).items():
                    if md.get("median") is not None:
                        exp_cells.setdefault(b, {}).setdefault(ch, {}).setdefault(m, {})[s] = md["median"]
    exp = {"kind": "peakguard_bench_expected_outputs",
           "source_artifact": "frozen two-batch baseline run (registered)",
           "source_sha256": sha(REG), "source_bytes": REG.stat().st_size,
           "tolerance_rel": 1e-6,
           "anchors": {"persistence_bandwidth_Hz_C_seed0_median": 0.007726751204325416,
                       "persistence_defined_rows": 416,
                       "n_rows_corpus": len(open(DATA["labels_two_batch_v3.csv"], encoding="utf-8-sig").readlines()) - 1,
                       "cells_with_no_method_beating_persistence_grouped": 8,
                       "cells_with_no_method_beating_persistence_random": 7},
           "per_seed_cell_medians": exp_cells,
           "how_to_check": "python run_benchmark.py --check (per-cell relative error <= tolerance_rel)",
           "note": "the expected values are extracted from the frozen registered run; a different machine "
                   "or library version can move the last bits, which is why a relative tolerance is given "
                   "rather than exact equality"}
    (PKG / "expected/EXPECTED_OUTPUTS.json").write_bytes(
        (json.dumps(exp, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    print("期望值：%d 个批 × 通道 × 方法 × 种子格" % sum(len(v) for b in exp_cells.values() for v in b.values()))

    # ---------- 6. check_results.py / run_benchmark.py / README / license note / 解身份检查
    (PKG / "check_results.py").write_bytes(CHECK.encode("utf-8"))
    (PKG / "run_benchmark.py").write_bytes(RUNNER.encode("utf-8"))
    (PKG / "check_solution_identity.py").write_bytes(IDENTITY.encode("utf-8"))
    (PKG / "data/solution_identity_example.json").write_bytes(IDENTITY_EXAMPLE.encode("utf-8"))
    (PKG / "README.md").write_bytes(README.replace("@RUNTIME_PARAGRAPH@", runtime_paragraph()).encode("utf-8"))
    (PKG / "NOTE_on_license.md").write_bytes(LICENSE.encode("utf-8"))
    print("代码：check_solution_identity.py + data/solution_identity_example.json（解身份四步清单）")

    # ---------- 6b. 任务套件：vendored 脚本 + 免求解 oracle + 期望值 + 文档
    vendored = {}
    RUNTIME = runtime_paragraph()
    for rel, src in sorted(TASK_FILES.items()):
        if not src.is_file():
            raise SystemExit("[FAIL] 缺移植源件：%s（%s）" % (rel, src))
        b = src.read_bytes()
        if rel.endswith(".md") or rel.endswith(".txt"):
            txt0 = b.decode("utf-8")
            if "@RUNTIME_PARAGRAPH@" in txt0:
                b = txt0.replace("@RUNTIME_PARAGRAPH@", RUNTIME).encode("utf-8")
        if b"\r\n" in b:
            raise SystemExit("[FAIL] %s 含 CRLF（包内文本件一律 LF）" % rel)
        txt = b.decode("utf-8")
        hits = [(n, rx.findall(txt)[:3]) for n, rx in FORBIDDEN if rx.search(txt)]
        if hits:
            raise SystemExit("[FAIL] %s 含禁串：%s" % (rel, hits))
        dst = PKG / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b)
        vendored[rel] = {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(),
                         "source": str(src.relative_to(REPO)), "forbidden_scan": "clean"}
    if not ORACLE_SRC.is_dir():
        raise SystemExit("[FAIL] 缺 oracle 缓存目录：%s" % ORACLE_SRC)
    pts = sorted(ORACLE_SRC.glob("p_*.json"))
    if len(pts) < 90:
        raise SystemExit("[FAIL] oracle 缓存只有 %d 个点，疑似不完整" % len(pts))
    (PKG / "oracle/points").mkdir(parents=True, exist_ok=True)
    oracle_bytes = 0
    for p in pts:
        shutil.copy2(p, PKG / "oracle/points" / p.name)
        oracle_bytes += p.stat().st_size
    if not EXPECTED_TASKS.is_file():
        raise SystemExit("[FAIL] 缺 %s（先跑 work/tools/build_expected_tasks.py）" % EXPECTED_TASKS)
    et = EXPECTED_TASKS.read_bytes()
    if b"\r\n" in et:
        raise SystemExit("[FAIL] EXPECTED_TASKS.json 含 CRLF")
    (PKG / "expected/EXPECTED_TASKS.json").write_bytes(et)
    print("任务套件：%d 个 vendored 件（全部通过禁串扫描）+ oracle %d 点（%.2f MB）+ 期望件 %.2f MB"
          % (len(vendored), len(pts), oracle_bytes / 1e6, len(et) / 1e6))

    # ---------- 7. 身份审计
    audit, bad = {}, []
    for p in sorted(PKG.rglob("*")):
        if not p.is_file():
            continue
        txt = None
        try:
            txt = p.read_text(encoding="utf-8-sig", errors="strict")
        except Exception:
            try:
                txt = p.read_bytes().decode("utf-8", errors="ignore")
            except Exception:
                txt = ""
        hits = {}
        for name, rx in RISK.items():
            f = rx.findall(txt)
            if f:
                hits[name] = sorted({str(x) for x in f})[:5]
        if hits:
            bad.append({"file": rel_posix(p, PKG), "hits": hits})
        audit[rel_posix(p, PKG)] = {"bytes": p.stat().st_size, "sha256": sha(p),
                                    "identity_risk": hits or None}
    print("身份审计：%d 个文件，%d 个有风险串" % (len(audit), len(bad)))
    for b in bad:
        print("   ⚠️", b["file"], b["hits"])

    # ---------- 8. MANIFEST
    man = {"kind": "peakguard_bench_manifest", "package": PKG.name,
           "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "files": audit, "n_files": len(audit),
           "identity_audit_clean": not bad, "identity_findings": bad,
           "provenance": {"runner_source_sha256": sha(SRC_RUNNER),
                          "fitter_source_sha256": sha(SRC_FITTER),
                          "sweep_helper_source_sha256": sha(SRC_SWEEP),
                          "registered_result_sha256": sha(REG),
                          "data_source_sha256": {k: sha(v) for k, v in DATA.items()}},
           "environment_recorded": ENV,
           "vendored_task_suite": {
               "files": vendored,
               "oracle": {"dir": "oracle/points", "n_points": len(pts), "bytes": oracle_bytes,
                          "source_run": "frozen closed-loop campaign cache (copied byte-for-byte)",
                          "n_solves_at_replay": 0},
               "expected_tasks": {"sha256": hashlib.sha256(et).hexdigest(), "bytes": len(et),
                                  "source": str(EXPECTED_TASKS.relative_to(REPO)),
                                  "note": "由注册结果件自动抽取并剥离计时/时间戳/内部路径键"},
               "requirements_pinned": {"python": ENV.get("python"), "numpy": ENV.get("numpy"),
                                       "scipy": ENV.get("scipy"), "sklearn": ENV.get("sklearn")},
               "forbidden_string_scan": "vendored 件逐个通过（见 files[*].forbidden_scan）"},
           "non_claims": ["本包不含任何实测/实验数据；全部为仿真标签与其评估代码",
                          "不主张任何工程绝对值；不得用于替代求解器的结论",
                          "不主张本包已覆盖所有失败模式；已知限制见 README 与 REPRODUCIBILITY.md",
                          "解身份检查（check_solution_identity.py）是**记账规则不是物理结论**：它拒绝的是**不可比**，不主张被拒读数在物理上错误；其示例记录为**合成**且已如此标注",
                          "任务套件里的闭环实验是**免求解查表回放**（n_solves=0）：它复现的是**分析**，不是重新求解；缺缓存即拒答，不做外推",
                          "预注册件**不随包分发**：各任务只记录其文件名与 sha256（且不参与相等比对），包内无法复核该摘要",
                          "自由文本口径/不主张/逐格 note 由 `tasks/_text.py` 的表**渲染**为英文；表内保留原文以便审计，数值与结构未变",
                          "本包**未**经过第三方运行验证（仅作者环境冒烟通过）"]}
    (PKG / "MANIFEST.json").write_bytes((json.dumps(man, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print("MANIFEST：%d 个文件；identity_audit_clean=%s" % (len(audit), not bad))
    print("包路径：", PKG.relative_to(REPO))
    return 0


ENV = {}
try:
    import numpy, scipy, sklearn, sys as _s
    ENV = {"python": _s.version.split()[0], "numpy": numpy.__version__,
           "scipy": scipy.__version__, "sklearn": sklearn.__version__}
except Exception as e:  # noqa: BLE001
    ENV = {"probe_error": repr(e)}

CHECK = '''# -*- coding: utf-8 -*-
"""Compare the outputs in `results/` against `expected/EXPECTED_OUTPUTS.json` (relative tolerance)."""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected/EXPECTED_OUTPUTS.json").read_text(encoding="utf-8"))
TOL = float(EXP.get("tolerance_rel", 1e-6))


def main() -> int:
    got_p = HERE / "results/baselines_by_seed.json"
    if not got_p.is_file():
        print("[FAIL] results/baselines_by_seed.json not found; run bench.py first")
        return 2
    got = json.loads(got_p.read_text(encoding="utf-8"))["per_seed"]
    worst, n_ok, n_bad, n_missing = 0.0, 0, 0, 0
    bad = []
    for b, chans in EXP["per_seed_cell_medians"].items():
        for ch, methods in chans.items():
            for m, seeds in methods.items():
                for s, want in seeds.items():
                    cell = ((got.get(b) or {}).get(s) or {}).get("channels", {}).get(ch) or {}
                    md = (cell.get("methods") or {}).get(m) or {}
                    v = md.get("median")
                    if v is None:
                        n_missing += 1
                        continue
                    rel = abs(v - want) / abs(want) if want else abs(v - want)
                    worst = max(worst, rel)
                    if rel <= TOL:
                        n_ok += 1
                    else:
                        n_bad += 1
                        if len(bad) < 12:
                            bad.append({"batch": b, "seed": s, "channel": ch, "method": m,
                                        "expected": want, "got": v, "rel": rel})
    print("per-cell comparison: OK %d | over tolerance %d | missing %d | max relative deviation %.3e (tolerance %.1e)"
          % (n_ok, n_bad, n_missing, worst, TOL))
    for x in bad:
        print("   x", x)
    verdict = "PASS" if (n_bad == 0 and n_missing == 0) else "FAIL"
    print("verdict:", verdict)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''

IDENTITY = '''# -*- coding: utf-8 -*-
"""Solution-identity check: prove two stored solutions are comparable BEFORE re-evaluating anything.

Why this exists. One model file can hold several solutions. Re-evaluating post-processing on a stored
solution is unsafe once the model was re-meshed or its geometry edited after that solution was stored:
selection sets and entity numbers can go stale, so a selection that is valid for one solution can
silently address different faces on another. In the measured case behind this benchmark, a probe
evaluated from a hard-coded face list differed by a factor 6.667 between two solutions of the same file
that shared an identical geometry, an identical parameter read-back and a single mesh object.

The four-step checklist
  1. TAG          every solution is named, and the names are unique.
  2. STORED MESH  every solution carries a digest of the mesh it stored (not the model's current mesh).
  3. PARAMETERS   every compared solution reads back identical parameters at the design point.
  4. INVARIANT    a geometry-only integral agrees across the compared solutions within tolerance.

Admissibility of a quantity
  Steps 1-4 must pass. In addition, a quantity that declares depends_on_entity_numbering=true may be
  compared across solutions only if all of them share one stored-mesh digest, or if every record
  declares selection_re_resolved=true (the selection was re-resolved on that solution's own mesh by a
  geometric predicate). Copying entity indices between solutions is never admissible.

Usage
    python check_solution_identity.py                 # self-test on the bundled record
    python check_solution_identity.py RECORDS.json    # your own record

Exit code 0 means the checker reached the decision recorded in expected_decision (self-test), or that
every comparison is admissible. It never means the physics is right.
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT = HERE / "data/solution_identity_example.json"
STEPS = ("tag", "stored_mesh", "parameters", "invariant")
STEP_TEXT = {
    "tag": "1 TAG: every solution named, names unique",
    "stored_mesh": "2 STORED MESH: a digest of the stored mesh per solution",
    "parameters": "3 PARAMETERS: identical read-back at the design point",
    "invariant": "4 INVARIANT: a geometry-only integral agrees",
}


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def check(rec):
    """Return {steps, quantities, admissible, refused, comments} for one record."""
    sols = rec.get("solutions") or []
    tol = float(rec.get("tolerance_rel", 1e-9))
    comments, steps = [], {}

    tags = [s.get("tag") for s in sols]
    steps["tag"] = bool(sols) and all(isinstance(t, str) and t for t in tags) and len(set(tags)) == len(tags)
    if not steps["tag"]:
        comments.append("a solution has no tag, or two share one")

    digests = [s.get("stored_mesh_digest") for s in sols]
    steps["stored_mesh"] = all(isinstance(d, str) and d for d in digests)
    if not steps["stored_mesh"]:
        comments.append("a solution does not carry a stored-mesh digest: identity cannot be established")

    params = [json.dumps(s.get("params"), sort_keys=True) for s in sols]
    steps["parameters"] = len(set(params)) == 1 and params and params[0] != "null"
    if not steps["parameters"]:
        comments.append("the compared solutions do not read back identical parameters")

    keys = sorted({k for s in sols for k, q in (s.get("quantities") or {}).items()
                   if isinstance(q, dict) and q.get("geometry_only")})
    agree = True
    if not keys:
        agree = False
        comments.append("no geometry-only integral is declared, so step 4 cannot be evaluated")
    for k in keys:
        vals = [((s.get("quantities") or {}).get(k) or {}).get("value") for s in sols]
        if not all(_finite(v) for v in vals):
            agree = False
            comments.append("geometry-only integral " + k + " is not finite everywhere")
            continue
        lo, hi = min(vals), max(vals)
        spread = (hi - lo) / abs(lo) if lo else abs(hi - lo)
        if spread > tol:
            agree = False
            comments.append("geometry-only integral " + k + " disagrees by rel " + repr(spread))
    steps["invariant"] = agree

    one_digest = steps["stored_mesh"] and len(set(digests)) == 1
    quantities, admissible, refused = {}, [], []
    all_keys = sorted({k for s in sols for k in (s.get("quantities") or {})})
    for k in all_keys:
        qs = [((s.get("quantities") or {}).get(k) or {}) for s in sols]
        vals = [q.get("value") for q in qs]
        finite = [v for v in vals if _finite(v)]
        spread, ratio = None, None
        if len(finite) >= 2:
            lo, hi = min(finite), max(finite)
            spread = (hi - lo) / abs(lo) if lo else abs(hi - lo)
            ratio = (hi / lo) if lo else None
        geo = all(q.get("geometry_only") for q in qs)
        ent = any(q.get("depends_on_entity_numbering") for q in qs)
        re_res = all(q.get("selection_re_resolved") for q in qs)
        if not all(steps.values()):
            why = "identity steps failed"
            ok = False
        elif geo or not ent or one_digest or re_res:
            why = "geometry-only" if geo else ("not entity-numbered" if not ent else
                                               ("one stored mesh" if one_digest else "selection re-resolved"))
            ok = True
        else:
            why = "entity-numbered selection, different stored meshes, not re-resolved"
            ok = False
        quantities[k] = {"admissible": ok, "reason": why, "n_values": len(finite),
                         "max_rel_spread": spread, "max_ratio_hi_over_lo": ratio}
        (admissible if ok else refused).append(k)

    return {"steps": steps, "quantities": quantities, "admissible": admissible,
            "refused": refused, "comments": comments,
            "n_solutions": len(sols), "tags": tags, "n_stored_meshes": len(set(digests))}


def main(argv):
    path = pathlib.Path(argv[0]) if argv else DEFAULT
    rec = json.loads(path.read_text(encoding="utf-8"))
    res = check(rec)
    print("record:", path.name, "| solutions:", res["n_solutions"], "| distinct stored meshes:",
          res["n_stored_meshes"])
    for s in STEPS:
        print(("  OK   " if res["steps"][s] else "  FAIL ") + STEP_TEXT[s])
    for c in res["comments"]:
        print("     note:", c)
    print("  quantities:")
    for k, q in sorted(res["quantities"].items()):
        sp = "n/a" if q["max_rel_spread"] is None else ("%.4g" % q["max_rel_spread"])
        ra = "n/a" if q["max_ratio_hi_over_lo"] is None else ("%.4g" % q["max_ratio_hi_over_lo"])
        print("    " + ("ADMISSIBLE" if q["admissible"] else "REFUSED   ") + "  " + k +
              "  (n=" + str(q["n_values"]) + ", max rel spread=" + sp + ", max ratio hi/lo=" + ra +
              ") -- " + q["reason"])
    exp = rec.get("expected_decision")
    if exp is None:
        verdict = "PASS" if not res["refused"] else "REFUSED"
        print("verdict:", verdict, "(no expected_decision recorded; advisory only)")
        return 0 if not res["refused"] else 1
    got = {"steps": "pass" if all(res["steps"].values()) else "fail",
           "admissible": sorted(res["admissible"]), "refused": sorted(res["refused"]),
           "max_rel_spread_refused": {k: res["quantities"][k]["max_rel_spread"] for k in res["refused"]}}
    ok = True
    for k in ("steps", "admissible", "refused"):
        if got[k] != exp.get(k):
            ok = False
            print("  SELF-TEST MISMATCH on", k, ": got", got[k], "want", exp.get(k))
    for k, want in (exp.get("max_rel_spread_refused") or {}).items():
        a = got["max_rel_spread_refused"].get(k)
        if a is None or abs(a - want) / abs(want) > 1e-3:
            ok = False
            print("  SELF-TEST MISMATCH on max_rel_spread_refused[" + k + "]: got", a, "want", want)
    if set(got["max_rel_spread_refused"]) != set(exp.get("max_rel_spread_refused") or {}):
        ok = False
        print("  SELF-TEST MISMATCH on max_rel_spread_refused keys: got",
              sorted(got["max_rel_spread_refused"]), "want",
              sorted(exp.get("max_rel_spread_refused") or {}))
    print("self-test:", "PASS (checker reproduced the recorded decision)" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''

IDENTITY_EXAMPLE = '''{
  "kind": "solution_identity_record",
  "synthetic": true,
  "note": "Synthetic demonstration record. The quantities mirror the measured probe reported in the paper's supplement (section S13): four solutions of one model file, identical geometry (fluid-domain volume 2.094393557e-12), identical parameter read-back, one mesh object, yet an electrode-area quantity evaluated from a hard-coded face list differs by a factor 6.667. The stored-mesh digests here are synthetic labels, not values read from the model file. Scope of the printed spreads: max_rel_spread is relative to the SMALLEST value across all four solutions, so for the electrode area it is 5.667 and the corresponding ratio hi/lo is 6.667 (the factor quoted in the paper). The paper also quotes a factor 3.6 for the mean electrode potential; that is the sol1-vs-sol4 ratio, whereas the max spread printed here (8.78) is taken over all four solutions and is driven by sol2.",
  "tolerance_rel": 1e-09,
  "expected_decision": {
    "steps": "pass",
    "admissible": ["fluid_volume"],
    "refused": ["elec_area", "mean_elec_potential"],
    "max_rel_spread_refused": {"elec_area": 5.6666, "mean_elec_potential": 8.7801}
  },
  "solutions": [
    {
      "tag": "sol1",
      "stored_mesh_digest": "mesh-digest-A",
      "params": {"x_scale": 0.6, "n1": 4, "n2": 9},
      "quantities": {
        "fluid_volume": {"value": 2.094393557e-12, "geometry_only": true, "depends_on_entity_numbering": true, "selection_re_resolved": false},
        "elec_area": {"value": 3.5467e-09, "geometry_only": false, "depends_on_entity_numbering": true, "selection_re_resolved": false},
        "mean_elec_potential": {"value": 8.2248e-03, "geometry_only": false, "depends_on_entity_numbering": true, "selection_re_resolved": false}
      }
    },
    {
      "tag": "sol2",
      "stored_mesh_digest": "mesh-digest-A",
      "params": {"x_scale": 0.6, "n1": 4, "n2": 9},
      "quantities": {
        "fluid_volume": {"value": 2.094393557e-12, "geometry_only": true, "depends_on_entity_numbering": true, "selection_re_resolved": false},
        "elec_area": {"value": 3.5467e-09, "geometry_only": false, "depends_on_entity_numbering": true, "selection_re_resolved": false},
        "mean_elec_potential": {"value": 8.0439e-02, "geometry_only": false, "depends_on_entity_numbering": true, "selection_re_resolved": false}
      }
    },
    {
      "tag": "sol3",
      "stored_mesh_digest": "mesh-digest-A",
      "params": {"x_scale": 0.6, "n1": 4, "n2": 9},
      "quantities": {
        "fluid_volume": {"value": 2.094393557e-12, "geometry_only": true, "depends_on_entity_numbering": true, "selection_re_resolved": false},
        "elec_area": {"value": 3.5467e-09, "geometry_only": false, "depends_on_entity_numbering": true, "selection_re_resolved": false},
        "mean_elec_potential": {"value": 8.2248e-03, "geometry_only": false, "depends_on_entity_numbering": true, "selection_re_resolved": false}
      }
    },
    {
      "tag": "sol4",
      "stored_mesh_digest": "mesh-digest-B",
      "params": {"x_scale": 0.6, "n1": 4, "n2": 9},
      "quantities": {
        "fluid_volume": {"value": 2.094393557e-12, "geometry_only": true, "depends_on_entity_numbering": true, "selection_re_resolved": false},
        "elec_area": {"value": 5.3201e-10, "geometry_only": false, "depends_on_entity_numbering": true, "selection_re_resolved": false},
        "mean_elec_potential": {"value": 2.9744e-02, "geometry_only": false, "depends_on_entity_numbering": true, "selection_re_resolved": false}
      }
    }
  ]
}
'''

RUNNER = '''# -*- coding: utf-8 -*-
"""One-command entry point: run the benchmark, then optionally compare against the expected values.

    python run_benchmark.py                # baselines only: 8 methods x 5 seeds (~4 minutes)
    python run_benchmark.py --check        # run, compare per cell against expected/, then the identity self-test
    python run_benchmark.py --check-only   # seconds only: manifest integrity + expected-file sanity + identity self-test
    python run_benchmark.py --skip-ablations --check

The task suite (which needs the `results/baselines_by_seed.json` this script produces) has its own
entry point: `python run_tasks.py --check`.
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bench  # noqa: E402
import check_results  # noqa: E402
import check_solution_identity  # noqa: E402


def main() -> int:
    if "--check-only" in sys.argv:
        import verify_package  # noqa: E402
        return verify_package.main()
    argv = [a for a in sys.argv[1:] if a != "--check"]
    do_check = "--check" in sys.argv
    rc = bench.main(argv or ["--out", str(HERE / "results")])
    if rc:
        return rc
    if not do_check:
        return 0
    rc = check_results.main()
    if rc:
        return rc
    print()
    return check_solution_identity.main([])


if __name__ == "__main__":
    raise SystemExit(main())
'''

README = '''# PeakGuard-Bench v1 — a reliability benchmark for surrogate models of resonant multiphysics design

**What this is.** A frozen, self-contained benchmark for *how a surrogate model of a resonant
multiphysics design task should be evaluated*: label validity, split structure, strong baselines,
abstention, and the failure modes that make a numerically present label physically incomparable.

**What this is not.** It is not a solver, not a device database, and not a claim about any engineering
absolute value. All labels are **simulation** values for a piezoelectric micromachined ultrasonic
transducer (PMUT) parameter sweep; there is no experimental data in the package.

## Contents

| path | what |
|---|---|
| `data/labels_two_batch_v3.csv` | the 2,255-row union label table (two scan batches + one frozen 250-row batch) |
| `data/channels_multichannel.csv` | the eight-channel source table with the native state flags |
| `data/labels_v2_frozen.csv` | the frozen 250-row batch (four channels only) |
| `data/splits_grouped_five_seeds.csv` | the frozen split assignment, five seeds (`side_seed0..4`) |
| `data/excluded_quarantine.json` | the frozen quarantine list used by the ablations |
| `config/thresholds.json` | S0–S5 thresholds, copied unchanged |
| `bench.py` | the evaluation program (vendored, path-sanitised) |
| `pchip_fitter.py` | the registered PCHIP caliber implementation (vendored) |
| `run_benchmark.py` / `check_results.py` | one-command entry point and the expected-value checker |
| `check_solution_identity.py` | the four-step solution-identity check (see below) |
| `data/solution_identity_example.json` | synthetic record for that check, mirroring the measured probe |
| `tasks/` | **six task scripts covering five analyses**: label validity, split structure, T1/T2 classification (with a spacing/leakage addendum), refusal, closed-loop scheduling |
| `tasks/_text.py` | the English rendering table for the frozen free-text strings (see "Language" below) |
| `tasks/ref_ledger.json` | designs-only projection that pins the closed-loop call schedule (carries **no** objective values) |
| `tasks/t7_frozen_protocol.py` | the closed-loop pre-registration's **structural** content as data (the document itself is not distributed) |
| `oracle/points/` | the frozen closed-loop campaign cache, replayed **without any solver** |
| `run_tasks.py` / `check_tasks.py` | task-suite entry point and its deep checker |
| `verify_package.py` | seconds-long integrity check: per-file sha256, expected-file sanity, identity self-test |
| `expected/EXPECTED_OUTPUTS.json` | per-seed per-cell reference medians + anchors |
| `expected/EXPECTED_TASKS.json` | frozen reference for every task output, with the stripping policy recorded |
| `REPRODUCIBILITY.md` | **which reported numbers this package does and does not reproduce, and why** |
| `requirements.txt` | pinned versions (bit-for-bit needs them; see `MANIFEST.json`) |
| `MANIFEST.json` | sha256 of every file, plus a machine-run identity audit |

## Reproduce

```
python -m pip install -r requirements.txt
python run_benchmark.py --check-only   # seconds: is this copy intact?
python run_benchmark.py --check        # baselines + ablations + identity self-test
python run_tasks.py --check            # the task suite, then a deep comparison against expected/
```

@RUNTIME_PARAGRAPH@

**Language.** The internal pipeline wrote its free-text fields (calibers, non-claims, per-cell notes) in
Chinese. This package is an English artifact, so those strings are rendered in English by one explicit
table, `tasks/_text.py`, applied identically to the produced outputs and to the expected values — only
those string values change; no number, key name or structure does. Everything a reviewer reads as data
is English. The original text survives in exactly four places — the rendering table itself, comments in
the two vendored evaluation files, comments in the ported task scripts, and note fields inside the 94
frozen oracle payloads (which are shipped byte-for-byte as evidence) — and section 1 of
`REPRODUCIBILITY.md` names each one, with its size, so the claim can be checked rather than trusted.

Outputs land in `results/` (`baselines_by_seed.json`, `baseline_table.md`, and — unless
`--skip-ablations` — `ablations.json`, `ablations.md`). `--check` compares every per-seed per-cell
median against `expected/EXPECTED_OUTPUTS.json` with relative tolerance `1e-6`, prints `PASS`/`FAIL`,
and then runs `check_solution_identity.py` as a self-test on the bundled record.

`run_tasks.py` **needs** `results/baselines_by_seed.json` and fails closed if it is absent rather than
skipping stages. Its comparison is a **deep** one — structure, key names and values — so a changed
caliber or a dropped channel fails it, not just a changed number. Read `REPRODUCIBILITY.md` before
quoting any of the paper's numbers from this package.

## Solution identity, and why a numeric label can be incomparable

A single model file can hold several **solutions**. Re-evaluating post-processing on a stored solution
is unsafe once the model was re-meshed or its geometry edited after that solution was stored: selection
sets and entity numbers can go stale. In the measured case behind this benchmark, a probe evaluated from
a hard-coded face list differed by a factor **6.667** between two solutions of one file that shared an
**identical geometry** (fluid-domain volume equal to ten digits), an **identical parameter read-back**,
and a **single mesh object**. With geometry, mesh object and parameters identical, the only consistent
explanation is that the same entity numbers addressed different physical faces on the two stored meshes.

Before any number is compared across stored solutions or across files, all four of these must hold:

1. **Tag** — every compared solution is named, and the names are unique.
2. **Stored mesh** — every solution carries a digest of the mesh *it stored*, not of the model's current
   mesh.
3. **Parameters** — every compared solution reads back identical parameters at the design point.
4. **Invariant** — a geometry-only integral (such as the fluid-domain volume) agrees within tolerance.

Passing the four steps is **not** sufficient by itself. A quantity that depends on entity numbering may
be compared across solutions only if all of them share **one** stored-mesh digest, or if the selection
was **re-resolved on each solution's own mesh** by a geometric predicate. Copying entity indices between
solutions is never admissible — `check_solution_identity.py` refuses it and reports the observed spread,
so the refusal can be audited rather than trusted. It prints both the relative spread (relative to the
smallest compared value: 5.667 for the electrode area) and the corresponding ratio hi/lo (**6.667**, the
factor quoted above); the two are the same fact stated differently. Where re-resolution is impossible,
the quantity must be **re-solved** rather than re-used.

```
python check_solution_identity.py                 # self-test on the bundled record
python check_solution_identity.py RECORDS.json    # your own record
```

The bundled record is **synthetic and labelled as such**: its quantities mirror the measured probe, its
stored-mesh digests are synthetic labels (the file does not expose one), and its `expected_decision`
makes the script a self-test. Exit code 0 means the checker reproduced that recorded decision; it never
means the physics is right. This rule is bookkeeping, not physics: the discarded readings are not
claimed to be wrong, only non-comparable.

## The tasks

The benchmark is evaluated in two halves. `run_benchmark.py` covers the **regression** half — eight
strong baselines under a frozen duplicate-aware split with five seeds, plus six ablations, plus the
OOD abstention that is part of the ablation set. `run_tasks.py` covers the **analysis** half, which is
where the paper's negative and diagnostic results live:

| task | script | what it produces | paper |
|---|---|---|---|
| label validity | `tasks/label_validity.py` | rows per batch; how many two-sided −3 dB bandwidths are undefined because the crossing leaves the scan window; per-channel defined counts | §5, §6.1 |
| split structure and sensitivity | `tasks/m1_m2_m3.py` | what the split actually groups (duplicate clusters vs spacing), the x-adjacency leakage fraction, how much the verdict moves across split realisations, a risk–coverage curve under a pre-registered score, and cross-batch transfer gaps | §4.1, §6.3 |
| peak identity and closure classification | `tasks/t1_t2.py` (+ `tasks/t1_t2_spacing.py`, the spacing/leakage addendum) | balanced accuracy for predicting the label's own state flags, per batch and seed, under the frozen split | §6.3 |
| refusal behaviour | `tasks/t5.py` | accepted/refused counts and the false-accept rate at three registered tolerances | §6.2, §7 |
| closed-loop scheduling | `tasks/t7_scheduling.py` | four acquisition arms under a fixed budget, best-at-k and simple regret, and the out-of-domain proposal replay — **replayed from `oracle/points/` with zero solves** | §6.6 |

1. **Label validity** — a two-sided −3 dB bandwidth is undefined when the crossing leaves the scan
   window: 259 of 1,782 rows (14.5 %) in one batch and 69 of 223 (30.9 %) in the other are not closed.
2. **Resonance-semantic labelling** — the first peak can drift to or across the scan boundary; flags
   distinguish "peaked", "closed", "usable" and "quarantined".
3. **Eight baselines** — persistence (copy the nearest available neighbour), PCHIP, linear, kernel
   ridge, quadratic ridge, Gaussian process, gradient boosting, MLP, each with five seeds.
4. **Six ablations** — peak semantics, refusal, quarantine, log transform, extrapolation limit,
   active sampling.
5. **OOD abstention** — proposals outside the measured (x, N1, N2) grid are refused rather than
   extrapolated.

### The solver-free oracle, and what it does not mean

`tasks/t7_scheduling.py` does **not** call a solver. The closed-loop campaign's own result cache is
shipped under `oracle/points/` and replayed as a lookup oracle; the task reports `n_solves: 0` and the
number of cache hits. If a design the campaign would have requested is not in the cache, the task
**refuses** — it does not extrapolate, substitute a surrogate, or silently drop the arm. So what is
reproduced here is the **analysis** of a past campaign, never a fresh solve, and the cache bounds
exactly which arms are replayable.

## Known facts a user must not mis-read

* **The split is duplicate-aware, not spacing-disjoint.** Its grouping variable is duplicate clusters
  (541 of 2,255 rows, 24 %). Exactly repeated design points cannot straddle the split (each geometry
  cell and continuous coordinate occurs once: 0 % exact-key overlap in every batch). But at the
  finer batch's grid step (0.01), **91 %** of held-out rows have a *training* neighbour one step away
  (87 % and 90 % in the two coarser batches, step 0.1). Interpolation leakage is therefore **not**
  removed, and no result may be quoted as if it were.
* **The verdict is split-realisation sensitive.** Replacing the split with a size-matched uniform
  random one is geometrically equivalent (adjacent-step fraction within 4 points) yet moves the median
  error of 9 of 63 cells of the finer batch by more than 10 %, in both directions. The negative
  "no method beats persistence" result reproduces under both rules (8 of 20 vs 7 of 20 decidable
  channel×batch cells), so it is not an artefact of the split rule — but individual cell numbers
  should not be read as stable.
* **`None` is never a pass** and no threshold in `config/thresholds.json` was adjusted after the fact.
* **Persistence is a hard baseline**: on the two formal targets nothing beats it.

## Provenance and licence

Every file's sha256 is in `MANIFEST.json`, together with the hashes of the upstream run artifacts the
package was cut from, and the sha256 of each vendored task script. `NOTE_on_license.md` records that the
licence choice is deliberately left to the authors.

`REPRODUCIBILITY.md` is the honest map of coverage: it lists, row by row, which of the paper's reported
numbers this package reproduces and which it cannot (the solver-side physics gates and the
multi-frequency reduced-order model), with the reason for each. Read it before quoting a number from
here.
'''


LICENSE = '''# Licence — deliberately undecided

This package is prepared for anonymous review. The licence is **not** asserted here because the choice
(a permissive data licence such as CC-BY-4.0, a code licence such as MIT/Apache-2.0, or a
research-use-only notice) is the authors' decision and must be made before any public release.

Until that decision is recorded, treat the package as **review-only**: do not redistribute.

Code in `bench.py` and `pchip_fitter.py` is a vendored copy of the authors' own evaluation code;
the label tables are derived simulation output, not third-party data.
'''

if __name__ == "__main__":
    raise SystemExit(main())
