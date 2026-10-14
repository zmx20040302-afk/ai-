# -*- coding: utf-8 -*-
"""**证据只读检查**（纪律 **R16**：校验者不得改写被校验对象）—— 可复用的两部分。

## 事故背景（实测，`INDEX §105`/§109.3）

`scripts\\verify_paper_evidence.py` 旧版第 0 项**把主生成脚本就地重跑一遍**
（「先覆盖现场、再比对产物」）⇒ 2026-10-09 09:54:53 一次「校验」把
`work\\runs\\paper-evidence-20261009\\` **31 件产物整个重写**，而它同时报告「逐位相同」。
该设计**原理上无法发现篡改**（先把现场覆盖掉，再宣布无异常）。

本模块把那次的教训做成**两件可复用的东西**（原来只长在 `verify_paper_evidence.py` 里，
现在任何脚本/测试都能挂）：

1. **动态**：`snapshot_dir()` ＋ `check_dir_readonly()` —— 对一个目录取「文件集合 +
   每文件 sha256 + size + mtime_ns」快照，跑一段被检代码后再取一次，断言**完全相等**。
   `mtime_ns` 一并比，是为了抓住「**内容相同但被重写**」那种写盘（只比 sha256 会漏）。
2. **静态**：`scan_verify_scripts()` —— 扫 `scripts\\verify_*.py`，若**默认路径**下出现
   对**被校验对象**的写操作、或在 `regen*` 之外**调用生成器/起子进程** ⇒ 报错（R16）。

### 静态扫描的判定口径（说得清、也可反证）

* **D1 `subprocess_outside_regen`**：`subprocess.*` / `os.system` / `os.popen` / `os.spawn*`
  出现在**函数名不含 `regen`** 的位置 ⇒ 违例。这正是 §109 事故的机制
  （旧版把 `subprocess.run([... 生成脚本 ...])` 写在 `main()` 第 0 项）。
* **D2 `write_to_read_root`**：同一个作用域内，**既被读又被写**的路径根表达式
  （如 `RUN` / `pd` / `args.report`）⇒ 违例。判定只在**同一作用域**内做交集：
  「读了 A、写到 B」不算违例（校验脚本写自己的报告到用户指定路径是允许的），
  「读了 A、又写回 A」正是 R16 禁止的事。
* **豁免必须显式、可 grep**：写调用所在行（或该语句跨行范围）里带
  `R16-ALLOW-WRITE: <理由>` 才豁免；整个文件豁免要写
  `R16-ALLOW-WRITES-IN-FILE: <理由>`。豁免件会被**列出来**（`exempt`），不静默。
* **已知盲区（如实声明）**：只看静态语法，**不做跨函数/跨过程的数据流**。所以
  「把 `--out-dir` 的缺省值算成被校验目录」这种形态不保证被抓到（本轮实测：
  `verify_te2_9_value_profile.py` 的 `pd` 是**同一函数内**的局部变量 ⇒ 恰好落在 D2 内，
  被抓到了；换个写法就未必）。动态快照（1）是这条盲区的补充手段。
"""
from __future__ import annotations

import ast
import fnmatch
import hashlib
import os
import pathlib
import tokenize
from dataclasses import dataclass
from typing import Any, Callable, NamedTuple

__all__ = [
    "DEFAULT_IGNORE", "ReadOnlyViolation", "snapshot_dir", "compare_snapshots",
    "check_dir_readonly", "assert_dir_readonly", "format_snapshot_diff",
    "Finding", "scan_verify_source", "scan_verify_scripts", "LEGACY_KNOWN_OFFENDERS",
    "LEGACY_STATUS_FIXED", "LEGACY_STATUS_NEVER_OFFENDED", "LEGACY_STATUS_VALUES",
    "LegacyOffenderStatus", "LEGACY_OFFENDER_STATUSES", "legacy_status_gaps",
    "assert_legacy_allowlist_status_complete",
]

#: 快照时忽略的名字（**快照前后用同一套**，否则两侧不可比）。
#: 只忽略明确与产物无关的噪声；**不忽略任何证据文件**。
DEFAULT_IGNORE: tuple[str, ...] = (
    "__pycache__", "*.pyc", ".DS_Store", "Thumbs.db", "*.tmp", "~$*",
)


class ReadOnlyViolation(RuntimeError):
    """被检代码改写了它本该只读的对象。"""

    def __init__(self, message: str, verdict: dict | None = None) -> None:
        super().__init__(message)
        self.verdict = verdict


# --------------------------------------------------------------------------- 动态快照
def _sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ignored(name: str, ignore: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in ignore)


