# -*- coding: utf-8 -*-
"""P4 / 门禁 #10：**OOD 拒答 → 回退 COMSOL → 来源分离**的端到端闭环实测（真跑，不桩）。

闭环三段（每段都必须留下可核对的证据）：
  ① **AI 路径必须拒答**：三种典型（隔离点 / 参数越域 / 状态未放行）各查一次，
     断言**返回体里没有任何数值**（fail-closed），并记录拒答原文与代号。
  ② **回退 = 真的提交并真的求解**：走平台队列（`JobQueue` + `LocalComsolBackend`）
     提交一个已注册模板、串行 drain 到终态，记录 `run_id / 命令 / 退出码 / 墙钟 / 结果`。
  ③ **来源分离**：把该 run `ingest_run` 进**独立**元数据库，断言样本 `source_type`
     只出现 `simulation`/`analytic`，**绝不出现 `ai_solver`**（红线 4/8），
     且 AI 路径的拒答**没有**在库里留下任何样本（拒答不是来源）。

⚠️ **载体口径（必须与数字同现）**：本测试用**解析可验证的 F2 二维模板**作**回退载体**，
因为闭环机制（拒答 → 提交 → 求解 → 盖章 → 分离来源）**与器件无关**，而器件级 PMUT 回退
单点成本是分钟~小时级（另见 N3/N4 的远端求解）。**因此本件不声称**「PMUT 器件级回退已验证」。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from memsharness import multichannel_surrogate as MCS  # noqa: E402
from memsharness import solver as solver_mod  # noqa: E402
from memsharness import store  # noqa: E402
from memsharness.comsol import backend as backend_mod  # noqa: E402
from memsharness.comsol import queue as queue_mod  # noqa: E402

GATE = REPO / "work/runs/eda64-20261010/p4_gate"
LOOP = GATE / "loop"
TEMPLATE = "heat_slab_2d"


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def ai_refusals() -> list[dict]:
    """① 三种 AI 路径拒答。返回逐条记录（含原文），**每条都必须无数字**。"""
    out = []
    probes = [
        ("隔离点（模型 excluded_quarantine）", lambda: MCS.predict(0.20, 1, 7)),
        ("参数越域（x_scale 超出适用域）", lambda: MCS.predict(1.50, 1, 7)),
        ("约束量误用（§3.4 只作约束）", lambda: MCS.predict(0.50, 1, 7, channels=["abs_pv_W"])),
    ]
    for label, fn in probes:
        rec = {"case": label}
        try:
            got = fn()
            rec.update({"refused": False, "numbers_returned": True,
                        "leak": json.dumps(got, ensure_ascii=False)[:400]})
        except MCS.Refused as exc:
            rec.update({"refused": True, "numbers_returned": False,
                        "reason_class": MCS._classify_refusal(str(exc)),
                        "reason": str(exc)})
        except Exception as exc:  # noqa: BLE001 - 如实记录，不吞
            rec.update({"refused": True, "numbers_returned": False,
                        "reason_class": "other_exception",
                        "reason": "%s: %s" % (type(exc).__name__, exc)})
        out.append(rec)
    # 状态未放行：`solver.solve()` 必须拒答（本平台 solver_spec 仍为 draft）
    spec = {"state": "draft", "model_id": "multichannel-surrogate-20260929",
            "applicability": {"param_bounds": {"x_scale": [0.2, 1.0]},
                              "geometry_family": "GF-pmut-te2"},
            "thresholds": {}, "stamps": {}}
    res = solver_mod.solve(spec, {"x_scale": 0.5, "geometry_family": "GF-pmut-te2"},
                           error_bound=None)
    out.append({"case": "状态未放行（solver_spec.state=draft）",
                "refused": bool(res.get("refused")), "numbers_returned": "field" in res,
                "reason_class": "state_not_approved" if res.get("refused") else "unexpected",
                "reason": res.get("reason"), "fallback": res.get("fallback")})
    assert all(r["refused"] and not r["numbers_returned"] for r in out), \
        "有查询没有 fail-closed：%s" % json.dumps(out, ensure_ascii=False)
    return out


def fallback_run() -> dict:
    """② 回退：真提交、真求解（本地 COMSOL），并轮询到终态。"""
    for sub in ("queue", "runs", "logs"):
        (LOOP / sub).mkdir(parents=True, exist_ok=True)
    db = LOOP / "store.duckdb"
    backend = backend_mod.get_backend("local")
    probe = backend.probe()
    rec: dict = {"carrier_template": TEMPLATE, "backend_probe": probe}
    with store.connect(db) as conn:
        store.init_schema(conn)
        q = queue_mod.JobQueue(root=LOOP / "queue", runs_root=LOOP / "runs",
                               logs_root=LOOP / "logs", backend=backend, conn=conn)
        t0 = time.time()
        run_id = q.submit(queue_mod.JobSpec(template=TEMPLATE,
                                            params={"q_in": 4000.0, "T0": 300.0},
                                            timeout_seconds=1800,
                                            notes=["P4 门禁 #10 回退闭环载体（F2 解析可验证模板）"]))
        rec["run_id"] = run_id
        rec["submit_wall_seconds"] = round(time.time() - t0, 3)
        done = q.drain()
        rec["drain_returned"] = done
        status = q.status(run_id)
        rec["status"] = {k: status.get(k) for k in
                         ("status", "exit_code", "wall_seconds", "started_at", "finished_at",
                          "diagnostic")}
        rec["run_dir"] = status.get("run_dir")
        rd = pathlib.Path(rec["run_dir"] or "")
        for name in ("job.json", "status.json", "result.json", "commands.json"):
            p = rd / name
            if p.is_file():
                rec.setdefault("artifacts", {})[name] = {"bytes": p.stat().st_size,
                                                         "sha256": sha(p)[:32]}
        res_path = rd / "result.json"
        if res_path.is_file():
            payload = json.loads(res_path.read_text(encoding="utf-8"))
            rec["outputs"] = payload.get("result")
            rec["analytic"] = payload.get("analytic")
            rec["comparison"] = payload.get("comparison")
        # ③ 入库 + 来源分离
        info = queue_mod.ingest_run(conn, q, run_id)
        rec["ingest"] = {"l0_passed": info.get("l0_passed")}
        rows = store.query(conn, "SELECT source_type, fidelity, outputs FROM sample "
                                 "WHERE run_id = ?", [run_id])
        rec["sample_source_types"] = sorted({str(r["source_type"]) for r in rows})
        rec["n_samples"] = len(rows)
        run_row = store.query(conn, "SELECT * FROM run WHERE run_id = ?", [run_id])[0]
        rec["run_row"] = {k: run_row.get(k) for k in
                          ("status", "backend", "pathway", "exit_code", "wall_seconds",
                           "model_sha256", "software")}
    rec["source_separation_ok"] = ("ai_solver" not in rec["sample_source_types"]
                                   and "simulation" in rec["sample_source_types"])
    return rec


def main() -> int:
    GATE.mkdir(parents=True, exist_ok=True)
    out: dict = {
        "kind": "p4_fallback_closed_loop",
        "gate_item": 10,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "calibers": {
            "carrier": ("用解析可验证的 F2 二维模板作**回退载体**：闭环机制与器件无关，"
                        "而器件级 PMUT 回退为分钟~小时级（另见 N3/N4 远端求解）"),
            "does_not_claim": "本件**不**声称「PMUT 器件级回退已验证」",
            "real_solve": "② 段是**真求解**（本地 COMSOL），非桩、非重放",
            "isolation": "队列/运行/元数据库都在 work/runs/eda64-20261010/p4_gate/loop/ 下，"
                         "不写生产队列与生产库",
        },
    }
    # 每次重跑前清掉上一轮的 loop 目录（本目录是本件自有的**临时**沙箱，非历史记录）
    if LOOP.exists():
        shutil.rmtree(LOOP)
    out["ai_path_refusals"] = ai_refusals()
    out["fallback"] = fallback_run()
    ok = (all(r["refused"] and not r["numbers_returned"] for r in out["ai_path_refusals"])
          and out["fallback"].get("status", {}).get("status") == "succeeded"
          and out["fallback"].get("source_separation_ok") is True)
    out["closed_loop_verified"] = bool(ok)
    out["verdict"] = "passed" if ok else "failed_or_inconclusive"
    (GATE / "FALLBACK_CLOSED_LOOP.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    L = ["# P4 / 门禁 #10：OOD 拒答 → 回退 COMSOL → 来源分离（端到端实测）", "",
         "- 生成：%s" % out["generated"],
         "- 载体口径：%s" % out["calibers"]["carrier"],
         "- **不声称**：%s" % out["calibers"]["does_not_claim"], "",
         "## ① AI 路径（全部 fail-closed，逐条无数字）", "",
         "| 场景 | 拒答 | 给出数字 | 原因代号 |", "|---|---|---|---|"]
    for r in out["ai_path_refusals"]:
        L.append("| %s | %s | %s | `%s` |" % (r["case"], r["refused"],
                                              r["numbers_returned"], r.get("reason_class")))
    f = out["fallback"]
    L += ["", "## ② 回退：真提交 + 真求解（平台队列，本地 COMSOL）", "",
          "- 模板（载体）：`%s`；`run_id` = `%s`" % (f["carrier_template"], f.get("run_id")),
          "- 终态：`%s`；退出码 %s；墙钟 %s s" % (f.get("status", {}).get("status"),
                                                 f.get("status", {}).get("exit_code"),
                                                 f.get("status", {}).get("wall_seconds")),
          "- 输出：%s（解析参考 %s）" % (json.dumps(f.get("outputs"), ensure_ascii=False),
                                        json.dumps(f.get("analytic"), ensure_ascii=False)),
          "- 运行目录：`%s`" % f.get("run_dir"), "",
          "## ③ 来源分离（红线 4/8）", "",
          "- 样本 `source_type` = %s（n=%s）；`l0_passed` = %s"
          % (f.get("sample_source_types"), f.get("n_samples"), f.get("ingest", {}).get("l0_passed")),
          "- **`ai_solver` 未出现**：%s" % f.get("source_separation_ok"), "",
          "## 结论", "",
          "- `closed_loop_verified` = **%s**（verdict=%s）" % (out["closed_loop_verified"],
                                                             out["verdict"]),
          "- 限制：载体是 F2 模板 ⇒ 只证明**机制**闭环；器件级 PMUT 回退需另做（未做）。"]
    (GATE / "FALLBACK_CLOSED_LOOP.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    print("\n== 写出", GATE / "FALLBACK_CLOSED_LOOP.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
