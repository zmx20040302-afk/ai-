"""执行后端抽象：``ExecutionBackend`` 协议与 ``local`` 实现。

设计意图（WORKING_PLAN 第 3 节 / 决策点 D4）：
本机（local）与将来的可借用服务器/集群（remote）在**接口层面等价**，
P0–P2 只实现 ``local``；``remote`` 只留 seam，不实现，调用即报
``NotImplementedError`` 并说明需要补什么。

``local`` 后端走的是「Java API + comsolcompile + comsolbatch」这条**不依赖 MATLAB** 的通路：
1. 把 run 目录下生成的 ``<class>.java`` 编译为 ``<class>.class``（comsolcompile.exe）
2. 用 comsolbatch.exe 求解 ``<class>.class``，输出 ``out.mph``
3. 从 stdout 日志里解析 ``MEMS_RESULT_JSON=`` 标记得到标量结果

所有命令的实际 argv、退出码、墙钟时间、日志路径都会回传到 ``ExecutionOutcome``，
由调用方写进 run 目录的 ``commands.json``（可复现单元的一部分）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from .. import env as env_mod
from . import diagnostics
from .java_model import (
    EXTRACTOR_VERSION,
    TemplateSpec,
    parse_batchlog_facts,
    parse_result_marker,
)

__all__ = [
    "BackendError",
    "ExecutionOutcome",
    "PreparedRun",
    "ExecutionBackend",
    "LocalComsolBackend",
    "RemoteBackend",
    "BACKENDS",
    "get_backend",
]


class BackendError(RuntimeError):
    """后端不可用（缺可执行文件、路径不存在等），区别于「求解失败」。"""


# --------------------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------------------


@dataclass
class PreparedRun:
    """一次已准备好、可交给后端执行的工作单元。"""

    run_id: str
    run_dir: Path
    template: TemplateSpec
    params: dict[str, float]
    java_source: str
    timeout_seconds: int = 3600

    @property
    def java_class(self) -> str:
        return self.template.java_class

    @property
    def java_path(self) -> Path:
        return self.run_dir / f"{self.java_class}.java"


@dataclass
class ExecutionOutcome:
    """一次执行的完整事实（不去猜、不补默认值）。"""

    ok: bool
    exit_code: int | None
    wall_seconds: float
    commands: list[dict[str, Any]] = field(default_factory=list)
    log_paths: dict[str, str] = field(default_factory=dict)
    artifacts: list[Path] = field(default_factory=list)
    result: dict[str, Any] | None = None
    result_error: str | None = None
    diagnosis: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)
    software: dict[str, Any] = field(default_factory=dict)
    log_tail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "exit_code": self.exit_code,
            "wall_seconds": self.wall_seconds,
            "commands": self.commands,
            "log_paths": self.log_paths,
            "artifacts": [str(p) for p in self.artifacts],
            "result": self.result,
            "result_error": self.result_error,
            "diagnosis": self.diagnosis,
            "notes": self.notes,
            "software": self.software,
        }


# --------------------------------------------------------------------------------------
# 协议
# --------------------------------------------------------------------------------------


@runtime_checkable
class ExecutionBackend(Protocol):
    """执行后端协议（local 已实现；remote 见 ``RemoteBackend`` 存根）。

    约定：
    - ``probe()`` 只做**只读**探测，不启动任何长驻进程，不检出许可证。
    - ``execute()`` 必须在 ``prepared.run_dir`` 内产生全部输入/日志/产物，
      并保证同一时刻只有一个后端实例在真正求解（由队列层的文件锁保证）。
    """

    name: str

    def capabilities(self) -> dict[str, Any]:
        """本后端能做什么、不能做什么（供 MCP/报告说明）。"""

    def probe(self) -> dict[str, Any]:
        """只读环境探测。"""

    def execute(
        self,
        prepared: PreparedRun,
        log: Callable[[str], None] | None = None,
    ) -> ExecutionOutcome:
        """执行一次求解。"""


# --------------------------------------------------------------------------------------
# local 后端
# --------------------------------------------------------------------------------------


def _decode(data: bytes) -> str:
    """按 UTF-8 → GBK → latin-1 顺序解码 COMSOL 输出（中文 Windows 控制台常见 GBK）。"""
    for encoding in ("utf-8", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def tail(text: str, lines: int = 40) -> str:
    parts = (text or "").splitlines()
    return "\n".join(parts[-lines:])


class LocalComsolBackend:
    """本机 COMSOL 批处理后端（Java API + comsolcompile + comsolbatch）。"""

    name = "local"

    def __init__(
        self,
        comsol_home: str | Path | None = None,
        *,
        comsolbatch: str | Path | None = None,
        comsolcompile: str | Path | None = None,
        keep_class_files: bool = True,
    ) -> None:
        self.comsol_home = Path(comsol_home or env_mod.DEFAULT_COMSOL_HOME)
        self.bin_dir = self.comsol_home / "bin" / "win64"
        self.comsolbatch = Path(comsolbatch) if comsolbatch else self.bin_dir / "comsolbatch.exe"
        self.comsolcompile = (
            Path(comsolcompile) if comsolcompile else self.bin_dir / "comsolcompile.exe"
        )
        self.keep_class_files = keep_class_files

    # ---- 能力与探测 -------------------------------------------------------------

    def capabilities(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "pathway": "comsolbatch",
            "requires_matlab": False,
            "parallel_solving": False,
            "notes": [
                "单实例串行；并发由队列层的文件锁保证。",
                "输入为生成的 Java 模型类（.class），输出 out.mph + result.json。",
                "remote 后端未实现（见 WORKING_PLAN 决策点 D4）。",
            ],
        }

    def probe(self) -> dict[str, Any]:
        """只读探测：可执行文件是否存在、版本、mphserver 端口。不启动进程。"""
        batch_ok = self.comsolbatch.is_file()
        compile_ok = self.comsolcompile.is_file()
        version = env_mod.pe_file_version(self.comsolbatch) if batch_ok else None
        listening = env_mod.tcp_probe("127.0.0.1", env_mod.DEFAULT_MPH_PORT)
        return {
            "backend": self.name,
            "comsol_home": str(self.comsol_home),
            "comsol_home_exists": self.comsol_home.is_dir(),
            "comsolbatch": str(self.comsolbatch),
            "comsolbatch_exists": batch_ok,
            "comsolcompile": str(self.comsolcompile),
            "comsolcompile_exists": compile_ok,
            "comsol_version": version,
            "comsol_version_source": (
                "PE FileVersion of comsolbatch.exe" if version else "读不到（可执行文件缺失或 PowerShell 取版本失败）"
            ),
            "mphserver_host": "127.0.0.1",
            "mphserver_port": env_mod.DEFAULT_MPH_PORT,
            "mphserver_listening": listening,
            "ready": batch_ok and compile_ok,
        }

    # ---- 运行 -------------------------------------------------------------------

    def _run_command(
        self,
        argv: list[str],
        *,
        cwd: Path,
        timeout: int,
        stdout_path: Path,
        stderr_path: Path,
        log: Callable[[str], None] | None,
    ) -> tuple[int | None, float, str, str, bool]:
        """执行外部命令，落盘 stdout/stderr，返回 (退出码, 墙钟秒, stdout文本, stderr文本, 是否超时)。"""
        if log:
            log(f"$ {' '.join(argv)}  (cwd={cwd})")
        started = time.monotonic()
        timed_out = False
        out_bytes = b""
        err_bytes = b""
        returncode: int | None
        # 继承父环境（COMSOL 依赖 PATH/LM_LICENSE_FILE 等）；不额外注入 JVM 参数，
        # 以免 JVM 在 stderr 打 "Picked up ..." 之类的噪声行干扰日志判读。
        env = dict(os.environ)
        try:
            with stdout_path.open("wb") as out_handle, stderr_path.open("wb") as err_handle:
                proc = subprocess.Popen(
                    argv,
                    cwd=str(cwd),
                    stdout=out_handle,
                    stderr=err_handle,
                    env=env,
                )
                try:
                    returncode = proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    proc.kill()
                    try:
                        proc.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        pass
                    returncode = None
        except OSError as exc:
            wall = time.monotonic() - started
            stdout_path.write_bytes(b"")
            stderr_path.write_bytes(f"{type(exc).__name__}: {exc}".encode("utf-8"))
            return None, wall, "", f"{type(exc).__name__}: {exc}", False
        wall = time.monotonic() - started
        out_bytes = stdout_path.read_bytes() if stdout_path.exists() else b""
        err_bytes = stderr_path.read_bytes() if stderr_path.exists() else b""
        return returncode, wall, _decode(out_bytes), _decode(err_bytes), timed_out

    def execute(
        self,
        prepared: PreparedRun,
        log: Callable[[str], None] | None = None,
    ) -> ExecutionOutcome:
        run_dir = prepared.run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        probe = self.probe()
        software = {
            "backend": self.name,
            "pathway": "comsolbatch",
            "comsol_home": probe["comsol_home"],
            "comsol_version": probe["comsol_version"],
            "comsol_version_source": probe["comsol_version_source"],
            "comsolbatch_path": probe["comsolbatch"],
            "comsolcompile_path": probe["comsolcompile"],
            "mphserver_host": probe["mphserver_host"],
            "mphserver_port": probe["mphserver_port"],
            "mphserver_listening_at_run_start": probe["mphserver_listening"],
            "matlab_used": False,
            "extractor": EXTRACTOR_VERSION,
        }
        if not probe["ready"]:
            outcome = ExecutionOutcome(
                ok=False,
                exit_code=None,
                wall_seconds=0.0,
                software=software,
                notes=["comsolbatch/comsolcompile 缺失，未执行任何命令。"],
            )
            outcome.diagnosis = diagnostics.classify_failure(
                f"comsolbatch_exists={probe['comsolbatch_exists']} "
                f"comsolcompile_exists={probe['comsolcompile_exists']}",
                exit_code=None,
                stage="preflight",
            )
            return outcome

        commands: list[dict[str, Any]] = []
        log_paths: dict[str, str] = {}
        notes: list[str] = []
        started = time.monotonic()

        # 1) 写 Java 源码
        java_path = prepared.java_path
        java_path.write_text(prepared.java_source, encoding="ascii", newline="\n")

        # 2) 编译
        compile_out = run_dir / "compile.stdout.log"
        compile_err = run_dir / "compile.stderr.log"
        compile_argv = [str(self.comsolcompile), java_path.name]
        rc, wall, c_out, c_err, timed = self._run_command(
            compile_argv,
            cwd=run_dir,
            timeout=min(900, prepared.timeout_seconds),
            stdout_path=compile_out,
            stderr_path=compile_err,
            log=log,
        )
        commands.append(
            {
                "stage": "compile",
                "argv": compile_argv,
                "cwd": str(run_dir),
                "returncode": rc,
                "wall_seconds": wall,
                "timed_out": timed,
                "stdout": compile_out.name,
                "stderr": compile_err.name,
            }
        )
        log_paths["compile.stdout"] = str(compile_out)
        log_paths["compile.stderr"] = str(compile_err)

        class_path = run_dir / f"{prepared.java_class}.class"
        if timed:
            outcome = ExecutionOutcome(
                ok=False,
                exit_code=rc,
                wall_seconds=wall,
                commands=commands,
                log_paths=log_paths,
                software=software,
                log_tail=tail(c_out + "\n" + c_err),
                notes=["编译阶段超时。"],
            )
            outcome.diagnosis = diagnostics.classify_failure(
                c_out + "\n" + c_err, exit_code=rc, stage="timeout"
            )
            return outcome
        if rc != 0 or not class_path.exists():
            # 编译失败的 class 目录可能残留在子目录里，记录下来方便排查
            stray = sorted(str(p) for p in run_dir.rglob("*.class"))
            outcome = ExecutionOutcome(
                ok=False,
                exit_code=rc,
                wall_seconds=wall,
                commands=commands,
                log_paths=log_paths,
                software=software,
                log_tail=tail(c_out + "\n" + c_err),
                notes=[f"编译未产出 {class_path.name}；发现 class 文件：{stray}"],
            )
            outcome.diagnosis = diagnostics.classify_failure(
                c_out + "\n" + c_err, exit_code=rc, stage="compile"
            )
            return outcome
        log(f"编译完成：{class_path.name} ({class_path.stat().st_size} bytes)")

        # 3) 求解
        batch_out = run_dir / "batch.stdout.log"
        batch_err = run_dir / "batch.stderr.log"
        batchlog = run_dir / "batchlog.txt"
        batch_argv = [
            str(self.comsolbatch),
            "-inputfile",
            class_path.name,
            "-outputfile",
            "out.mph",
            "-batchlog",
            batchlog.name,
            "-stoptime",
            str(int(prepared.timeout_seconds)),
        ]
        rc, wall, b_out, b_err, timed = self._run_command(
            batch_argv,
            cwd=run_dir,
            timeout=prepared.timeout_seconds,
            stdout_path=batch_out,
            stderr_path=batch_err,
            log=log,
        )
        commands.append(
            {
                "stage": "batch",
                "argv": batch_argv,
                "cwd": str(run_dir),
                "returncode": rc,
                "wall_seconds": wall,
                "timed_out": timed,
                "stdout": batch_out.name,
                "stderr": batch_err.name,
            }
        )
        log_paths["batch.stdout"] = str(batch_out)
        log_paths["batch.stderr"] = str(batch_err)
        log_paths["batchlog"] = str(batchlog)

        combined = "\n".join(
            part
            for part in (
                b_out,
                b_err,
                batchlog.read_text(encoding="utf-8", errors="replace") if batchlog.exists() else "",
            )
            if part
        )
        facts = parse_batchlog_facts(combined)
        out_mph = run_dir / "out.mph"

        artifacts: list[Path] = [java_path, class_path] if self.keep_class_files else [java_path]
        for extra in (out_mph, compile_out, compile_err, batch_out, batch_err, batchlog):
            if extra.exists():
                artifacts.append(extra)

        result, result_error = parse_result_marker(b_out + "\n" + combined)
        if result is not None:
            result["batchlog_facts"] = facts

        ok = rc == 0 and out_mph.exists() and result is not None and not timed
        notes.append(f"总墙钟（compile+batch）：{time.monotonic() - started:.1f} s")
        if not out_mph.exists():
            notes.append("未生成 out.mph")
        if timed:
            notes.append(
                f"batch 阶段在 {prepared.timeout_seconds} s 时限内未结束，已终止进程。"
            )

        outcome = ExecutionOutcome(
            ok=ok,
            exit_code=rc,
            wall_seconds=time.monotonic() - started,
            commands=commands,
            log_paths=log_paths,
            artifacts=artifacts,
            result=result,
            result_error=result_error,
            software=software,
            notes=notes,
            log_tail=tail(combined),
        )
        if not ok:
            failure_text = combined if combined.strip() else f"exit_code={rc}"
            outcome.diagnosis = diagnostics.classify_failure(
                failure_text,
                exit_code=rc,
                stage="timeout" if timed else "batch",
            )
        return outcome


# --------------------------------------------------------------------------------------
# remote 后端：只留接口，不实现（用户明确要求）
# --------------------------------------------------------------------------------------


class RemoteBackend:
    """将来「借用服务器/集群」的执行后端**存根**（本阶段不实现）。

    实现它需要补齐的东西（在实现前不得宣称支持远程执行）：
    1. 远端 COMSOL 安装与许可证的可用性探测（版本、可用模块、并发上限）
    2. 远程文件同步（模型/输入上传 + 产物/日志回收，需内容寻址与校验）
    3. 远端单实例锁与排队语义（本机队列必须知道远端是否已满载）
    4. 失败回传与本地诊断分类的对齐（远端日志格式可能不同）
    5. 安全与凭据管理（不在本仓库存明文口令）
    """

    name = "remote"

    def __init__(self, *_: Any, **__: Any) -> None:
        raise NotImplementedError(
            "remote 后端尚未实现：P0–P2 只提供 local 后端（WORKING_PLAN 决策点 D4）。"
            "需要 remote 时请先补齐远端探测、文件同步、远端锁与凭据管理。"
        )


BACKENDS: dict[str, type] = {
    "local": LocalComsolBackend,
    # "remote": RemoteBackend,  # 故意不注册：未实现的后端不得被误选
}


def get_backend(name: str = "local", **kwargs: Any) -> ExecutionBackend:
    """按名字取执行后端；未实现的后端会明确报错，而不是静默回退到 local。"""
    if name == "remote":
        raise NotImplementedError(
            "backend='remote' 未实现（P0–P2 只实现 local，见 WORKING_PLAN 决策点 D4）。"
            "不要静默回退到 local，以免把本机结果当成集群结果。"
        )
    if name not in BACKENDS:
        raise ValueError(f"未知后端 {name!r}；可用：{sorted(BACKENDS)}")
    return BACKENDS[name](**kwargs)  # type: ignore[return-value]


def dump_commands(path: Path, outcome: ExecutionOutcome) -> Path:
    """把命令与退出码写成可审计的 JSON（append-only 语义：每次执行覆盖本 run 的记录）。"""
    payload = {
        "commands": outcome.commands,
        "wall_seconds": outcome.wall_seconds,
        "exit_code": outcome.exit_code,
        "ok": outcome.ok,
        "notes": outcome.notes,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def sha256_file(path: Path) -> str | None:
    """文件 sha256；文件不存在返回 None（不编造哈希）。"""
    if not path.exists() or not path.is_file():
        return None
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_comsol_home() -> Path | None:
    """从 PATH 或默认位置猜测 COMSOL 安装目录（读不到返回 None）。"""
    for candidate in (env_mod.DEFAULT_COMSOL_HOME,):
        if Path(candidate).is_dir():
            return Path(candidate)
    which = shutil.which("comsolbatch")
    if which:
        return Path(which).resolve().parents[2]
    return None
