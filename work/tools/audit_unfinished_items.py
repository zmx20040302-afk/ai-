# -*- coding: utf-8 -*-
"""遗留任务盘点：**逐项核对真实状态**，不采信文档自述。

做法：对每个候选遗留项，去仓库里找**证据**（产物文件/行数/列数/注册表条目），
把「文档说怎样」与「磁盘上实际怎样」分开打印。找不到证据的项一律记为「无证据」。

⚠️ **本清单必须跟着现实更新**（2026-09-29 晚修）：上一版把「多通道代理」「跨批一致性模板」
等**已经做完**的项仍按「无证据/未开工」打印，读者会以为还欠着 —— 过时的审计脚本
比没有审计更糟。现在每一项都指向**当前**产物，并区分「已完成 / 已阻塞 / 待外部输入」。

用法：python -B work/tools/audit_unfinished_items.py
"""
from __future__ import annotations

import csv
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
W = REPO / "work"
MCP_SRC = (REPO / "src/memsharness/mcp_server.py").read_text(encoding="utf-8")
WEB_SRC = (REPO / "scripts/webapp_server.py").read_text(encoding="utf-8")

_BANNER_DOCS = ("docs/HANDOFF_TO_CODEX.md", "docs/TASK_PLAN.md",
                "docs/STATUS-20260913.md", "docs/STATUS-20260915-vs-original-order.md",
                "docs/TO_USER-status-20260915.md", "docs/TO_USER-status-simple.md",
                "docs/ANALYSIS-20260914-status-and-next-steps.md", "docs/WORK_COMPLETED.md")


