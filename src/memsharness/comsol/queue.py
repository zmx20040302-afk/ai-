"""COMSOL 求解任务的文件队列 + 单实例串行 worker。

为什么是文件队列（而不是数据库队列）：
- DuckDB 是单写者：让 worker 进程写库会与调用方抢锁，跨境协调成本高。
- 文件队列让「提交」与「执行」彻底解耦：``submit`` 只写几个 JSON 就返回，
  满足「提交即返回 run_id、绝不阻塞」的硬要求（WORKING_PLAN 2.4 / R11）。
- 数据库写入集中在**同一个进程**里完成（提交时写 run，收尾时由 ``ingest_run`` 补样本与产物）。

单实例互斥：``work/queue/locks/worker.lock`` 上的字节范围锁（Windows 用 ``msvcrt.locking``，
POSIX 用 ``fcntl.flock``）。同一时刻只有一个 worker 能持有它，从而保证
「同一时刻只有一个 COMSOL 求解在跑」（license/内存约束，WORKING_PLAN R1）。

目录布局（全部在运行区内，不进版本库）：
    work/queue/
        jobs/<run_id>.json        排队中（存在即待执行）
        jobs/<run_id>.claimed     已被 worker 认领
        jobs/<run_id>.done        已结束
        locks/worker.lock         单实例锁
        status/<run_id>.json      状态镜像（便于 list_jobs 快速扫描）
        worker_status.json        worker 自己的存活状态
        env_snapshot.json         COMSOL 环境快照缓存（避免每次提交都探一次）
    work/runs/<run_id>/
        job.json                  提交的 job spec（输入快照）
        status.json               状态机与时间戳
        <class>.java              生成的模型源码
        <class>.class             编译产物
        commands.json             实际执行过的命令 + 退出码 + 墙钟
        compile.stdout.log / compile.stderr.log
        batch.stdout.log / batch.stderr.log / batchlog.txt
        out.mph                   求解结果模型
        result.json               抽取结果 + 解析对照
        worker.log                worker 的执行日志
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Windows 文件锁；非 Windows 用 fcntl；两者都没有时退化为 O_EXCL 哨兵文件
try:  # pragma: no cover - 平台分支
    import msvcrt
except ImportError:  # pragma: no cover
    msvcrt = None  # type: ignore[assignment]
try:  # pragma: no cover - 平台分支
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

from .. import env as env_mod
from .. import store as store_mod
from ..paths import ensure_work_tree, work_root
from . import backend as backend_mod
from . import diagnostics
from . import java_model
from .backend import ExecutionBackend, ExecutionOutcome, PreparedRun

__all__ = [
    "JobSpec",
    "FileLock",
    "JobQueue",
    "new_run_id",
    "TERMINAL_STATUSES",
    "ingest_run",
    "worker_main",
]

TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")
ACTIVE_STATUSES = ("queued", "running")

# 状态机（只允许这些跃迁）
_ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "queued": ("running", "cancelled", "failed"),
    "running": ("succeeded", "failed", "cancelled"),
    "succeeded": (),
    "failed": (),
    "cancelled": (),
}

ENV_SNAPSHOT_TTL_SECONDS = 900


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(moment: datetime | None = None) -> str:
    return (moment or utcnow()).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def new_run_id(prefix: str = "run") -> str:
    """生成可排序、文件系统安全的 run_id：``run-20260601T120000Z-3f9a1c2b``。"""
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"


def _json_dump(path: Path, payload: dict[str, Any]) -> Path:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def _json_load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------------------------------
# 文件锁
# --------------------------------------------------------------------------------------


class FileLock:
    """跨进程文件锁（非阻塞优先）。

    - Windows：``msvcrt.locking(fd, LK_NBLCK, 1)`` 锁住文件首字节。注意 Windows 的
      字节范围锁是**句柄级**的：同一进程内用第二个句柄锁同一区间同样会失败，
      因此本类可用于进程内互斥测试。
    - POSIX：``fcntl.flock(LOCK_EX | LOCK_NB)``。
    - 都没有：退化为 ``O_EXCL`` 哨兵文件（释放即删除）。
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._handle: Any = None
        self._sentinel_used = False

    def acquire(self, blocking: bool = False, poll_seconds: float = 1.0, timeout: float | None = None) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self._try_acquire():
                return True
            if not blocking:
                return False
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(poll_seconds)

    def _try_acquire(self) -> bool:
        if msvcrt is not None:
            handle = self.path.open("a+b")
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                handle.close()
                return False
            self._handle = handle
            return True
        if fcntl is not None:  # pragma: no cover - POSIX 分支
            handle = self.path.open("a+b")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                return False
            self._handle = handle
            return True
        # 退化方案：O_EXCL 哨兵
        try:  # pragma: no cover - 仅当两种锁都不可用时
            with self.path.open("xb"):
                pass
        except FileExistsError:
            return False
        self._sentinel_used = True
        return True

    def release(self) -> None:
        if self._sentinel_used:  # pragma: no cover
            self.path.unlink(missing_ok=True)
            self._sentinel_used = False
            return
        if self._handle is None:
            return
        try:
            if msvcrt is not None:
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            elif fcntl is not None:  # pragma: no cover
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None

    @property
    def held(self) -> bool:
        return self._handle is not None or self._sentinel_used

    def __enter__(self) -> "FileLock":
        if not self._try_acquire():
            raise RuntimeError(f"无法获取文件锁：{self.path}")
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