def snapshot_dir(root: str | os.PathLike, *, ignore: tuple[str, ...] = DEFAULT_IGNORE,
                 ) -> dict[str, tuple[str, int, int]]:
    """对一个目录取快照：`{相对路径(posix): (sha256, size, mtime_ns)}`。

    * **子目录也算条目**（`sha256` 记 `"<dir>"`、`size` 记 0）：在被校验目录里
      `mkdir` 同样是写盘，只记文件会漏掉「新建了一个目录」；
    * 目录不存在 ⇒ 返回空字典（调用方据此判「快照为空 ⇒ 用例无意义」）；
    * 符号链接指向的文件按普通文件处理（读的是目标字节）；
    * 读不出的文件不静默跳过 ⇒ 记 `("<读不出: 类型: 原文>", -1, -1)`，
      这样「快照变小」不会伪装成「没变化」。
    """
    base = pathlib.Path(root)
    out: dict[str, tuple[str, int, int]] = {}
    if not base.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if not _ignored(d, ignore))
        for name in dirnames:
            p = pathlib.Path(dirpath) / name
            rel = p.relative_to(base).as_posix()
            try:
                out[rel] = ("<dir>", 0, p.stat().st_mtime_ns)
            except OSError as exc:
                out[rel] = ("<读不出: %s: %s>" % (type(exc).__name__, exc), -1, -1)
        for name in sorted(filenames):
            if _ignored(name, ignore):
                continue
            p = pathlib.Path(dirpath) / name
            rel = p.relative_to(base).as_posix()
            try:
                st = p.stat()
                out[rel] = (_sha256_file(p), st.st_size, st.st_mtime_ns)
            except OSError as exc:
                out[rel] = ("<读不出: %s: %s>" % (type(exc).__name__, exc), -1, -1)
    return out


_FIELD_ZH = {"sha256": "sha256", "size": "字节数", "mtime_ns": "mtime_ns"}


def compare_snapshots(before: dict, after: dict) -> dict:
    """比较两次快照，给出逐项差异与中文问题清单。"""
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed: list[dict] = []
    for rel in sorted(set(before) & set(after)):
        b, a = before[rel], after[rel]
        if b == a:
            continue
        fields = [name for name, i in (("sha256", 0), ("size", 1), ("mtime_ns", 2))
                  if b[i] != a[i]]
        changed.append({"path": rel, "fields": fields, "before": b, "after": a})
    problems: list[str] = []
    for rel in added:
        problems.append("新增文件：%s（被检代码往被校验目录里写了新东西）" % rel)
    for rel in removed:
        problems.append("文件消失：%s（被检代码删了东西）" % rel)
    for c in changed:
        zh = "、".join(_FIELD_ZH[f] for f in c["fields"])
        extra = ""
        if c["fields"] == ["mtime_ns"]:
            extra = "（**内容逐字节相同但被重写**）"
        problems.append("被改写：%s（变了：%s）%s" % (c["path"], zh, extra))
    return {"added": added, "removed": removed, "changed": changed,
            "n_before": len(before), "n_after": len(after), "problems": problems,
            "ok": not problems}


def format_snapshot_diff(cmp: dict, *, limit: int = 10) -> str:
    """把差异压成一行行的中文说明（报告/异常消息里直接用）。"""
    if cmp["ok"]:
        return "目录快照前后全等（%d 个文件，sha256 + size + mtime_ns 全等）" % cmp["n_before"]
    lines = ["目录快照**不一致**：前 %d 个文件 → 后 %d 个文件"
             % (cmp["n_before"], cmp["n_after"])]
    lines += ["  - " + p for p in cmp["problems"][:limit]]
    if len(cmp["problems"]) > limit:
        lines.append("  … 另有 %d 条" % (len(cmp["problems"]) - limit))
    return "\n".join(lines)


def check_dir_readonly(root: str | os.PathLike, fn: Callable[[], Any], *,
                       ignore: tuple[str, ...] = DEFAULT_IGNORE) -> dict:
    """跑 `fn()` 并断言它**一个字节都没写**进 `root`。

    返回（不抛）：
    * `read_only_ok`：只看写入 —— 快照前后是否全等（这是 R16 的判定）；
    * `ok`：`read_only_ok` **且** `fn()` 没抛异常；
    * `problems`：中文问题清单（写入问题 + 异常）；
    * `before`/`after`：两次快照（供报告逐件列哈希）。

    ⚠️ 即使 `fn()` 抛了异常，**照样比对快照** —— 「它中途崩了」不能成为「它没写」的借口。
    """
    base = pathlib.Path(root)
    before = snapshot_dir(base, ignore=ignore)
    error: str | None = None
    exc_obj: BaseException | None = None
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 —— 异常要如实记，但不能吞掉写入判定
        error = "%s: %s" % (type(exc).__name__, exc)
        exc_obj = exc
    after = snapshot_dir(base, ignore=ignore)
    cmp = compare_snapshots(before, after)
    problems = list(cmp["problems"])
    if error:
        problems.append("被检代码抛异常（写入判定照做）：%s" % error)
    verdict = {"ok": cmp["ok"] and error is None, "read_only_ok": cmp["ok"],
               "error": error, "problems": problems, "write_problems": cmp["problems"],
               "before": before, "after": after, "diff": cmp,
               "n_files_before": cmp["n_before"], "n_files_after": cmp["n_after"],
               "root": str(base)}
    if exc_obj is not None:
        verdict["exc_type"] = type(exc_obj).__name__
    return verdict


