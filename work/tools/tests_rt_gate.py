"""rt_gate 故障注入测试（Codex 2026-09-14 裁定 §8）。

**不通过真实压垮内存来完成**：全部使用模拟值/测试进程，符合裁定要求。

覆盖裁定的 5 个故障场景 + 单元规则：
  T1 sampler 进程退出
  T2 时间线停更 > 15 s（引擎内检测 + 外层 sidecar_health 检测）
  T3 端口被无关 PID 占用
  T4 checkpoint 写失败可检出且不留半写文件
  T5 硬线必须**连续两个**采样才触发（单次不触发；中间回落要清零）
  T6 commit 硬线同规则 + 软线只预警
  T7 软线只阻止下一组合，不取消当前组合
  T8 PeakWorkingSet 不作实时信号（只审计）

用法：python work/tools/tests_rt_gate.py    （退出码 0 = 全通过）
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rt_gate import (  # noqa: E402
    GateEngine, Thresholds, atomic_write_json, port_owner_ok, sidecar_health,
)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))


def S(ws=None, avail=None, commit=None, peak=None, **kw) -> dict:
    s = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "server_working_set_mb": ws, "system_available_physical_mb": avail,
         "commit_available_mb": commit, "server_peak_working_set_mb": peak}
    s.update(kw)
    return s


# ---------------- T1 / T2：sidecar 与时间线 ----------------
def t1_sidecar_exit() -> None:
    h = sidecar_health(now=1000.0, last_sample_ts=998.0, proc_alive=False)
    check("T1 sampler 退出 → hard_stop", h["verdict"] == "hard_stop"
          and "sidecar_exited" in h["reasons"], str(h))
    h2 = sidecar_health(now=1000.0, last_sample_ts=None, proc_alive=True)
    check("T1b 尚无采样 → hard_stop", h2["verdict"] == "hard_stop", str(h2))


def t2_timeline_stall() -> None:
    ok = sidecar_health(now=1000.0, last_sample_ts=996.0, proc_alive=True)
    check("T2 停更 4 s → ok", ok["verdict"] == "ok", str(ok))
    bad = sidecar_health(now=1000.0, last_sample_ts=980.0, proc_alive=True)
    check("T2b 停更 20 s → hard_stop", bad["verdict"] == "hard_stop"
          and any("sidecar_stale" in r for r in bad["reasons"]), str(bad))

    e = GateEngine()
    e.evaluate(S(ws=100.0, avail=20000.0, commit=9000.0), now=100.0)
    r = e.evaluate(S(ws=100.0, avail=20000.0, commit=9000.0), now=120.0)
    check("T2c 引擎内空档 20 s → sample_gap 硬停",
          r["verdict"] == "hard_stop" and any("sample_gap" in x for x in r["reasons"]), str(r))
    check("T2d 空档事件已记录", len(e.gap_events) == 1, str(e.gap_events))


# ---------------- T3：端口归属 ----------------
def t3_port_owner() -> None:
    check("T3 归属一致 → ok", port_owner_ok(4242, 4242, True)["ok"] is True)
    m = port_owner_ok(4242, 9999, True)
    check("T3b 归属不一致 → 拒绝", m["ok"] is False and "mismatch" in m["reason"], str(m))
    check("T3c 端口未开 → 拒绝", port_owner_ok(4242, 4242, False)["ok"] is False)
    check("T3d 期望 PID 未知 → 拒绝", port_owner_ok(None, 1, True)["ok"] is False)
    check("T3e 占用者未知 → 拒绝", port_owner_ok(4242, None, True)["ok"] is False)


# ---------------- T4：checkpoint 写失败 ----------------
def t4_checkpoint_write() -> None:
    with tempfile.TemporaryDirectory() as td:
        good = Path(td) / "ck.json"
        r = atomic_write_json(good, {"a": 1})
        check("T4 正常写 → ok", r["ok"] is True and good.is_file(), str(r))

        missing_parent = Path(td) / "nope" / "ck.json"
        bad = atomic_write_json(missing_parent, {"a": 1})
        check("T4b 父目录不存在 → 可检出失败",
              bad["ok"] is False and "error" in bad, str(bad))
        check("T4c 失败不留 .tmp", not missing_parent.with_name("ck.json.tmp").exists())

        # 目标是已存在的目录 → os.replace 必失败
        d = Path(td) / "adir"
        d.mkdir()
        bad2 = atomic_write_json(d, {"a": 1})
        check("T4d 目标为目录 → 可检出失败", bad2["ok"] is False, str(bad2))
        check("T4e 不破坏原目录", d.is_dir())


# ---------------- T5 / T6：连续采样门禁 ----------------
def t5_ws_two_consecutive() -> None:
    e = GateEngine()
    r1 = e.evaluate(S(ws=12300.0, avail=20000.0, commit=9000.0), now=1.0)
    check("T5 首次越 WS 硬线 → 不硬停（仅预警）",
          r1["verdict"] == "warning" and r1["counters"]["ws_hard"] == 1, str(r1))
    r2 = e.evaluate(S(ws=12300.0, avail=20000.0, commit=9000.0), now=2.0)
    check("T5b 连续第二次 → 硬停",
          r2["verdict"] == "hard_stop" and any("ws_hard_stop" in x for x in r2["reasons"]), str(r2))

    e2 = GateEngine()
    e2.evaluate(S(ws=12300.0, avail=20000.0, commit=9000.0), now=1.0)
    e2.evaluate(S(ws=11000.0, avail=20000.0, commit=9000.0), now=2.0)
    r3 = e2.evaluate(S(ws=12300.0, avail=20000.0, commit=9000.0), now=3.0)
    check("T5c 中间回落后计数清零 → 不硬停",
          r3["counters"]["ws_hard"] == 1 and r3["verdict"] != "hard_stop", str(r3))

    e3 = GateEngine()
    e3.evaluate(S(ws=11000.0, avail=20000.0, commit=9000.0), now=1.0)
    check("T5d 11500 以下不预警", e3.warnings_seen == [], str(e3.warnings_seen))


def t6_commit_and_avail() -> None:
    e = GateEngine()
    a = e.evaluate(S(ws=11000.0, avail=20000.0, commit=4000.0), now=1.0)
    check("T6 commit 首次低于硬线 → 预警不硬停",
          a["verdict"] == "warning" and a["counters"]["commit_hard"] == 1, str(a))
    b = e.evaluate(S(ws=11000.0, avail=20000.0, commit=4000.0), now=2.0)
    check("T6b commit 连续第二次 → 硬停",
          b["verdict"] == "hard_stop" and any("commit_hard_stop" in x for x in b["reasons"]), str(b))

    # 边界：5000 > 4096 → 不得触发（先前 T6c 误用 5000 断言触发，是测试写错，非代码错）
    e4 = GateEngine()
    e4.evaluate(S(ws=11000.0, avail=5000.0, commit=9000.0), now=1.0)
    edge = e4.evaluate(S(ws=11000.0, avail=5000.0, commit=9000.0), now=2.0)
    check("T6e 物理可用 5000 > 4096 → 不硬停（边界）",
          edge["verdict"] == "ok" and edge["counters"]["avail_hard"] == 0, str(edge))

    e2 = GateEngine()
    e2.evaluate(S(ws=11000.0, avail=4000.0, commit=9000.0), now=1.0)
    c = e2.evaluate(S(ws=11000.0, avail=4000.0, commit=9000.0), now=2.0)
    check("T6c 物理可用连续两次 ≤4096 → 硬停",
          c["verdict"] == "hard_stop"
          and any("physical_avail_hard_stop" in x for x in c["reasons"]), str(c))

    e3 = GateEngine()
    d = e3.evaluate(S(ws=11000.0, avail=20000.0, commit=6000.0), now=1.0)
    check("T6d commit 6000 → 预警（<=6144）", d["verdict"] == "warning", str(d))


# ---------------- T7：软线语义 ----------------
def t7_soft_blocks_next_only() -> None:
    e = GateEngine()
    e.evaluate(S(ws=11600.0, avail=20000.0, commit=9000.0), now=1.0)
    d = e.to_dict()
    check("T7 软线 → 无硬停", not d["hard_stops"], str(d["hard_stops"]))
    check("T7b 软线 → 阻止下一组合", d["blocks_next_combination"] is True, str(d))
    e2 = GateEngine()
    e2.evaluate(S(ws=11000.0, avail=20000.0, commit=9000.0), now=1.0)
    check("T7c 无越线 → 不阻止下一组合",
          e2.to_dict()["blocks_next_combination"] is False, str(e2.to_dict()))


# ---------------- T8：Peak WS 只审计 ----------------
def t8_peak_not_realtime() -> None:
    e = GateEngine()
    r = e.evaluate(S(ws=3000.0, avail=20000.0, commit=9000.0, peak=99999.0), now=1.0)
    check("T8 Peak 极高但当前 WS 正常 → 不触发任何门禁",
          r["verdict"] == "ok" and not e.hard_stops and not e.warnings_seen, str(r))
    th = Thresholds().to_dict()
    check("T8b 阈值表不含任何 peak 实时门禁",
          not any("peak" in k for k in th), str(list(th)))


def t9_warning_dedup() -> None:
    """真实时间线回放暴露的缺陷：按数值累积会产生上百条同类预警，必须按类型去重计数。"""
    e = GateEngine()
    for i, c in enumerate((6000.0, 5000.0, 4500.0), start=1):
        e.evaluate(S(ws=11000.0, avail=20000.0, commit=c), now=float(i))
    d = e.to_dict()
    check("T9 同类预警按类型去重为 1 条", len(d["warnings_seen"]) == 1, str(d["warnings_seen"]))
    check("T9b 预警计数为 3", d["warning_counts"].get("commit_warning") == 3,
          str(d["warning_counts"]))
    check("T9c 预警只留首次的具体数值（6000）", "6000.0" in d["warnings_seen"][0],
          str(d["warnings_seen"]))


def main() -> int:
    for fn in (t1_sidecar_exit, t2_timeline_stall, t3_port_owner, t4_checkpoint_write,
               t5_ws_two_consecutive, t6_commit_and_avail, t7_soft_blocks_next_only,
               t8_peak_not_realtime, t9_warning_dedup):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            check(f"{fn.__name__} 未抛异常", False, f"{type(exc).__name__}: {exc}")
    bad = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  <- {detail}" if not ok and detail else ""))
    print(f"\n合计 {len(RESULTS)} 项，通过 {len(RESULTS) - len(bad)}，失败 {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
