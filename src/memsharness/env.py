"""环境探测：COMSOL / MATLAB / LiveLink / mphserver / 授权的只读事实快照。

设计原则（AGENTS.md 红线 3）：只报告能实测到的事实，不猜测。
- 可执行文件存在性、文件版本号、授权文件存在性、端口可连接性：**实测**
- 模块「文档存在」只是文档层事实，**不等于授权包含**，必须标为待求解确认

命令行用法：
    python -m memsharness.env            # 打印摘要并写入 work/reports/env_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .paths import ensure_work_tree, work_root

# ---- 默认值（可用环境变量或参数覆盖）------------------------------------------
DEFAULT_COMSOL_HOME = os.environ.get("MEMS_COMSOL_HOME", r"D:\COMSOL64\Multiphysics")
DEFAULT_MATLAB_EXE = os.environ.get("MEMS_MATLAB_EXE", r"D:\MATLAB2025\bin\matlab.exe")
DEFAULT_MPH_PORT = int(os.environ.get("MEMS_MPH_PORT", "2036"))

EXPECTED_EXES = (
    "comsol.exe",
    "comsolbatch.exe",
    "comsolmphserver.exe",
    "comsolmphclient.exe",
    "comsolcompile.exe",
    "comsolclusterbatch.exe",
)

INTERESTING_MODULE_DOCS = (
    "MEMS_Module",
    "Structural_Mechanics_Module",
    "Acoustics_Module",
    "RF_Module",
    "Heat_Transfer_Module",
    "Optimization_Module",
    "Nonlinear_Structural_Materials_Module",
    "LiveLink_for_MATLAB",
)

REPORT_RELATIVE = Path("reports") / "env_report.json"
CAPABILITY_RELATIVE = Path("reports") / "capability_matrix.json"


def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """执行外部命令，返回 (returncode, stdout, stderr)，失败不抛异常。"""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except Exception as exc:  # 超时 / 找不到可执行文件 / 权限不足
        return -1, "", f"{type(exc).__name__}: {exc}"


def pe_file_version(exe: Path) -> str | None:
    """通过 PowerShell 读取 PE 文件版本，避免引入 pywin32 依赖。"""
    if not exe.exists():
        return None
    _, out, _ = _run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-Item -LiteralPath '{exe}').VersionInfo.FileVersion",
        ]
    )
    return out or None


def tcp_probe(host: str, port: int, timeout: float = 1.5) -> bool:
    """探测 TCP 端口是否可连接（判断 comsolmphserver 是否在监听）。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def parse_license_info(path: Path) -> dict[str, str]:
    """解析 licenseinfo.ini，并对授权号脱敏（仅保留末 3 位）。"""
    info: dict[str, str] = {}
    if not path.exists():
        return info
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        info[key.strip()] = value.strip()
    license_number = info.pop("LicenseNumber", "")
    if license_number:
        info["LicenseNumber_masked"] = "*" * max(0, len(license_number) - 3) + license_number[-3:]
    return info


def collect_env(
    comsol_home: Path | str | None = None,
    matlab_exe: Path | str | None = None,
    mph_port: int | None = None,
) -> dict:
    """汇总一次环境快照（只读，不启动任何 COMSOL 进程）。"""
    comsol_home = Path(comsol_home or DEFAULT_COMSOL_HOME)
    matlab_exe = Path(matlab_exe or DEFAULT_MATLAB_EXE)
    mph_port = int(mph_port or DEFAULT_MPH_PORT)
    bin_dir = comsol_home / "bin" / "win64"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": {
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "cwd": str(Path.cwd()),
        },
        "comsol": {
            "home": str(comsol_home),
            "home_exists": comsol_home.is_dir(),
            "version": pe_file_version(bin_dir / "comsolbatch.exe"),
            "executables": {name: (bin_dir / name).exists() for name in EXPECTED_EXES},
            "license_files": {
                name: (comsol_home / "license" / name).exists()
                for name in ("license.dat", "license.paid")
            },
            "license_info": parse_license_info(comsol_home / "licenseinfo.ini"),
            # 文档层事实，非授权事实
            "documented_modules": {
                name: (comsol_home / "doc" / "pdf" / name).exists()
                for name in INTERESTING_MODULE_DOCS
            },
        },
        "matlab": {
            "executable": str(matlab_exe),
            "exists": matlab_exe.exists(),
            "livelink_mli": str(comsol_home / "mli"),
            "livelink_exists": (comsol_home / "mli").is_dir(),
        },
        "mphserver": {
            "host": "127.0.0.1",
            "port": mph_port,
            "listening": tcp_probe("127.0.0.1", mph_port),
        },
    }