def assert_dir_readonly(root: str | os.PathLike, fn: Callable[[], Any], *,
                        ignore: tuple[str, ...] = DEFAULT_IGNORE,
                        label: str = "") -> dict:
    """`check_dir_readonly()` 的断言版：**有任何写入即抛** `ReadOnlyViolation`（R16）。

    例外：被检代码自己抛的异常会被**原样重抛**（调用方本来就要看到它），
    但只在**没有写入**的前提下；一旦发现写入，写入违例优先抛出（并 `from` 原异常）。
    """
    v = check_dir_readonly(root, fn, ignore=ignore)
    if not v["read_only_ok"]:
        msg = "%s被检代码改写了只读对象：\n%s" % (
            (label + "：") if label else "", format_snapshot_diff(v["diff"]))
        if v["error"]:
            msg += "\n（被检代码同时抛了异常：%s）" % v["error"]
        raise ReadOnlyViolation(msg, verdict=v)
    if v["error"]:
        raise RuntimeError("%s被检代码抛异常：%s" % ((label + "：") if label else "", v["error"]))
    return v


# --------------------------------------------------------------------------- 静态扫描
@dataclass(frozen=True)
class Finding:
    """一条 R16 静态发现。`key` 是**稳定标识**（行号会随文件演进而漂移，不用于比对）。"""

    script: str
    line: int
    kind: str
    root: str
    detail: str
    text: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.script, self.kind, self.root)

    def render(self) -> str:
        return "%s:%d [%s] %s —— %s" % (self.script, self.line, self.kind, self.root, self.detail)


#: **已登记的遗留写入点**（`INDEX §116.3` 建立；**两处均已在 `§140` 修掉**）。
#: 策略（**一字未变**）：**不允许出现新的越界点**（`new == []`），遗留项仍在时如实列出
#: （`legacy_hits`），被修掉也不报错（`legacy_absent`）；**已修条目若再次命中，重新计入
#: `legacy_hits`**（并标 `legacy_regressed`）—— 「已修」**不是永久豁免**。
#: 条目**保留在表内**是刻意的：删掉它只会让「回归」落进 `new`，而 `new`/`legacy_hits`
#: 的判定语义本次**一个字都没改**；状态位见 `LEGACY_OFFENDER_STATUSES`。
LEGACY_KNOWN_OFFENDERS: frozenset[tuple[str, str, str]] = frozenset({
    # `RUN` 既是读的根（`RUN.glob("mesh_*/field_points.npz")`）又是写的根
    # （`(RUN / "independent_s4_recheck.json").write_text(...)`）⇒ 旧默认路径会把
    # `independent_s4_recheck.json` 写进被校验树。
    # **现状（`§140` 实测；本条注释于 `§142` 更正）**：已改为「**默认只读** ＋ 显式 `--out`
    # 才落盘」⇒ 该写入点**不再命中**（落入 `legacy_absent`），故状态位 = `fixed`。
    ("verify_s34_s4_interp.py", "write_to_read_root", "RUN"),
    # `pd` 既是读的根（`(pd / "te2_9_profile.json").read_text()`）又是写的根
    # （`(pd / "verify.json").write_text(...)`）⇒ 旧默认路径会把 `verify.json` 写进画像目录。
    # ⚠️ **旧注释已陈旧，此处更正（`§142`）**：原文写的「`--out-dir` 缺省与画像同目录」
    # 与实况不符 —— `--out-dir` 在 argparse 里**从来不存在**；自称「本脚本**只读**」的
    # docstring 也已于 `§140` 改对。
    # **现状**：同样改为「默认只读 ＋ 显式 `--out`」⇒ 不再命中（`legacy_absent`），
    # 状态位 = `fixed`。
    ("verify_te2_9_value_profile.py", "write_to_read_root", "pd"),
})

