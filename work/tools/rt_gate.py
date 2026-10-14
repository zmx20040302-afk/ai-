"""LT2 实时门禁引擎（纯逻辑、无 COMSOL / 无 PowerShell 依赖 → 可用模拟值做故障注入测试）。

Codex 2026-09-14 裁定 §Q2 / §Q5 的规则实现：
  - Peak WS 单调不减，**只作审计**，不作实时信号；
  - 实时软/硬线：

        expected_high_water : current_server_ws_mb < 11500
        hard_stop           : current_server_ws_mb >= 12288  连续 2 个 5 s 采样
        physical hard_stop  : system_available_physical_mb <= 4096 连续 2 个采样
        commit warning      : commit_available_mb <= 6144
        commit hard_stop    : commit_available_mb <= 4096 连续 2 个采样

  - 连续 15 s 没有新样本 → 停止投递并报警；
  - 软线只阻止**下一组合**，硬线取消**当前**组合。

本模块只做判定，不做动作（动作在 lt2_production.py 的外层 supervisor 里），
因此可以脱离 COMSOL 单独测试。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

GAP_LIMIT_S = 15.0
SAMPLE_INTERVAL_S = 5.0


@dataclass
class Thresholds:
    """实时门禁阈值。默认值全部来自 Codex 2026-09-14 裁定，不得静默放宽。"""

    ws_warning_mb: float = 11500.0
    ws_hard_stop_mb: float = 12288.0
    physical_avail_hard_stop_mb: float = 4096.0
    commit_warning_mb: float = 6144.0
    commit_hard_stop_mb: float = 4096.0
    consecutive_samples: int = 2
    # Codex 未指定物理内存软线 → 显式留空，不自行发明数字
    physical_avail_warning_mb: float | None = None
    sample_interval_s: float = SAMPLE_INTERVAL_S
    gap_limit_s: float = GAP_LIMIT_S

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GateEngine:
    """逐样本计算，**运行期实时**给出判定；不做事后回放。"""

    th: Thresholds = field(default_factory=Thresholds)
    n_ws_hard: int = 0
    n_avail_hard: int = 0
    n_commit_hard: int = 0
    n_samples: int = 0
    last_sample_ts: float | None = None
    warnings_seen: list[str] = field(default_factory=list)
    hard_stops: list[str] = field(default_factory=list)
    # 按「类型」去重的计数（用真实时间线回放时发现：按数值累积会得到上百条同类条目）
    warning_counts: dict[str, int] = field(default_factory=dict)
    hard_stop_counts: dict[str, int] = field(default_factory=dict)
    gap_events: list[dict] = field(default_factory=list)

    # ---- 单样本判定 ----
    def evaluate(self, s: dict, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        self.n_samples += 1
        reasons: list[str] = []
        warnings: list[str] = []

        ws = _f(s.get("server_working_set_mb"))
        avail = _f(s.get("system_available_physical_mb"))
        commit = _f(s.get("commit_available_mb"))

        # --- 硬线：需连续 N 个采样 ---
        self.n_ws_hard = self.n_ws_hard + 1 if (ws is not None and ws >= self.th.ws_hard_stop_mb) else 0
        self.n_avail_hard = (self.n_avail_hard + 1
                             if (avail is not None and avail <= self.th.physical_avail_hard_stop_mb)
                             else 0)
        self.n_commit_hard = (self.n_commit_hard + 1
                              if (commit is not None and commit <= self.th.commit_hard_stop_mb)
                              else 0)

        if self.n_ws_hard >= self.th.consecutive_samples:
            reasons.append(f"ws_hard_stop({ws} >= {self.th.ws_hard_stop_mb} x{self.n_ws_hard})")
        if self.n_avail_hard >= self.th.consecutive_samples:
            reasons.append(f"physical_avail_hard_stop({avail} <= {self.th.physical_avail_hard_stop_mb}"
                           f" x{self.n_avail_hard})")
        if self.n_commit_hard >= self.th.consecutive_samples:
            reasons.append(f"commit_hard_stop({commit} <= {self.th.commit_hard_stop_mb}"
                           f" x{self.n_commit_hard})")

        # --- 软线：只预警 ---
        if ws is not None and ws >= self.th.ws_warning_mb:
            warnings.append(f"ws_warning({ws} >= {self.th.ws_warning_mb})")
        if commit is not None and commit <= self.th.commit_warning_mb:
            warnings.append(f"commit_warning({commit} <= {self.th.commit_warning_mb})")
        if (self.th.physical_avail_warning_mb is not None and avail is not None
                and avail <= self.th.physical_avail_warning_mb):
            warnings.append(f"physical_avail_warning({avail})")

        # --- 采样空档 ---
        gap = None
        if self.last_sample_ts is not None:
            gap = round(now - self.last_sample_ts, 3)
            if gap > self.th.gap_limit_s:
                ev = {"gap_s": gap, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
                self.gap_events.append(ev)
                reasons.append(f"sample_gap({gap}s > {self.th.gap_limit_s}s)")
        self.last_sample_ts = now

        for w in warnings:
            kind = w.split("(")[0]
            self.warning_counts[kind] = self.warning_counts.get(kind, 0) + 1
            if kind not in [x.split("(")[0] for x in self.warnings_seen]:
                self.warnings_seen.append(w)   # 只留**首次**出现时的具体数值
        for r in reasons:
            kind = r.split("(")[0]
            self.hard_stop_counts[kind] = self.hard_stop_counts.get(kind, 0) + 1
            if kind not in [x.split("(")[0] for x in self.hard_stops]:
                self.hard_stops.append(r)      # 只留首次触发的具体证据

        verdict = "hard_stop" if reasons else ("warning" if warnings else "ok")
        return {"verdict": verdict, "reasons": reasons, "warnings": warnings,
                "gap_s": gap, "n_samples": self.n_samples,
                "counters": {"ws_hard": self.n_ws_hard, "avail_hard": self.n_avail_hard,
                             "commit_hard": self.n_commit_hard}}

    # ---- 批次级判定 ----
    def blocks_next_combination(self) -> bool:
        """软线只阻止下一组合；硬线亦阻止（当前组合已被取消）。"""
        return bool(self.hard_stops or self.warnings_seen)

    def to_dict(self) -> dict:
        return {"thresholds": self.th.to_dict(), "n_samples": self.n_samples,
                "warnings_seen": self.warnings_seen, "hard_stops": self.hard_stops,
                "warning_counts": self.warning_counts, "hard_stop_counts": self.hard_stop_counts,
                "gap_events": self.gap_events,
                "blocks_next_combination": self.blocks_next_combination()}


def _f(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def sidecar_health(now: float, last_sample_ts: float | None, proc_alive: bool,
                   th: Thresholds | None = None) -> dict:
    """外层 supervisor 用：sidecar 是否还活着 / 时间线是否停更。

    Codex §Q5：连续 15 s 没有新样本即停止投递并报警；sidecar 异常退出时
    外层 supervisor 将当前任务标为 blocked。
    """
    th = th or Thresholds()
    if not proc_alive:
        return {"verdict": "hard_stop", "reasons": ["sidecar_exited"]}
    if last_sample_ts is None:
        return {"verdict": "hard_stop", "reasons": ["sidecar_no_sample_yet"]}
    age = round(now - last_sample_ts, 3)
    if age > th.gap_limit_s:
        return {"verdict": "hard_stop", "reasons": [f"sidecar_stale({age}s > {th.gap_limit_s}s)"],
                "age_s": age}
    return {"verdict": "ok", "reasons": [], "age_s": age}


def port_owner_ok(expected_pid: int | None, actual_pid: int | None,
                  port_open: bool) -> dict:
    """端口归属校验：端口被非本任务 PID 占用即硬停（Codex §Q5 / LT2-D）。"""
    if not port_open:
        return {"ok": False, "reason": "port_not_open"}
    if expected_pid is None:
        return {"ok": False, "reason": "expected_pid_unknown"}
    if actual_pid is None:
        return {"ok": False, "reason": "port_owner_unknown"}
    if int(actual_pid) != int(expected_pid):
        return {"ok": False, "reason": f"port_owner_mismatch(expected={expected_pid} "
                                       f"actual={actual_pid})"}
    return {"ok": True, "reason": "port_owner_matches_task_pid"}


def atomic_write_json(path: Path, obj: Any) -> dict:
    """原子写：临时文件 + fsync + `os.replace`，并带**有界重试**。

    **为什么需要重试（2026-09-14 实测确诊）**：Windows 上 `os.replace` 覆盖一个
    **正被其它进程读取**的目标文件会抛 `PermissionError: [WinError 5] 拒绝访问`
    （同类还有 WinError 32 共享冲突）。本函数被三处共用，而三处的目标文件都**同时被读**：

        sampler 写 sampler_state.json ←→ supervisor 每 2.5–3 s 轮询读它
        worker  写 worker_state.json  ←→ supervisor / sidecar 读它
        worker  写 checkpoint.json    ←→ 聚合读它

    修复前该异常直接冒泡 ⇒ 调用方致命退出（sampler rc=2 ⇒ supervisor 判 `sidecar_exited`
    ⇒ `sampler_supervisor_integrity` ⇒ **整个逻辑批 blocked**）。
    定向压测（含并发读取）复现 10/80；**12.5% 是压测复现率，不是生产故障率**。

    **fail-closed 语义不变**：重试耗尽仍失败 ⇒ 照旧返回 `{"ok": False, ...}` 并清理 `.tmp`，
    绝不静默丢弃写入。
    返回 dict 增加 `attempts` / `retries`，使「重试是否被触发过」可被观测。
    """
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    max_attempts, backoff_s = 5, 0.05
    last_exc: Exception | None = None
    attempts_made = 0
    for attempt in range(1, max_attempts + 1):
        attempts_made = attempt
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(obj, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            return {"ok": True, "path": str(path), "bytes": path.stat().st_size,
                    "attempts": attempt, "retries": attempt - 1}
        except OSError as exc:
            last_exc = exc
            winerr = getattr(exc, "winerror", None)
            if winerr not in (5, 32) or attempt == max_attempts:
                break
            time.sleep(backoff_s)
        except Exception as exc:  # noqa: BLE001 - 需要把任何失败原样上报
            last_exc = exc
            break
    try:
        if tmp.exists():
            tmp.unlink()
    except Exception:
        pass
    return {"ok": False, "path": str(path),
            "error": f"{type(last_exc).__name__}: {last_exc}" if last_exc else "unknown",
            "attempts": attempts_made, "retries": max(0, attempts_made - 1),
            "note": "重试耗尽仍失败 ⇒ fail-closed（未静默丢弃）"}


def read_json_safe(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