def report_path() -> Path:
    """环境报告文件的规范位置。"""
    return work_root() / REPORT_RELATIVE


def save_report(report: dict, path: Path | None = None) -> Path:
    """把快照写入磁盘（默认 ``work/reports/env_report.json``）。"""
    target = path or report_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def load_report(path: Path | None = None) -> dict | None:
    """读取已保存的快照；不存在时返回 None。"""
    target = path or report_path()
    if not target.exists():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def capability_matrix(report: dict | None = None) -> dict:
    """生成模块能力表：合并「文档存在」（实测）与「求解已验证」（来自真实冒烟）。

    ``documented`` 来自文档目录（实测）；``solve_verified`` 只有真实求解冒烟才能回填，
    未回填前一律为 ``None``，不得写成 ``True``（AGENTS.md 红线 1/3）。
    """
    report = report or load_report() or collect_env()
    recorded = load_capability_matrix() or {}
    recorded_modules = recorded.get("modules", {})

    modules: dict[str, dict] = {}
    for name, present in report["comsol"]["documented_modules"].items():
        entry = recorded_modules.get(name, {})
        modules[name] = {
            "documented": present,
            "solve_verified": entry.get("solve_verified"),
            "evidence": entry.get("evidence"),
        }
    # 允许记录文件中出现文档目录之外的模块（例如靠 license 冒烟确认的产品）
    for name, entry in recorded_modules.items():
        modules.setdefault(name, {"documented": None, **entry})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "comsol_version": report["comsol"]["version"],
        "mphserver_listening": report["mphserver"]["listening"],
        "note": (
            "documented=文档存在(实测)；solve_verified=真实求解确认，"
            "需逐模块冒烟后由 scripts 回填，未回填为 null"
        ),
        "matrix_source": str(capability_path()) if recorded else None,
        "modules": modules,
    }


def capability_path() -> Path:
    """模块能力表文件的规范位置。"""
    return work_root() / CAPABILITY_RELATIVE


def load_capability_matrix(path: Path | None = None) -> dict | None:
    """读取已记录的求解能力表；不存在时返回 None。"""
    target = path or capability_path()
    if not target.exists():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def save_capability_matrix(matrix: dict, path: Path | None = None) -> Path:
    """把求解能力表落盘（供 MCP 的 module_capability 读取）。"""
    target = path or capability_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def render_summary(report: dict) -> str:
    """把快照渲染成可读摘要（供 CLI 与工具返回共用）。"""
    comsol = report["comsol"]
    lines = [
        "=" * 68,
        "COMSOL 环境冒烟报告",
        "=" * 68,
        f"COMSOL home      : {comsol['home']}  (存在={comsol['home_exists']})",
        f"COMSOL 版本      : {comsol['version']}",
        f"可执行文件       : {sum(comsol['executables'].values())}/{len(comsol['executables'])} 就位",
        f"授权文件         : {comsol['license_files']}",
        f"授权信息(脱敏)   : {comsol['license_info']}",
        f"MATLAB           : {report['matlab']['executable']} (存在={report['matlab']['exists']})",
        f"LiveLink(mli)    : 存在={report['matlab']['livelink_exists']}",
        f"mphserver        : {report['mphserver']['host']}:{report['mphserver']['port']} "
        f"监听={report['mphserver']['listening']}",
        "-" * 68,
        "模块文档存在性（≠授权，需真实求解确认）:",
    ]
    lines += [
        f"  [{'x' if ok else ' '}] {name}"
        for name, ok in comsol["documented_modules"].items()
    ]
    lines.append("=" * 68)
    return "\n".join(lines)


def core_paths_ok(report: dict) -> bool:
    """核心通路是否齐备（决定 CLI 退出码）。"""
    exes = report["comsol"]["executables"]
    return bool(
        report["comsol"]["home_exists"]
        and exes.get("comsol.exe")
        and exes.get("comsolbatch.exe")
        and exes.get("comsolmphserver.exe")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="COMSOL 环境冒烟检查（只读）")
    parser.add_argument("--comsol-home", default=DEFAULT_COMSOL_HOME)
    parser.add_argument("--matlab-exe", default=DEFAULT_MATLAB_EXE)
    parser.add_argument("--mph-port", type=int, default=DEFAULT_MPH_PORT)
    parser.add_argument("--out", default=None, help="报告输出路径（默认 work/reports/env_report.json）")
    args = parser.parse_args(argv)

    ensure_work_tree()
    report = collect_env(args.comsol_home, args.matlab_exe, args.mph_port)
    print(render_summary(report))
    target = save_report(report, Path(args.out) if args.out else None)
    print(f"已写入: {target}")
    return 0 if core_paths_ok(report) else 2


if __name__ == "__main__":
    raise SystemExit(main())