#: allowlist 条目状态位的**取值**（`INDEX §140.6 第 1 条` 的待办落地）。
#: * `fixed` —— **曾经越界、现已修复**（必须同时给 `fixed_at` 与 `evidence`，否则算状态缺失）；
#: * `never_offended` —— 登记在册但**从未实测命中**（没有任何「曾经越界」的证据）。
#: 两者的差别只体现在**报告**上：`fixed` 且当前不再命中 ⇒ 进 `legacy_fixed_absent`
#: （这才叫「已修」）；`never_offended` 且不命中 ⇒ 只是「没出现」，**不得**声称已修。
LEGACY_STATUS_FIXED = "fixed"
LEGACY_STATUS_NEVER_OFFENDED = "never_offended"
LEGACY_STATUS_VALUES: tuple[str, ...] = (LEGACY_STATUS_FIXED, LEGACY_STATUS_NEVER_OFFENDED)


class LegacyOffenderStatus(NamedTuple):
    """一条 allowlist 条目的**状态位**（让「曾经越界、现已修复」与「从未越界」可区分）。

    三个字段都不是字面量判定：`status` 是登记值，`fixed_at`/`evidence` 是**依据**，
    而「它到底算不算已修」由 `scan_verify_scripts()` **现算**（见 `legacy_fixed_absent` /
    `legacy_regressed`），不是写死的 `ok`。

    status       `fixed` / `never_offended`（取值域 = `LEGACY_STATUS_VALUES`）
    fixed_at     修复日期（`status == fixed` 必填；`never_offended` 必须留空）
    evidence     依据原文（索引节号 ＋ 实测结论）；`fixed` 时**不许空**（空 = 没依据 ⇒ 算状态缺失）
    """

    status: str
    fixed_at: str = ""
    evidence: str = ""


#: allowlist 条目的状态位。**键必须与 `LEGACY_KNOWN_OFFENDERS` 逐条对齐**（分母可判定）：
#: 缺一条 ⇒ `legacy_status_gaps()` 报 `missing`、`assert_legacy_allowlist_status_complete()`
#: **明确报错**、`scan_verify_scripts()` 侧**如实降级**（`legacy_status_ok=False`）。
#: ⚠️ 缺状态的键**绝不**被当成「已修」；`ok` / `new` / `legacy_hits` / `legacy_absent`
#: 的判定语义本次**一个字都没改**。
LEGACY_OFFENDER_STATUSES: dict[tuple[str, str, str], LegacyOffenderStatus] = {
    ("verify_s34_s4_interp.py", "write_to_read_root", "RUN"): LegacyOffenderStatus(
        status=LEGACY_STATUS_FIXED,
        fixed_at="2026-10-09",
        evidence="§140.2 实测：默认只读 ＋ 显式 `--out` 才落盘；`legacy_hits` 2→0、"
                 "`legacy_absent` 0→2；见证串 `independent_s4_recheck.json` 已不在源码里",
    ),
    ("verify_te2_9_value_profile.py", "write_to_read_root", "pd"): LegacyOffenderStatus(
        status=LEGACY_STATUS_FIXED,
        fixed_at="2026-10-09",
        evidence="§140.2 实测：默认只读 ＋ 显式 `--out`；不实 docstring 已改对；"
                 "被校验树 `te2_9-value-20261009T090701` 本轮未被触碰",
    ),
}