# --------------------------------------------------------------------------------------
# Job spec
# --------------------------------------------------------------------------------------


@dataclass
class JobSpec:
    """一次求解任务的声明式描述（提交前的全部输入）。"""

    template: str
    params: dict[str, float] = field(default_factory=dict)
    backend: str = "local"
    timeout_seconds: int = 3600
    design_id: str | None = None
    notes: list[str] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    sweep_id: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "JobSpec":
        return cls(
            template=str(payload["template"]),
            params={k: float(v) for k, v in dict(payload.get("params") or {}).items()},
            backend=str(payload.get("backend", "local")),
            timeout_seconds=int(payload.get("timeout_seconds", 3600)),
            design_id=payload.get("design_id"),
            notes=list(payload.get("notes") or []),
            tags={str(k): str(v) for k, v in dict(payload.get("tags") or {}).items()},
            sweep_id=payload.get("sweep_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------------------
# 队列
# --------------------------------------------------------------------------------------


class JobQueue:
    """文件队列 + 单实例串行 worker。

    ``conn`` 可选：传入 DuckDB 连接时，``submit`` 会写 ``design``/``run`` 记录，
    ``run_job`` 结束时写 ``artifact``。为 None 时队列完全不碰数据库
    （便于在没有元数据库的场景下单独测试队列语义）。
    """

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        conn: Any | None = None,
        backend: ExecutionBackend | None = None,
        runs_root: Path | str | None = None,
        logs_root: Path | str | None = None,
    ) -> None:
        ensure_work_tree()
        self.root = Path(root) if root else work_root() / "queue"
        self.runs_root = Path(runs_root) if runs_root else work_root() / "runs"
        self.logs_root = Path(logs_root) if logs_root else work_root() / "logs"
        self.conn = conn
        self.backend: ExecutionBackend = backend or backend_mod.get_backend("local")
        self._ensure_dirs()

    # ---- 目录 -------------------------------------------------------------------

    def _ensure_dirs(self) -> None:
        for sub in ("jobs", "locks", "status"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.logs_root.mkdir(parents=True, exist_ok=True)

    @property
    def lock_path(self) -> Path:
        return self.root / "locks" / "worker.lock"

    def run_dir(self, run_id: str) -> Path:
        return self.runs_root / run_id

    def _ticket(self, run_id: str, suffix: str = ".json") -> Path:
        return self.root / "jobs" / f"{run_id}{suffix}"

    # ---- 环境快照 ---------------------------------------------------------------

    def environment_snapshot(self, force: bool = False) -> dict[str, Any]:
        """COMSOL 环境快照（带缓存，避免每次提交都探一次）。"""
        cache = self.root / "env_snapshot.json"
        cached = _json_load(cache)
        if cached and not force:
            captured = cached.get("captured_at_unix")
            if isinstance(captured, (int, float)) and time.time() - captured < ENV_SNAPSHOT_TTL_SECONDS:
                return cached
        probe = self.backend.probe()
        snapshot = {
            "captured_at": _iso(),
            "captured_at_unix": time.time(),
            "ttl_seconds": ENV_SNAPSHOT_TTL_SECONDS,
            "backend": self.backend.name,
            "probe": probe,
        }
        _json_dump(cache, snapshot)
        return snapshot

    # ---- 提交 -------------------------------------------------------------------

    def submit(self, spec: JobSpec | dict[str, Any]) -> str:
        """写任务文件后立即返回 run_id（非阻塞；此处不做任何求解）。"""
        if isinstance(spec, dict):
            spec = JobSpec.from_dict(spec)
        template = java_model.get_template(spec.template)
        params = java_model.validate_values(template, spec.params)
        if spec.backend == "remote":
            raise NotImplementedError(
                "backend='remote' 未实现（P0–P2 只实现 local，见 WORKING_PLAN 决策点 D4）。"
            )
        run_id = new_run_id()
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        design_id = spec.design_id or f"design-{run_id}"
        snapshot = self.environment_snapshot()

        units = {p.name: p.unit for p in template.params}
        job = {
            "run_id": run_id,
            "design_id": design_id,
            "created_at": _iso(),
            "backend": spec.backend,
            "template": template.name,
            "template_title": template.title,
            "pathway": "comsolbatch",
            "fidelity": template.fidelity,
            "geometry_family": template.geometry_family,
            "params": params,
            "param_units": units,
            "timeout_seconds": int(spec.timeout_seconds),
            "notes": list(spec.notes),
            "tags": dict(spec.tags),
            "sweep_id": spec.sweep_id,
            "environment_snapshot": snapshot,
            "estimator_version": java_model.EXTRACTOR_VERSION,
        }
        _json_dump(run_dir / "job.json", job)
        status = {
            "run_id": run_id,
            "status": "queued",
            "attempts": 0,
            "created_at": job["created_at"],
            "updated_at": job["created_at"],
            "queued_at": job["created_at"],
            "started_at": None,
            "finished_at": None,
            "exit_code": None,
            "wall_seconds": None,
            "diagnostic": None,
            "pid": None,
            "notes": [],
        }
        self._write_status(run_id, status, mirror=True)
        _json_dump(self._ticket(run_id), {"run_id": run_id, "created_at": job["created_at"]})

        if self.conn is not None:
            self._record_queued_run(job)
        return run_id

    def _write_status(self, run_id: str, status: dict[str, Any], *, mirror: bool = True) -> None:
        status["updated_at"] = _iso()
        _json_dump(self.run_dir(run_id) / "status.json", status)
        if mirror:
            _json_dump(self.root / "status" / f"{run_id}.json", status)

    def _set_status(self, run_id: str, status: dict[str, Any], new: str, **extra: Any) -> dict[str, Any]:
        current = str(status.get("status"))
        if new != current and new not in _ALLOWED_TRANSITIONS.get(current, ()):
            raise RuntimeError(f"非法状态跃迁：{current} -> {new}（run_id={run_id}）")
        status = dict(status)
        status["status"] = new
        status.update(extra)
        self._write_status(run_id, status)
        return status

    def _record_queued_run(self, job: dict[str, Any]) -> None:
        """提交时写 design + run（status=queued）。溯源字段此刻能拿到的全部写入。"""
        conn = self.conn
        conn.execute(
            "INSERT INTO design (design_id, params, units, geometry_family, source_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                job["design_id"],
                json.dumps(job["params"], ensure_ascii=False),
                json.dumps(job["param_units"], ensure_ascii=False),
                job["geometry_family"],
                "simulation",
                utcnow(),
            ],
        )
        software = {
            "backend": job["backend"],
            "pathway": job["pathway"],
            "comsol_home": job["environment_snapshot"]["probe"].get("comsol_home"),
            "comsol_version": job["environment_snapshot"]["probe"].get("comsol_version"),
            "comsol_version_source": job["environment_snapshot"]["probe"].get("comsol_version_source"),
            "mphserver_host": job["environment_snapshot"]["probe"].get("mphserver_host"),
            "mphserver_port": job["environment_snapshot"]["probe"].get("mphserver_port"),
            "mphserver_listening_at_submit": job["environment_snapshot"]["probe"].get("mphserver_listening"),
            "matlab_used": False,
            "extractor": java_model.EXTRACTOR_VERSION,
            "captured_at": job["environment_snapshot"]["captured_at"],
        }
        settings = {
            "template": job["template"],
            "template_title": job["template_title"],
            "fidelity": job["fidelity"],
            "timeout_seconds": job["timeout_seconds"],
            "params_si": job["params"],
            "param_units": job["param_units"],
            "solver": "COMSOL 默认 Stationary 求解器（模板未覆写容差）",
            "model_sha256_note": "run.model_sha256 指向**生成的 Java 模型源码**；求解输出 out.mph 的哈希在 artifact 表中。",
            "provenance_gaps_at_submit": [
                "model_sha256/exit_code/wall_seconds/diagnostic 在求解结束前为空（提交时刻尚不存在）。",
            ],
        }
        store_mod.insert_run(
            conn,
            run_id=job["run_id"],
            design_id=job["design_id"],
            backend=job["backend"],
            pathway=job["pathway"],
            model_path=None,
            model_sha256=None,
            software=software,
            settings=settings,
            status="queued",
            run_dir=str(self.run_dir(job["run_id"])),
            started_at=None,
            finished_at=None,
        )

    # ---- 查询 -------------------------------------------------------------------

    def status(self, run_id: str) -> dict[str, Any]:
        """读取一个 run 的状态（读 run 目录，不依赖数据库）。"""
        run_dir = self.run_dir(run_id)
        if not run_dir.is_dir():
            return {"run_id": run_id, "status": "missing", "error": f"run 目录不存在：{run_dir}"}
        status = _json_load(run_dir / "status.json")
        job = _json_load(run_dir / "job.json")
        if status is None:
            return {
                "run_id": run_id,
                "status": "unknown",
                "error": "status.json 缺失或损坏",
                "run_dir": str(run_dir),
            }
        result = _json_load(run_dir / "result.json")
        payload: dict[str, Any] = {
            **status,
            "run_dir": str(run_dir),
            "template": (job or {}).get("template"),
            "params": (job or {}).get("params"),
            "sweep_id": (job or {}).get("sweep_id"),
            "job_present": job is not None,
            "result_present": result is not None,
            "cancel_requested": (run_dir / "cancel.flag").exists(),
        }
        if result:
            payload["outputs"] = result.get("result")
            payload["analytic"] = result.get("analytic")
            payload["comparison"] = result.get("comparison")
            payload["result_error"] = result.get("result_error")
        if payload.get("status") == "queued":
            payload["queue_position"] = self._queue_position(run_id)
        return payload

    def _queue_position(self, run_id: str) -> int | None:
        tickets = sorted(p.name for p in (self.root / "jobs").glob("*.json"))
        target = f"{run_id}.json"
        if target not in tickets:
            return None
        return tickets.index(target) + 1

    def list_jobs(self, limit: int = 50, *, status_in: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        """列出 run（按创建时间倒序）。只扫描本队列产生的运行目录。"""
        rows: list[dict[str, Any]] = []
        if not self.runs_root.is_dir():
            return rows
        for run_dir in self.runs_root.iterdir():
            if not run_dir.is_dir():
                continue
            status = _json_load(run_dir / "status.json")
            if status is None:
                continue
            job = _json_load(run_dir / "job.json") or {}
            if status_in and str(status.get("status")) not in status_in:
                continue
            rows.append(
                {
                    "run_id": run_dir.name,
                    "status": status.get("status"),
                    "created_at": status.get("created_at"),
                    "started_at": status.get("started_at"),
                    "finished_at": status.get("finished_at"),
                    "wall_seconds": status.get("wall_seconds"),
                    "exit_code": status.get("exit_code"),
                    "diagnostic": (status.get("diagnostic") or {}).get("code"),
                    "template": job.get("template"),
                    "params": job.get("params"),
                    "sweep_id": job.get("sweep_id"),
                }
            )
        rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return rows[: max(1, int(limit))]

    # ---- 取消 -------------------------------------------------------------------

    def cancel(self, run_id: str, *, force_kill: bool = True) -> dict[str, Any]:
        """请求取消一个 run。

        - 排队中：立即置为 ``cancelled`` 并撤掉排队票据。
        - 运行中：写 ``cancel.flag``（worker 在阶段之间检查）；若记录了 pid 且
          ``force_kill``，额外尝试终止该进程树（会记录尝试结果，不假装成功）。
        - 已终态：不做任何改动。
        """
        status = _json_load(self.run_dir(run_id) / "status.json")
        if status is None:
            return {"run_id": run_id, "cancelled": False, "reason": "status.json 缺失"}
        current = str(status.get("status"))
        if current in TERMINAL_STATUSES:
            return {"run_id": run_id, "cancelled": False, "reason": f"已在终态 {current}", "status": current}

        (self.run_dir(run_id) / "cancel.flag").write_text(_iso(), encoding="utf-8")
        if current == "queued":
            self._ticket(run_id).unlink(missing_ok=True)
            status = self._set_status(
                run_id,
                status,
                "cancelled",
                finished_at=_iso(),
                notes=list(status.get("notes") or []) + ["提交者在排队阶段取消"],
            )
            return {"run_id": run_id, "cancelled": True, "status": status["status"], "stage": "queued"}

        attempts: list[str] = []
        pid = status.get("pid")
        if force_kill and isinstance(pid, int) and pid > 0:
            attempts = _terminate_pid(pid)
        status = self._set_status(
            run_id,
            status,
            current,
            notes=list(status.get("notes") or [])
            + [f"运行中收到取消请求（terminate attempts={attempts or '未尝试'}）"],
        )
        return {
            "run_id": run_id,
            "cancelled": False,
            "cancel_requested": True,
            "status": current,
            "terminate_attempts": attempts,
            "reason": "任务已在运行；已置取消标志，worker 会在阶段边界中止，并尽力终止子进程。",
        }

    # ---- worker -----------------------------------------------------------------

    def claim_next(self) -> str | None:
        """认领下一个排队任务（原子：重命名票据）。"""
        tickets = sorted((self.root / "jobs").glob("*.json"), key=lambda p: p.name)
        for ticket in tickets:
            run_id = ticket.stem
            claimed = self._ticket(run_id, ".claimed")
            try:
                ticket.replace(claimed)
            except OSError:
                continue
            return run_id
        return None

    def run_job(self, run_id: str, log: Callable[[str], None] | None = None) -> dict[str, Any]:
        """执行一个已认领的 run（由 worker 调用）。"""
        run_dir = self.run_dir(run_id)
        job = _json_load(run_dir / "job.json")
        if job is None:
            status = _json_load(run_dir / "status.json") or {"run_id": run_id, "status": "queued"}
            status = self._set_status(
                run_id,
                status,
                "failed",
                finished_at=_iso(),
                diagnostic=diagnostics.classify_failure("job.json 缺失或损坏", stage="preflight"),
            )
            return status

        logger = _make_logger(run_dir / "worker.log", log)
        status = _json_load(run_dir / "status.json") or {"run_id": run_id, "status": "queued"}
        if (run_dir / "cancel.flag").exists():
            status = self._set_status(
                run_id, status, "cancelled", finished_at=_iso(), notes=["认领时发现取消标志"]
            )
            _json_dump(self._ticket(run_id, ".done"), {"run_id": run_id, "status": "cancelled"})
            return status

        status = self._set_status(
            run_id,
            status,
            "running",
            started_at=_iso(),
            pid=os.getpid(),
            attempts=int(status.get("attempts") or 0) + 1,
        )
        logger(f"[{run_id}] 开始执行 template={job.get('template')} params={job.get('params')}")

        template = java_model.get_template(str(job["template"]))
        params = java_model.validate_values(template, dict(job.get("params") or {}))
        source = template.render(params)
        prepared = PreparedRun(
            run_id=run_id,
            run_dir=run_dir,
            template=template,
            params=params,
            java_source=source,
            timeout_seconds=int(job.get("timeout_seconds") or 3600),
        )

        try:
            outcome = self.backend.execute(prepared, log=logger)
        except Exception as exc:  # 后端自身异常也要落盘，不能静默
            outcome = ExecutionOutcome(
                ok=False,
                exit_code=None,
                wall_seconds=0.0,
                notes=[f"后端抛出异常：{type(exc).__name__}: {exc}"],
            )
            outcome.diagnosis = diagnostics.classify_failure(
                f"{type(exc).__name__}: {exc}", stage="backend_exception"
            )

        backend_mod.dump_commands(run_dir / "commands.json", outcome)
        result_payload = self._write_result(run_id, job, template, params, outcome)
        status = self._finalize(run_id, status, job, template, prepared, outcome, result_payload, logger)
        _json_dump(self._ticket(run_id, ".done"), {"run_id": run_id, "status": status["status"]})
        return status

    def _write_result(
        self,
        run_id: str,
        job: dict[str, Any],
        template: java_model.TemplateSpec,
        params: dict[str, float],
        outcome: ExecutionOutcome,
    ) -> dict[str, Any]:
        """写 result.json：仿真结果 + 解析参考 + 逐输出量的对照。"""
        analytic = template.analytic(params)
        comparison: dict[str, Any] = {}
        sim = outcome.result or {}
        rtol = template.analytic_rtol
        for name in template.outputs:
            sim_value = sim.get(name)
            ref_value = analytic.get(name)
            entry: dict[str, Any] = {
                "analytic": ref_value,
                "simulation": sim_value,
                "tolerance_rtol": rtol,
                "passed": None,
                "reason": None,
            }
            if isinstance(sim_value, (int, float)) and isinstance(ref_value, (int, float)):
                entry["abs_error"] = abs(float(sim_value) - float(ref_value))
                scale = abs(float(ref_value)) if ref_value else 1.0
                entry["rel_error"] = abs(float(sim_value) - float(ref_value)) / scale
                entry["passed"] = bool(entry["rel_error"] <= rtol)
            else:
                entry["reason"] = "仿真值或解析值缺失（见 run 日志）"
            comparison[name] = entry
        payload = {
            "run_id": run_id,
            "template": template.name,
            "params_si": params,
            "result": outcome.result,
            "result_error": outcome.result_error,
            "analytic": analytic,
            "comparison": comparison,
            "diagnosis": outcome.diagnosis,
            "extractor": java_model.EXTRACTOR_VERSION,
            "outcome_ok": outcome.ok,
            "notes": outcome.notes,
        }
        _json_dump(self.run_dir(run_id) / "result.json", payload)
        return payload

    def _finalize(
        self,
        run_id: str,
        status: dict[str, Any],
        job: dict[str, Any],
        template: java_model.TemplateSpec,
        prepared: PreparedRun,
        outcome: ExecutionOutcome,
        result_payload: dict[str, Any],
        logger: Callable[[str], None],
    ) -> dict[str, Any]:
        run_dir = self.run_dir(run_id)
        cancelled = (run_dir / "cancel.flag").exists()
        if cancelled and outcome.ok:
            final = "succeeded"
            note = "取消请求在求解完成后才被检查到：保留已成功的结果并如实标注。"
        elif outcome.ok:
            final = "succeeded"
            note = None
        elif cancelled:
            final = "cancelled"
            note = "求解未完成，且收到取消请求。"
        else:
            final = "failed"
            note = None

        extra_notes = [log for log in (note,) if log]
        status = self._set_status(
            run_id,
            status,
            final,
            finished_at=_iso(),
            exit_code=outcome.exit_code,
            wall_seconds=round(float(outcome.wall_seconds), 3),
            diagnostic=outcome.diagnosis,
            notes=list(status.get("notes") or []) + list(outcome.notes) + extra_notes,
        )
        logger(f"[{run_id}] 结束 status={final} exit_code={outcome.exit_code} wall={outcome.wall_seconds:.1f}s")

        # 收尾事实落盘成 db_record.json：这样即使 worker 进程没有数据库连接
        # （DuckDB 单写者，DB 写入集中在调用方进程），后续 ingest 也能原样补写 run 行。
        record = self._build_db_record(job, template, outcome, status)
        _json_dump(run_dir / "db_record.json", record)
        if self.conn is not None:
            self._apply_db_record(self.conn, record)
        return status

    def _build_db_record(
        self,
        job: dict[str, Any],
        template: java_model.TemplateSpec,
        outcome: ExecutionOutcome,
        status: dict[str, Any],
    ) -> dict[str, Any]:
        """构造要写回 ``run`` 表生命周期字段的载荷（不改写任何历史样本）。"""
        run_id = job["run_id"]
        run_dir = self.run_dir(run_id)
        java_path = run_dir / f"{template.java_class}.java"
        facts = (outcome.result or {}).get("batchlog_facts") or {}
        probe = ((job.get("environment_snapshot") or {}).get("probe") or {})
        settings = {
            "template": template.name,
            "template_title": template.title,
            "physics": template.physics,
            "study": template.study,
            "fidelity": template.fidelity,
            "geometry_family": template.geometry_family,
            "params_si": job["params"],
            "param_units": job["param_units"],
            "mesh": {
                "hmax_mesh_m": job["params"].get("hmax_mesh"),
                "type": "FreeTri（自由三角形）",
                "elements": facts.get("elements"),
            },
            "boundary_numbers": template.boundary_numbers,
            "boundary_selection_verified_in_gui": False,
            "boundary_selection_note": (
                "无人值守批处理，未在图形窗口核对选择集；正确性由解析解交叉验证"
                "（见 result.json.comparison 与样本 quality.l0_analytic_check）。"
            ),
            "solver": "COMSOL 默认 Stationary 求解器（模板未覆写容差/线性求解器）",
            "timeout_seconds": job["timeout_seconds"],
            "model_sha256_note": (
                "model_sha256 = 生成的 Java 模型源码哈希（编译输入）；out.mph 哈希见 artifact 表。"
            ),
            "matlab_used": False,
            "provenance_gaps": [
                gap
                for gap in (
                    "网格单元数未能从日志读到" if facts.get("elements") is None else None,
                    "求解器容差/线性求解器未覆写，沿用 COMSOL 默认值（未从日志读取具体数值）",
                )
                if gap
            ],
        }
        software = {
            # 先把提交时刻的环境快照写进去（保证 COMSOL 版本/端口一定有记录，
            # 不依赖后端是否回报），再用后端求解时实测到的值覆盖（更权威）。
            "backend": job.get("backend"),
            "pathway": job.get("pathway"),
            "comsol_home": probe.get("comsol_home"),
            "comsol_version": probe.get("comsol_version"),
            "comsol_version_source": probe.get("comsol_version_source"),
            "mphserver_host": probe.get("mphserver_host"),
            "mphserver_port": probe.get("mphserver_port"),
            "mphserver_listening_at_submit": probe.get("mphserver_listening"),
            "matlab_used": False,
            "extractor": java_model.EXTRACTOR_VERSION,
            "env_snapshot_captured_at": (job.get("environment_snapshot") or {}).get("captured_at"),
            **dict(outcome.software),
        }
        software["status_at_finalize"] = status.get("status")
        started_at = status.get("started_at")
        return {
            "run_id": run_id,
            "status": status.get("status"),
            "exit_code": status.get("exit_code"),
            "diagnostic": status.get("diagnostic"),
            "wall_seconds": status.get("wall_seconds"),
            "started_at": started_at,
            "model_path": str(java_path),
            "model_sha256": sha256_file(java_path),
            "software": software,
            "settings": settings,
            "finished_at": utcnow().isoformat(timespec="seconds"),
        }

    @staticmethod
    def _apply_db_record(conn: Any, record: dict[str, Any]) -> None:
        started = record.get("started_at")
        started_dt = None
        if isinstance(started, str):
            try:
                started_dt = datetime.fromisoformat(started)
            except ValueError:
                started_dt = None
        finished = record.get("finished_at")
        finished_dt = None
        if isinstance(finished, str):
            try:
                finished_dt = datetime.fromisoformat(finished)
            except ValueError:
                finished_dt = None
        conn.execute(
            "UPDATE run SET status=?, exit_code=?, diagnostic=?, wall_seconds=?, model_path=?, "
            "model_sha256=?, software=?, settings=?, started_at=?, finished_at=? WHERE run_id=?",
            [
                record.get("status"),
                record.get("exit_code"),
                json.dumps(record.get("diagnostic"), ensure_ascii=False)
                if record.get("diagnostic")
                else None,
                record.get("wall_seconds"),
                record.get("model_path"),
                record.get("model_sha256"),
                json.dumps(record.get("software"), ensure_ascii=False),
                json.dumps(record.get("settings"), ensure_ascii=False),
                started_dt,
                finished_dt,
                record["run_id"],
            ],
        )

    def drain(
        self,
        max_jobs: int | None = None,
        log: Callable[[str], None] | None = None,
        *,
        lock_timeout: float = 0.0,
    ) -> list[dict[str, Any]]:
        """在持有单实例锁的前提下，串行执行队列中的任务。"""
        lock = FileLock(self.lock_path)
        if not lock.acquire(blocking=lock_timeout > 0, timeout=lock_timeout or None):
            raise RuntimeError(
                f"已有 COMSOL 执行 worker 持有锁：{self.lock_path}。"
                "本平台严格单实例串行（license/内存约束），请等待其结束。"
            )
        processed: list[dict[str, Any]] = []
        try:
            self._write_worker_status("running")
            while True:
                if max_jobs is not None and len(processed) >= max_jobs:
                    break
                run_id = self.claim_next()
                if run_id is None:
                    break
                processed.append(self.run_job(run_id, log=log))
                self._write_worker_status("running", processed[-1])
        finally:
            self._write_worker_status("stopped", processed[-1] if processed else None)
            lock.release()
        return processed

    def _write_worker_status(self, state: str, last: dict[str, Any] | None = None) -> None:
        _json_dump(
            self.root / "worker_status.json",
            {
                "state": state,
                "pid": os.getpid(),
                "updated_at": _iso(),
                "queue_depth": len(list((self.root / "jobs").glob("*.json"))),
                "last_run_id": (last or {}).get("run_id"),
                "last_status": (last or {}).get("status"),
            },
        )

    def worker_locked(self) -> bool:
        """探测是否已有 worker 持锁（只读探测，不抢占）。"""
        lock = FileLock(self.lock_path)
        if lock.acquire():
            lock.release()
            return False
        return True


def _make_logger(path: Path, echo: Callable[[str], None] | None) -> Callable[[str], None]:
    path.parent.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        line = f"{_iso()} {message}"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        if echo:
            echo(line)

    return log


def _artifact_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".mph":
        return "mph"
    if suffix in (".log", ".txt"):
        return "log"
    if suffix == ".json":
        return "json"
    if suffix in (".java", ".class"):
        return "model_source"
    return "other"


def _terminate_pid(pid: int) -> list[str]:
    """尽力终止进程（返回尝试过的动作，供审计）。不假装成功。"""
    attempts: list[str] = []
    if os.name == "nt":  # pragma: no cover - 需要真实进程
        try:
            proc = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            attempts.append(f"taskkill /F /T /PID {pid} -> rc={proc.returncode}")
        except Exception as exc:  # pragma: no cover
            attempts.append(f"taskkill 失败：{type(exc).__name__}: {exc}")
    else:  # pragma: no cover
        import signal

        try:
            os.kill(pid, signal.SIGTERM)
            attempts.append(f"os.kill({pid}, SIGTERM)")
        except Exception as exc:  # pragma: no cover
            attempts.append(f"os.kill 失败：{exc}")
    return attempts


# --------------------------------------------------------------------------------------
# 入库（sample / artifact / design）
# --------------------------------------------------------------------------------------


def ingest_run(
    conn: Any,
    queue: JobQueue,
    run_id: str,
    *,
    extra_quality: dict[str, Any] | None = None,
    include_analytic_sample: bool = True,
    include_failed_sample: bool = True,
    write_samples: bool = True,
) -> dict[str, Any]:
    """把一个已结束的 run 写成 ``sample``（+ 可选 ``analytic`` 对照样本）。

    溯源要求（红线 1/4/6 + dataset-contract）：
    - ``source_type="simulation"`` 的样本必须带 run_id / design_id / fidelity / inputs / outputs / extractor；
    - 解析值单独成条（``source_type="analytic"``），绝不与仿真值合并；
    - 缺失的输出量写 ``null`` 并在 ``quality`` 里写明原因，不用 0 顶替；
    - 失败点作为**负样本**入库，带 run.diagnostic 分类。
    """
    job = _json_load(queue.run_dir(run_id) / "job.json")
    if job is None:
        return {"run_id": run_id, "error": "job.json 缺失，无法入库"}
    result = _json_load(queue.run_dir(run_id) / "result.json") or {}
    status = _json_load(queue.run_dir(run_id) / "status.json") or {}
    template = java_model.get_template(str(job["template"]))
    params = dict(job.get("params") or {})
    units = dict(job.get("param_units") or {})
    state = str(status.get("status"))
    # append-only：同一 run 已入库则不再重复插入（修正应新增记录，而不是重写）
    prior = store_mod.query(conn, "SELECT sample_id FROM sample WHERE run_id = ?", [run_id], limit=50)
    if prior:
        return {
            "run_id": run_id,
            "status": state,
            "sample_ids": [row["sample_id"] for row in prior],
            "already_ingested": True,
            "note": "该 run 已有样本入库；append-only，不重复插入（红线 6）。",
        }
    comparison = dict(result.get("comparison") or {})
    sim_result = dict(result.get("result") or {})
    analytic = dict(result.get("analytic") or {})
    design_id = job.get("design_id")
    inputs = {name: params.get(name) for name in sorted(params)}
    input_units = {name: units.get(name) for name in sorted(params)}

    l0 = {
        "passed": all(bool(entry.get("passed")) for entry in comparison.values()) if comparison else None,
        "detail": comparison,
        "reference": "闭式解 T_max = T0 + q_in*Lx/k（见 java_model.py 模板说明）",
        "tolerance_rtol": next(
            (entry.get("tolerance_rtol") for entry in comparison.values()), None
        ),
    }
    quality: dict[str, Any] = {
        "l0_analytic_check": l0,
        "l1_mesh_convergence": (extra_quality or {}).get("l1_mesh_convergence"),
        "l2_conservation": None,
        "l2_conservation_reason": "本模板为线性稳态导热，尚未做通量守恒积分检查（未实现）。",
        "source_units_preserved": input_units,
        "si_normalized": True,
        "unit_check": (extra_quality or {}).get("unit_check"),
        "negative_sample": state != "succeeded",
        "diagnostic_code": (status.get("diagnostic") or {}).get("code"),
        "notes": list(extra_quality.get("notes") if extra_quality else []),
    }

    inserted: list[str] = []
    if write_samples and state == "succeeded":
        outputs = {
            "T_max_K": sim_result.get("T_max_K"),
            "T_min_K": sim_result.get("T_min_K"),
        }
        uncertainty = {
            "T_max_K": {
                "unit": "K",
                "components": {
                    "numerical_discretization": {
                        "value": (extra_quality or {}).get("l1_max_abs_diff_K"),
                        "source": "L1 网格收敛检查（3 组网格）",
                        "reason": None
                        if (extra_quality or {}).get("l1_max_abs_diff_K") is not None
                        else "本批扫描未附带网格收敛结果，离散误差未量化",
                    },
                    "model_form": {
                        "value": None,
                        "reason": "模板是线性一维精确解的同构离散化，model-form 误差未独立量化（不写 0 冒充已知）",
                    },
                    "parameter": {
                        "value": None,
                        "reason": "本批为数值实验，未对 k/T0/几何公差做抽样传播",
                    },
                },
                "type": "numeric_experiment",
            }
        }
        sample_id = f"smpl-{run_id}-sim"
        store_mod.insert_sample(
            conn,
            sample_id=sample_id,
            run_id=run_id,
            design_id=design_id,
            fidelity=template.fidelity,
            source_type="simulation",
            inputs=inputs,
            outputs=outputs,
            uncertainty=uncertainty,
            extractor=java_model.EXTRACTOR_VERSION,
            quality=quality,
        )
        inserted.append(sample_id)

        if include_analytic_sample:
            analytic_sample_id = f"smpl-{run_id}-analytic"
            store_mod.insert_sample(
                conn,
                sample_id=analytic_sample_id,
                run_id=run_id,
                design_id=design_id,
                fidelity="F0",
                source_type="analytic",
                inputs=inputs,
                outputs={"T_max_K": analytic.get("T_max_K"), "T_min_K": analytic.get("T_min_K")},
                uncertainty={
                    "T_max_K": {
                        "unit": "K",
                        "components": {
                            "model_form": {
                                "value": None,
                                "reason": "闭式解本身无离散误差；其适用前提（一维线性、均匀 k、绝热侧边）已在模板中声明",
                            }
                        },
                        "type": "closed_form_reference",
                    }
                },
                extractor="memsharness.comsol.java_model:analytic_reference@0.1.0",
                quality={
                    "role": "cross_check_reference",
                    "paired_simulation_sample_id": sample_id,
                    "relative_deviation": {
                        name: entry.get("rel_error") for name, entry in comparison.items()
                    },
                    "within_tolerance": l0["passed"],
                },
            )
            inserted.append(analytic_sample_id)
    elif write_samples and include_failed_sample and state in ("failed", "cancelled"):
        # 负样本：输出显式写 null，并注明缺失原因；不得用 0 顶替
        sample_id = f"smpl-{run_id}-failed"
        store_mod.insert_sample(
            conn,
            sample_id=sample_id,
            run_id=run_id,
            design_id=design_id,
            fidelity=template.fidelity,
            source_type="simulation",
            inputs=inputs,
            outputs={name: None for name in template.outputs},
            uncertainty=None,
            extractor=java_model.EXTRACTOR_VERSION,
            quality={
                **quality,
                "negative_sample": True,
                "missing_reason": f"求解未成功（status={state}，diagnostic={(status.get('diagnostic') or {}).get('code')}），因此无输出值",
            },
        )
        inserted.append(sample_id)

    artifacts = _record_run_artifacts(conn, run_id, queue.run_dir(run_id))
    # 收尾事实（软件版本/耗时/退出码/哈希/设置）由 worker 写进 db_record.json，这里补写 run 行；
    # 若 worker 进程已经写过（同进程队列），UPDATE 是幂等的，不会产生重复记录。
    record = _json_load(queue.run_dir(run_id) / "db_record.json")
    if record:
        JobQueue._apply_db_record(conn, record)
    return {
        "run_id": run_id,
        "status": state,
        "sample_ids": inserted,
        "design_id": design_id,
        "artifact_rows": artifacts,
        "l0_passed": l0["passed"],
        "wall_seconds": status.get("wall_seconds"),
        "exit_code": status.get("exit_code"),
        "diagnostic": (status.get("diagnostic") or {}).get("code"),
    }


def _record_run_artifacts(conn: Any, run_id: str, run_dir: Path) -> int:
    """为 run 目录下所有实际存在的文件建 artifact 记录（幂等：已记录则跳过）。"""
    existing = int(
        conn.execute("SELECT count(*) FROM artifact WHERE run_id = ?", [run_id]).fetchone()[0]
    )
    if existing:
        return existing
    count = 0
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.suffix == ".tmp":
            continue
        rel = path.relative_to(run_dir).as_posix().replace("/", "__")
        conn.execute(
            "INSERT INTO artifact (artifact_id, run_id, kind, sha256, path, bytes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                f"art-{run_id}-{rel}",
                run_id,
                _artifact_kind(path),
                sha256_file(path),
                str(path),
                path.stat().st_size,
                utcnow(),
            ],
        )
        count += 1
    return count


# --------------------------------------------------------------------------------------
# CLI：worker
# --------------------------------------------------------------------------------------


def worker_main(argv: list[str] | None = None) -> int:
    """``python -m memsharness.comsol.queue`` —— 单实例 worker 入口。"""
    parser = argparse.ArgumentParser(description="COMSOL 文件队列 worker（单实例串行）")
    parser.add_argument("--queue-root", default=None, help="队列根目录（默认 work/queue）")
    parser.add_argument("--runs-root", default=None, help="run 目录根（默认 work/runs）")
    parser.add_argument("--max-jobs", type=int, default=None, help="最多处理多少个任务后退出")
    parser.add_argument("--once", action="store_true", help="只处理一个任务")
    parser.add_argument(
        "--wait-lock",
        type=float,
        default=0.0,
        help="等待锁的秒数（默认 0：拿不到锁立即失败退出，避免并发求解）",
    )
    parser.add_argument("--json", action="store_true", help="把每个任务的结果以 JSON 行打印")
    args = parser.parse_args(argv)

    queue = JobQueue(root=args.queue_root, runs_root=args.runs_root)
    max_jobs = 1 if args.once else args.max_jobs
    echo = (lambda line: print(line, flush=True)) if not args.json else None
    try:
        results = queue.drain(max_jobs=max_jobs, log=echo, lock_timeout=args.wait_lock)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 3
    for item in results:
        payload = {
            "run_id": item.get("run_id"),
            "status": item.get("status"),
            "exit_code": item.get("exit_code"),
            "wall_seconds": item.get("wall_seconds"),
            "diagnostic": (item.get("diagnostic") or {}).get("code"),
        }
        print(json.dumps(payload, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(worker_main())