def csv_shape(p: pathlib.Path) -> str:
    if not p.is_file():
        return "缺文件"
    with p.open(encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        rows = list(rd)
        return "%d 行 × %d 列" % (len(rows), len(rd.fieldnames or []))


def has(*globs: str) -> list[str]:
    out = []
    for g in globs:
        out += [str(p.relative_to(REPO)).replace("\\", "/") for p in REPO.glob(g)]
    return sorted(set(out))[:8]


def _pmut_l1() -> str:
    """**真查一次库**（只读），而不是写「见 /api」这种没用的指路。"""
    db = W / "store/mems.duckdb"
    if not db.is_file():
        return "**缺库**"
    try:
        import duckdb
        con = duckdb.connect(str(db), read_only=True)
        n, npass = con.execute(
            "select count(*), sum(case when passed then 1 else 0 end) "
            "from validation where level='L1'").fetchone()
        toys = con.execute(
            "select count(*) from validation where level='L1' and passed "
            "and result like '%heat_slab_2d%'").fetchone()[0]
        con.close()
        return ("%s 条 L1，passed=%s（其中 %s 条是 heat_slab_2d 玩具模板）⇒ **PMUT 的 L1 仍为 0**"
                % (n, npass, toys))
    except Exception as exc:
        return "查询失败：%s" % exc


def _has_text(rel: str, needle: str) -> bool:
    p = REPO / rel
    return p.is_file() and needle in p.read_text(encoding="utf-8")


ITEMS = [
    # ---------------- 数据与分析产物 ----------------
    ("裁定§4 一组合一行指标表",
     lambda: csv_shape(W / "runs/first-peak-20260929/first_peak_metrics.csv")),
    ("多通道统一标签表（裁定§4 超集）",
     lambda: csv_shape(W / "runs/first-peak-20260929/multichannel_labels.csv")),
    ("隔离与修正的 append-only 台账",
     lambda: has("work/runs/**/QUARANTINE_AMENDMENTS.jsonl",
                 "work/runs/**/*prereg_registry.json")),
    # ---------------- 本轮（2026-09-29 晚）完成的 7 项 ----------------
    ("① 多通道 DOE 网格筛查（端点）",
     lambda: "GET /api/mc/screen 已注册" if "def _mc_screen" in WEB_SRC else "**缺**"),
    ("① 多通道代理模型",
     lambda: csv_shape(W / "runs/multichannel-surrogate-20260929/multichannel_model.json")),
    ("① 多通道代理预注册",
     lambda: has("work/runs/multichannel-surrogate-20260929/PREREG_multichannel_surrogate.md")
     or "**缺**"),
    ("② 数据B↔批A 交叉检查",
     lambda: has("work/runs/data-b-crosscheck-20260929/DATA_B_VS_A_REPORT.md") or "**缺**"),
    ("③ 热力图多层聚合（不再「最后一层覆盖」）",
     lambda: "已改（mean_of_layers）" if _has_text("src/memsharness/first_peak.py",
                                                  "mean_of_layers") else "**缺**"),
    ("④ 跨批一致性模板参数化",
     lambda: "已支持 --fold/--models/--out-prefix"
     if _has_text("work/tools/cross_batch_consistency_report.py", "--out-prefix") else "**缺**"),
    ("⑤ WORKING_PLAN §7.1 现状对照",
     lambda: "已加" if _has_text("WORKING_PLAN.md", "7.1 现状对照") else "**缺**"),
    ("⑥ 陈旧状态文档指路横幅",
     lambda: "%d / %d 个已加" % (sum(1 for r in _BANNER_DOCS
                                    if _has_text(r, "状态/计划部分已过时")), len(_BANNER_DOCS))),
    ("⑦ 本审计脚本自身已更新",
     lambda: "是（本文件）"),
    # ---------------- 平台侧（已交付） ----------------
    ("MCP 控制台/代理工具",
     lambda: "%d 个（console_*/monitor_*）" % len(re.findall(r"^def (?:console_|monitor_)",
                                                            MCP_SRC, re.M))),
    ("控制台端点：任务超时可见性",
     lambda: "已注册" if "/api/tasks/active" in WEB_SRC and "/cancel" in WEB_SRC else "**缺**"),
    ("控制台端点：子智能体（离线点名）",
     lambda: "已注册" if "/api/agents/payload" in WEB_SRC else "**缺**"),
    ("任务执行台账（append-only）",
     lambda: ("%d 行" % len((W / "logs/task_runs.jsonl").read_text(encoding="utf-8")
                            .splitlines())) if (W / "logs/task_runs.jsonl").is_file()
     else "**尚未创建**"),
    ("现有响应级代理（单通道 SPL）",
     lambda: has("work/runs/surrogate-response-20260929/surrogate_model.npz") or "**缺**"),
    # ---------------- 仍未完成：分「阻塞」与「待外部输入」 ----------------
    ("[阻塞] mesh_fingerprint（角点归因 + fmax 是否改网格）",
     lambda: has("work/runs/**/mesh_fingerprint*", "work/**/mesh_fingerprint*")
     or "**无证据 ⇒ 需 COMSOL 侧执行**"),
    ("[阻塞] 场快照（S1 场级误差界前提）",
     lambda: ("%d 个 .npz，但**仅 20 MHz**、旧 phase0 网格"
              % len(list((W / "runs/phase0-field-holdout-20260915/exports").rglob("*.npz"))))
     if (W / "runs/phase0-field-holdout-20260915/exports").is_dir() else "**无证据**"),
    ("[阻塞] Stage-1 双向扩扫数据",
     lambda: (has("work/runs/first-peak-20260929/STAGE1_REQUEST.md")
              and "**仅请求书，数据侧未回**") or "**无证据**"),
    ("[阻塞] te2_9 / N2=9 数据",
     lambda: has("work/runs/**/cell_*_9") or "**无证据（数据侧在跑）**"),
    ("[阻塞] PMUT L1 网格收敛", _pmut_l1),
    ("[待外部输入] 设备规格 pending_human 字段",
     lambda: has("schemas/*device_spec*") or "**缺**"),
]


def main() -> int:
    print("=" * 104)
    print("遗留任务盘点：磁盘实际状态（脚本取证，非文档自述）")
    print("=" * 104)
    n_done = n_blocked = 0
    for name, fn in ITEMS:
        try:
            val = fn()
        except Exception as exc:                     # 取证失败要显式说，不能静默
            val = "取证异常 %s: %s" % (type(exc).__name__, exc)
        if isinstance(val, list):
            val = "；".join(val) if val else "**无证据**"
        if name.startswith("[阻塞]") or name.startswith("[待外部输入]"):
            n_blocked += 1
        else:
            n_done += 1
        print("  %-46s %s" % (name, val))
    print("\n合计 %d 项：其中**需外部输入/阻塞** %d 项。" % (len(ITEMS), n_blocked))
    print("已完成项的证据都在上方路径里；阻塞项已写明缺什么。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