def legacy_status_gaps(
        allowlist: frozenset[tuple[str, str, str]] = LEGACY_KNOWN_OFFENDERS,
        statuses: dict[tuple[str, str, str], LegacyOffenderStatus] = LEGACY_OFFENDER_STATUSES,
) -> dict:
    """状态位的**完整性体检**（返回报告，不抛；判定由测量算出，不是字面量）。

    fail-closed 口径：`ok` 只在**四类问题全空**时为真 ——

    * `missing`：allowlist 里有、状态表里没有 ⇒ **不得**被当成「已修」；
    * `invalid`：`fixed` 缺 `fixed_at`/`evidence`，或 `never_offended` 却带了 `fixed_at`；
    * `unknown_status`：状态值不在 `LEGACY_STATUS_VALUES` 内（单独列出便于定位）；
    * `extra`：状态表里有、allowlist 里没有 ⇒ 陈旧条目（分母对不上）。
    """
    missing = sorted(k for k in allowlist if k not in statuses)
    extra = sorted(k for k in statuses if k not in allowlist)
    invalid: list[tuple[str, str, str]] = []
    unknown: list[tuple[str, str, str]] = []
    for key in sorted(statuses):
        if key not in allowlist:
            continue
        v = statuses[key]
        if v.status not in LEGACY_STATUS_VALUES:
            unknown.append(key)
            continue
        if v.status == LEGACY_STATUS_FIXED and not (v.fixed_at.strip() and v.evidence.strip()):
            invalid.append(key)
        if v.status == LEGACY_STATUS_NEVER_OFFENDED and v.fixed_at.strip():
            invalid.append(key)
    problems: list[str] = []
    for k in missing:
        problems.append("allowlist 条目缺状态位：%s ⇒ **不得**当成「已修」（状态未登记）" % (k,))
    for k in invalid:
        problems.append("状态位不成立：%s（status=%r）：`fixed` 必须给 fixed_at+evidence、"
                        "`never_offended` 不得给 fixed_at" % (k, statuses[k].status))
    for k in unknown:
        problems.append("状态值不在 %s 内：%s（%r）"
                        % (LEGACY_STATUS_VALUES, k, statuses[k].status))
    for k in extra:
        problems.append("状态表里有、allowlist 里没有：%s（陈旧条目 ⇒ 分母对不上）" % (k,))
    n_fixed = sum(1 for k, v in statuses.items()
                  if k in allowlist and v.status == LEGACY_STATUS_FIXED)
    return {"ok": not (missing or invalid or unknown or extra),
            "missing": missing, "invalid": invalid, "unknown_status": unknown, "extra": extra,
            "problems": problems, "n_allowlist": len(allowlist), "n_statuses": len(statuses),
            "n_fixed": n_fixed}


def assert_legacy_allowlist_status_complete(
        allowlist: frozenset[tuple[str, str, str]] = LEGACY_KNOWN_OFFENDERS,
        statuses: dict[tuple[str, str, str], LegacyOffenderStatus] = LEGACY_OFFENDER_STATUSES,
) -> dict:
    """状态位不完整 ⇒ **明确报错**（`RuntimeError`，附缺失键原文）；完整 ⇒ 原样返回体检报告。

    这是任务书第 ③ 条选定的「明确报错」那一半；另一半（**如实降级**）在
    `scan_verify_scripts()` 里 —— 它不抛，但把 `legacy_status_ok` 置假并列出 `missing`。
    """
    gaps = legacy_status_gaps(allowlist, statuses)
    if not gaps["ok"]:
        raise RuntimeError(
            "allowlist 状态位不完整（%d 条问题）：\n%s"
            % (len(gaps["problems"]), "\n".join("  - " + p for p in gaps["problems"])))
    return gaps


_WRITE_METHODS = frozenset({
    "write_text", "write_bytes", "unlink", "touch", "mkdir", "rmdir", "rename",
    "replace", "truncate", "chmod", "symlink_to", "hardlink_to", "write",
})
_WRITE_FUNCS = frozenset({
    "os.remove", "os.unlink", "os.rename", "os.replace", "os.mkdir", "os.makedirs",
    "os.rmdir", "os.removedirs", "os.truncate", "os.chmod", "os.link", "os.symlink",
    "shutil.copy", "shutil.copy2", "shutil.copyfile", "shutil.copytree",
    "shutil.move", "shutil.rmtree",
})
_READ_METHODS = frozenset({
    "read_text", "read_bytes", "readlines", "glob", "rglob", "iterdir", "walk",
    "is_file", "is_dir", "exists", "stat", "open", "read", "loadtxt", "genfromtxt",
})
_READ_FUNCS = frozenset({
    "open", "os.listdir", "os.scandir", "os.stat", "os.path.isfile", "os.path.isdir",
    "os.path.exists", "json.load", "np.load", "np.loadtxt", "csv.DictReader",
    "csv.reader", "hashlib.sha256", "sha256_file", "snapshot_dir",
})
_SUBPROCESS_ROOTS = ("subprocess.", "os.system", "os.popen", "os.spawn")
_WRITE_MODE_CHARS = set("wax+")
_EXEMPT_WRITE = "R16-ALLOW-WRITE:"
_EXEMPT_FILE = "R16-ALLOW-WRITES-IN-FILE:"


def _dotted(node: ast.AST) -> str | None:
    """把 `a.b.c` 展开成字符串；不是纯属性链则 None。"""
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


def _expr_root(node: ast.AST | None) -> str | None:
    """表达式里代表「路径根」的那一段（`RUN / "x"` → `RUN`；`args.report` → `args.report`）。"""
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _expr_root(node.value)
        return None if base is None else "%s.%s" % (base, node.attr)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _expr_root(node.left)
    if isinstance(node, ast.Subscript):
        return _expr_root(node.value)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.replace("\\", "/")
    if isinstance(node, ast.Call):
        name = _dotted(node.func)
        if name in ("Path", "pathlib.Path", "str", "os.fspath", "os.path.expanduser"):
            return _expr_root(node.args[0]) if node.args else None
        if name == "os.path.join" and node.args:
            return _expr_root(node.args[0])
        return None
    return None


def _call_name(node: ast.Call) -> str:
    """纯属性链形式的调用名（`os.remove` / `subprocess.run`）；**接收者是表达式时返回空串**。

    ⚠️ 单独用它**不够**：`(RUN / "x.json").write_text(...)` 的 func 是
    `Attribute(value=BinOp(...))`，属性链断在 BinOp 上 ⇒ 这里返回空串。
    方法类调用必须另走 `_call_parts()` 的 `short`（`write_text`）＋ 接收者根（`RUN`）。
    """
    return _dotted(node.func) or ""


#: 目标路径**不是**第 1 个实参的调用（根表达式要从这里取，否则会取到源路径）
_DEST_ARG_INDEX = {
    "shutil.copy": 1, "shutil.copy2": 1, "shutil.copyfile": 1, "shutil.move": 1,
    "shutil.copytree": 1, "os.rename": 1, "os.replace": 1, "os.link": 1, "os.symlink": 1,
}


def _call_parts(node: ast.Call) -> tuple[str, str, str | None]:
    """把一次调用拆成（限定名, 短名, 接收者根表达式）。

    * `(RUN / "x").write_text(...)` → `("", "write_text", "RUN")`；
    * `Path(args.out).write_text(...)` → `("", "write_text", "args.out")`；
    * `os.remove(p)` → `("os.remove", "remove", None)`；
    * `shutil.copy2(a, b)` → `("shutil.copy2", "copy2", None)`（目标在 `_DEST_ARG_INDEX`）。
    """
    f = node.func
    if isinstance(f, ast.Attribute):
        return (_dotted(f) or ""), f.attr, _expr_root(f.value)
    if isinstance(f, ast.Name):
        return f.id, f.id, None
    return "", "", None


def _call_root(node: ast.Call, qualified: str, short: str, recv: str | None) -> str | None:
    """这次调用作用的**路径根**（写操作取目标、读操作取来源）。"""
    if recv is not None:
        return recv
    if not node.args:
        return None
    idx = _DEST_ARG_INDEX.get(qualified, 0)
    if idx >= len(node.args):
        return None
    return _expr_root(node.args[idx])


def _write_mode(call: ast.Call, name: str) -> bool:
    """`open(p, "w")` / `p.open("w")` 这类**按 mode 判定**的写操作。

    口径差别很关键：内建 `open(file, mode)` 的 mode 是**第 2 个**实参，
    而 `Path.open(mode="r")` 的 mode 是**第 1 个** —— 记反了就会把 `p.open("w")` 当读。
    """
    short = name.split(".")[-1]
    if short != "open":
        return False
    args = list(call.args)
    mode = None
    if name == "open":                       # 内建 open(file, mode)
        if len(args) >= 2 and isinstance(args[1], ast.Constant) \
                and isinstance(args[1].value, str):
            mode = args[1].value
    else:                                    # Path.open(mode, ...)
        if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
            mode = args[0].value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant) \
                and isinstance(kw.value.value, str):
            mode = kw.value.value
    return bool(mode) and any(ch in _WRITE_MODE_CHARS for ch in mode)


def _is_write_call(node: ast.Call, name: str) -> bool:
    """是否写操作。`str.replace(old, new)` 与 `Path.replace(target)` 必须分开 ——
    本仓库的 verify 脚本里 `str.replace("\\\\", "/")` 到处都是，误判会把读路径当成写路径。"""
    short = name.split(".")[-1]
    if name in _WRITE_FUNCS:
        return True
    if short == "replace":
        return isinstance(node.func, ast.Attribute) and len(node.args) == 1
    if short in _WRITE_METHODS:
        return True
    return _write_mode(node, name)


def _walk_pruned(stmt: ast.AST):
    """遍历语句，但**不进入函数/类定义体**（那些是独立作用域，各自单独扫）。

    注意是「遇到定义就停」，不是「跳过子节点里的定义」：否则以 `def main():` 为起点遍历时，
    它的函数体会**又**被模块作用域扫一遍 ⇒ 同一条发现报两次。
    """
    stack = [stmt]
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _string_constants(node: ast.AST) -> list[str]:
    """取一个表达式里出现的**字符串字面量**（**递归**，含列表/元组/字符串拼接）。

    ⚠️ 实测教训（`tests\\test_subprocess_encoding.py` 行 119 的原话）：
    按 `node.args` 找 `sys.executable` 在 **argv 是列表字面量**
    （`[sys.executable, "scripts/gen.py"]`）时**永远匹配不到** ⇒ 生成器名字也就抓不到。
    所以这里必须递归进列表 —— 否则这条检查就是恒真的摆设。
    """
    return [n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _collect_comments(path: pathlib.Path) -> dict[int, str]:
    out: dict[int, str] = {}
    try:
        with path.open("rb") as fh:
            for tok in tokenize.tokenize(fh.readline):
                if tok.type == tokenize.COMMENT:
                    out[tok.start[0]] = tok.string
    except (tokenize.TokenError, OSError, SyntaxError):
        return {}
    return out


def _enclosing_spans(tree: ast.AST) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node.lineno, node.end_lineno or node.lineno, node.name))
    return out


def scan_verify_source(path: str | os.PathLike) -> dict:
    """扫一个 `verify_*.py`：返回 `{"findings": [...], "exempt": [...]}`。

    `path` 不存在 / 语法错误 ⇒ `findings` 里放一条 `unreadable`（fail-closed：
    扫不了**不算通过**）。
    """
    p = pathlib.Path(path)
    script = p.name
    try:
        src = p.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        return {"findings": [Finding(script, 0, "unreadable", "-",
                                     "读不出或解析不了：%s: %s（扫不了不算通过）"
                                     % (type(exc).__name__, exc))],
                "exempt": []}
    lines = src.splitlines()
    comments = _collect_comments(p)
    file_exempt = next((f"{ln}: {txt.strip()}" for ln, txt in sorted(comments.items())
                        if _EXEMPT_FILE in txt and txt.split(_EXEMPT_FILE, 1)[1].strip()),
                       None)

    spans = _enclosing_spans(tree)
    findings: list[Finding] = []
    exempt: list[dict] = []

    def _fn_of(lineno: int) -> str:
        """所在**最内层**函数名（找不到 ⇒ 空串，代表模块级）。"""
        best: tuple[int, str] | None = None
        for s, e, name in spans:
            if s <= lineno <= e and (best is None or s > best[0]):
                best = (s, name)
        return best[1] if best else ""

    def _exempt_reason(node: ast.AST) -> str | None:
        """豁免注释可以写在该语句的**跨行范围内**、也可以写在**紧邻上一行**。"""
        lo, hi = node.lineno, getattr(node, "end_lineno", node.lineno) or node.lineno
        for ln in range(max(1, lo - 1), hi + 1):
            txt = comments.get(ln, "")
            if _EXEMPT_WRITE in txt:
                reason = txt.split(_EXEMPT_WRITE, 1)[1].strip()
                if reason:
                    return "行 %d %s %s" % (ln, _EXEMPT_WRITE, reason)
        return None

    def _emit(node: ast.AST, kind: str, root: str, detail: str) -> None:
        f = Finding(script, node.lineno, kind, root, detail,
                    lines[node.lineno - 1].strip()[:160] if node.lineno <= len(lines) else "")
        if file_exempt:
            exempt.append({"finding": f, "reason": "文件级豁免 %s" % file_exempt})
            return
        reason = _exempt_reason(node)
        if reason:
            exempt.append({"finding": f, "reason": reason})
            return
        findings.append(f)

    # ---- 作用域：模块级 + 每个函数各自一份（只在**同一作用域内**做读写根交集）
    # `_walk_pruned` 保证嵌套函数体**只在它自己的作用域里**被扫一次（否则会重复报）。
    scopes: list[tuple[str, list[ast.AST]]] = [("<module>", list(tree.body))]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scopes.append((node.name, list(node.body)))

    for scope_name, body in scopes:
        reads: dict[str, list[int]] = {}
        writes: list[tuple[ast.Call, str, str]] = []
        for stmt in body:
            for node in _walk_pruned(stmt):
                if not isinstance(node, ast.Call):
                    continue
                qualified, short, recv = _call_parts(node)
                if not short:
                    continue
                # D1：起子进程 / 调生成器（函数名不含 regen ⇒ 违例）
                if qualified.startswith(_SUBPROCESS_ROOTS):
                    fname = _fn_of(node.lineno)
                    if "regen" not in fname.lower():
                        argv = _string_constants(node)
                        gen = [s for s in argv if s.endswith(".py")] or [
                            s for s in argv if "gen" in s.lower()]
                        _emit(node, "subprocess_outside_regen", fname or "<module>",
                              "在 `%s` 里起子进程/调生成器%s ⇒ 默认路径可能改写被校验对象"
                              % (fname or "<module>",
                                 ("（命令含 %s）" % gen) if gen else ""))
                    continue
                if _is_write_call(node, qualified or short):
                    writes.append((node, _call_root(node, qualified, short, recv) or "<?>",
                                   qualified or short))
                elif qualified in _READ_FUNCS or short in _READ_METHODS:
                    root = _call_root(node, qualified, short, recv)
                    if root:
                        reads.setdefault(root, []).append(node.lineno)

        for node, root, name in writes:
            if root in reads:
                _emit(node, "write_to_read_root", root,
                      "`%s` 在 `%s` 里**既被读（行 %s）又被写**（`%s`）⇒ 默认路径就写进了"
                      "被校验对象（R16）"
                      % (root, scope_name, sorted(set(reads[root]))[:4], name))

    findings.sort(key=lambda f: (f.line, f.kind))
    return {"findings": findings, "exempt": exempt}


def scan_verify_scripts(scripts_dir: str | os.PathLike | None = None, *,
                        pattern: str = "verify_*.py",
                        allowlist: frozenset[tuple[str, str, str]] = LEGACY_KNOWN_OFFENDERS,
                        statuses: dict[tuple[str, str, str], LegacyOffenderStatus]
                        = LEGACY_OFFENDER_STATUSES,
                        ) -> dict:
    """扫整个 `scripts\\` 下的 `verify_*.py`，区分**新越界**与**已登记遗留**。

    * `new`：不在 `allowlist` 里的发现 ⇒ **策略违例**（`ok=False`）；
    * `legacy_hits` / `legacy_absent`：已登记遗留项仍在 / 已被修掉；
    * `exempt`：显式豁免（带理由，列出但不判违例）；
    * `unreadable`：扫不了的脚本（**不算通过**，进 `new`）。

    刻意**不**因为「遗留项被修好了」而失败：修掉遗留只会让 `legacy_absent` 变长。

    **状态位（`LEGACY_OFFENDER_STATUSES`，只影响报告、不影响 `ok`/`new`）**：

    * `legacy_fixed_absent`：状态 = `fixed` 且当前**不再命中** ⇒ 这才是「曾经越界、现已修复」；
    * `legacy_never_offended_absent`：状态 = `never_offended` 且未命中 ⇒ 只是「没出现」；
    * `legacy_regressed`：状态 = `fixed` 却**又命中**了 ⇒ 证明「已修」**不是永久豁免**
      （它同时照旧出现在 `legacy_hits` 里 —— 这一条语义未改）；
    * `legacy_status_missing` / `legacy_status_ok`：状态表与 allowlist 对不上时**如实降级**
      （不抛、不改 `ok`，但 `legacy_status_ok=False` 且缺哪几条一并列出）。
    """
    base = pathlib.Path(scripts_dir) if scripts_dir is not None \
        else pathlib.Path(__file__).resolve().parents[2] / "scripts"
    findings: list[Finding] = []
    exempt: list[dict] = []
    scanned: list[str] = []
    for p in sorted(base.glob(pattern)):
        r = scan_verify_source(p)
        findings.extend(r["findings"])
        exempt.extend([{**e, "script": p.name} for e in r["exempt"]])
        scanned.append(p.name)
    new = [f for f in findings if f.key not in allowlist]
    legacy_hits = [f for f in findings if f.key in allowlist]
    hit_keys = {f.key for f in legacy_hits}

    def _status_of(key: tuple[str, str, str]) -> str:
        s = statuses.get(key)
        return s.status if s is not None else ""

    gaps = legacy_status_gaps(allowlist, statuses)
    return {"dir": str(base), "n_scanned": len(scanned), "scanned": tuple(scanned),
            "findings": tuple(findings), "new": tuple(new),
            "legacy_hits": tuple(legacy_hits),
            "legacy_absent": tuple(sorted(allowlist - hit_keys)),
            "exempt": tuple(exempt), "allowlist": allowlist, "ok": not new,
            # ---- 状态位：「曾经越界、现已修复」vs「从未越界」（现算，非字面量）----
            "legacy_statuses": dict(statuses),
            "legacy_fixed_absent": tuple(k for k in sorted(allowlist - hit_keys)
                                         if _status_of(k) == LEGACY_STATUS_FIXED),
            "legacy_never_offended_absent": tuple(
                k for k in sorted(allowlist - hit_keys)
                if _status_of(k) == LEGACY_STATUS_NEVER_OFFENDED),
            "legacy_regressed": tuple(sorted(k for k in hit_keys
                                             if _status_of(k) == LEGACY_STATUS_FIXED)),
            "legacy_status_missing": tuple(gaps["missing"]),
            "legacy_status_gaps": gaps,
            "legacy_status_ok": gaps["ok"]}
