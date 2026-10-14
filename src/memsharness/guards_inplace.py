# -*- coding: utf-8 -*-
"""就地编辑守卫：**改既有文件之前先备份**（fail-closed）＋「读+写同一路径」静态清单。

## 事故背景（本仓会话内两次实测，见 `INDEX §109` / `§130.3`）

* **前科 A**（`§109`）：`work/runs/paper-evidence-20261009/` 被**就地重生成 3 次** ⇒ 旧字节**不可恢复**；
* **前科 B**（`§130.3`）：`docs/INJECTION_SOLVER_AUTOMATION_MERGED_20261008.md` 就地改述**事前未备份**
  ⇒ 旧 sha256 `d47edaae…` 从此指向**不存在的字节**（`§130.2` 原话：「改前版本是否可恢复 = **不可**」）。

对比之下，`scripts/append_record_section.py` / `scripts/append_record_locked.py` **自带**
`work/logs/*.bak` 备份；**临时的就地编辑没有任何备份** —— 本模块补的就是这一处。

## 本模块给两件东西

1. **`backup_before_edit(path)`**：把目标文件**改前的字节**复制到 `work/logs/<name>.<ts>.bak`，
   返回一条记录（第 0 项 = **备份文件的 sha256**，也就是**改前字节的 sha256**）。
   三条 **fail-closed 拒绝**（拒绝即**不得继续编辑**）：
   * 目标**不存在**（或为目录）；目标为**空**（0 字节或仅空白）；
   * 备份目录**不可写 / 建不出来**（`OSError`）；
   * 备份**没有真的落盘**、或落盘内容与源不符（写后**独立复读复核**）。
2. **`scan_inplace_writers(roots)`**：扫 `work/tools/` 与 `scripts/` 下**读+写同一路径**的脚本，
   若在**写之前**没有调用备份、也没有 `INPLACE-ALLOW: <理由>` 显式豁免 ⇒ 报进清单。
   **只报不修**（本轮只保证「新写的能拦住」）。

## 「状态字段不得是字面量」（`INDEX §119` 教训）

本模块**不打印硬编码的 `ok`**：所有判定字段都由**测量**算出 —— 例如
`bak_sha256 == src_sha256`、`bak_bytes == src_bytes`、`bak_path.exists()`、
`backed_up = bool(evidence)`。`verdict` 也是由「有没有证据、证据是什么、证据在第几行」推导出来的。

## 为什么放在 `src/memsharness/`

本仓既有守卫一律是 `src/memsharness/guards_*.py`（`guards_readonly` / `guards_denominator` /
`guards_envfacts` / `guards_metatest` / `guards_indexlock`），用例一律 `tests/test_guards_*.py`。
就地备份要被 `scripts/` 下的脚本与未来的 runner **共用**，放包内才 import 得到；
`work/tools/` 属运行区（`work/` 被 gitignore），放那里**不进版本库**，不适合当守卫的家。
"""
from __future__ import annotations

import argparse
import ast
import datetime as _dt
import hashlib
import pathlib
import re
import sys
import warnings
from typing import Iterable, NamedTuple

from .paths import repo_root

__all__ = [
    "INPLACE_ALLOW_MARKER",
    "InplaceEditRefused",
    "InplaceBackup",
    "Finding",
    "sha256_file",
    "sha256_bytes",
    "default_log_dir",
    "backup_before_edit",
    "scan_inplace_writers",
    "format_findings",
    "main",
]

#: 显式豁免标记（必须**带理由**才算豁免）：形如 `# INPLACE-ALLOW: 本处只写新建文件，无既有字节`
INPLACE_ALLOW_MARKER = "INPLACE-ALLOW:"

#: 豁免理由的**最小长度**（短于它视为「没写理由」⇒ 不豁免，仍报出）
_MIN_REASON_CHARS = 4


def _is_blank(data: bytes) -> bool:
    """「为空」= 0 字节，或去掉空白后为空。"""
    return (not data) or (not data.strip())


class InplaceEditRefused(RuntimeError):
    """拒绝就地编辑（fail-closed）：没有可信的改前备份就不许动既有文件。"""


class InplaceBackup(NamedTuple):
    """`backup_before_edit()` 的结果。

    第 0 项 `sha256` = **备份文件的 sha256**；因为备份在写之前生成，它同时也是
    **改前字节的 sha256**（`src_sha256`）—— 「两者相等」这件事是被**复核**过的：
    `backup_before_edit()` 会把盘上的备份**重新读出来现算一遍**，而不是相信写入调用的返回值。
    """

    sha256: str
    bak_path: pathlib.Path
    bytes: int
    src_path: pathlib.Path
    src_sha256: str
    src_bytes: int
    log_dir: pathlib.Path
    existed_before: bool


# --------------------------------------------------------------------------- 基础工具
def sha256_bytes(data: bytes) -> str:
    """字节串的 sha256（十六进制小写）。"""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | pathlib.Path, bufsize: int = 1 << 20) -> str:
    """文件字节的 sha256（分块读，避免把大文件整个读进内存）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(bufsize)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def default_log_dir(repo: str | pathlib.Path | None = None) -> pathlib.Path:
    """备份目录：`<repo>/work/logs`（与两个既有追加器的备份落点一致）。"""
    base = pathlib.Path(repo) if repo is not None else repo_root()
    return base / "work" / "logs"


def _write_backup_bytes(bak_path: pathlib.Path, data: bytes) -> None:
    """把改前字节写到备份路径（单独成函数 ⇒ 测试可注入「假装成功但没写」）。"""
    with open(bak_path, "wb") as f:
        f.write(data)


def _pick_bak_path(log_dir: pathlib.Path, template: str, src: pathlib.Path,
                   ts: str, data: bytes) -> pathlib.Path:
    """挑一个**不覆盖既有备份**的名字。

    * 同名备份已存在且内容与源**逐字节相同** ⇒ 直接复用（幂等：同一秒内重试不增生备份）；
    * 同名备份存在但内容不同 ⇒ 加 `-2`/`-3`… 后缀（**绝不覆盖**别人的备份）；
    * 都不存在 ⇒ 用原名。
    """
    base = template.format(name=src.name, stem=src.stem, ts=ts)
    cand = log_dir / base
    if not cand.exists():
        return cand
    try:
        if cand.read_bytes() == data:
            return cand
    except OSError:
        pass
    for i in range(2, 1000):
        alt = log_dir / ("%s-%d" % (base, i))
        if not alt.exists():
            return alt
    raise InplaceEditRefused("备份名冲突过多（%s）⇒ 拒绝继续编辑" % base)


def backup_before_edit(path: str | pathlib.Path, *,
                       log_dir: str | pathlib.Path | None = None,
                       name_template: str = "{name}.{ts}.bak",
                       now: _dt.datetime | None = None,
                       repo: str | pathlib.Path | None = None) -> InplaceBackup:
    """**就地改既有文件之前**先备份改前字节；返回备份记录（第 0 项 = 备份 sha256）。

    参数
    ----
    path          要被就地修改的既有文件（**必须已存在且非空**）
    log_dir       备份落点；缺省 `<repo>/work/logs`
    name_template 备份文件名模板，占位符 `{name}`（全名）/`{stem}`（去后缀）/`{ts}`；
                  缺省 `"{name}.{ts}.bak"` —— 即「`<name>.<ts>.bak`」这条要求。
                  （`scripts/append_record_section.py` 传 `"{stem}.{ts}.md.bak"`，
                  因为它那份备份名被 6 个既有用例逐字锁住，见 `tests/test_append_record_section_guard.py`。）
    now           注入用的当前时间（测试固定时间戳 ⇒ 产物可复现）
    repo          仓库根（缺省 `memsharness.paths.repo_root()`）

    拒绝条件（**抛 `InplaceEditRefused`，调用方必须视为「不许编辑」**）
    ---------------------------------------------------------------
    1. 目标不存在 / 是目录 / 读不出；
    2. 目标为空（0 字节或仅空白）；
    3. 备份目录建不出或不可写（`OSError`）；
    4. **写完之后独立复读**：备份不存在、字节数不符、或 sha256 与源不符。
       第 4 条专门拦「备份函数假装成功但没写文件」这类**沉默失败**。
    """
    src = pathlib.Path(path)
    if not src.exists():
        raise InplaceEditRefused(
            "目标不存在：%s ⇒ 拒绝（没有可备份的改前字节，fail-closed）" % src)
    if src.is_dir():
        raise InplaceEditRefused("目标是目录，不是文件：%s ⇒ 拒绝" % src)
    try:
        data = src.read_bytes()
    except OSError as exc:
        raise InplaceEditRefused(
            "读不出目标 %s（%s: %s）⇒ 拒绝" % (src, type(exc).__name__, exc)) from exc
    if _is_blank(data):
        raise InplaceEditRefused(
            "目标为空/仅空白（%d B）：%s ⇒ 拒绝（空文件没有可保护的改前内容）"
            % (len(data), src))

    src_sha = sha256_bytes(data)
    ld = pathlib.Path(log_dir) if log_dir is not None else default_log_dir(repo)
    stamp = (now or _dt.datetime.now()).strftime("%Y%m%dT%H%M%S")

    try:
        ld.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InplaceEditRefused(
            "备份目录建不出来（%s: %s）：%s ⇒ 拒绝继续编辑（fail-closed）"
            % (type(exc).__name__, exc, ld)) from exc
    if not ld.is_dir():
        raise InplaceEditRefused("备份落点不是目录：%s ⇒ 拒绝继续编辑" % ld)

    bak = _pick_bak_path(ld, name_template, src, stamp, data)
    existed = bak.exists()
    if not existed:
        try:
            _write_backup_bytes(bak, data)
        except OSError as exc:
            raise InplaceEditRefused(
                "备份写不进去（%s: %s）：%s ⇒ 拒绝继续编辑（fail-closed，不得先改后补）"
                % (type(exc).__name__, exc, bak)) from exc

    # ---- 写后独立复读复核：不信「函数返回了就算写成功」
    if not bak.exists():
        raise InplaceEditRefused(
            "备份**没有落盘**（%s 不存在）⇒ 拒绝继续编辑"
            "（这是「假装成功」类沉默失败的兜底拦截）" % bak)
    try:
        got_bytes = bak.stat().st_size
        got_sha = sha256_file(bak)
    except OSError as exc:
        raise InplaceEditRefused(
            "备份存在但读不出（%s: %s）：%s ⇒ 拒绝继续编辑"
            % (type(exc).__name__, exc, bak)) from exc
    if got_bytes != len(data) or got_sha != src_sha:
        raise InplaceEditRefused(
            "备份内容与改前字节**不符**（备份 %d B/%s，源 %d B/%s）：%s ⇒ 拒绝继续编辑"
            % (got_bytes, got_sha[:16], len(data), src_sha[:16], bak))

    return InplaceBackup(sha256=got_sha, bak_path=bak, bytes=got_bytes,
                         src_path=src, src_sha256=src_sha, src_bytes=len(data),
                         log_dir=ld, existed_before=existed)


# --------------------------------------------------------------------------- 静态清单
class Finding(NamedTuple):
    """一处「读+写同一路径」的判定。`verdict` 由**证据**推出，不是写死的。"""

    path: str          # 相对扫描根的脚本路径
    lineno: int        # 写操作所在行
    scope: str         # 所在函数（模块级为 `<module>`）
    target: str        # 被读又被写的路径表达式（源码原文）
    verdict: str       # unbacked / exempt / backup_call / copy_to_bak / unparsed
    detail: str        # 含「哪一行读的」等**实测**信息


_READ_ATTRS = {"read_text", "read_bytes"}
_WRITE_ATTRS = {"write_text", "write_bytes"}
_COPY_FUNCS = {"copy", "copy2", "copyfile", "copyfileobj"}
_BACKUP_NAME_RE = re.compile(r"(?i)backup")
_BAK_HINT_RE = re.compile(r"(?i)\.bak")
_WRITE_MODE_CHARS = "wax+"


def _callee_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _key(node: ast.AST) -> str:
    """路径表达式的**源码级**键（同键 = 同一个路径对象；不做别名/重命名推断，见 docstring）。"""
    try:
        return re.sub(r"\s+", " ", ast.unparse(node)).strip()
    except Exception:                                   # pragma: no cover - ast 兜底
        return "<?>"


def _open_mode(call: ast.Call, pos: int) -> tuple[str | None, bool]:
    """`open(path, mode)`（pos=1）/ `path.open(mode)`（pos=0）的 mode。

    返回 `(mode 字面量 or None, 是否给了 mode 但读不出字面量)`：

    * **没给** mode ⇒ `("r", False)`（Python 默认是文本读，不是写）；
    * 给了**字面量** ⇒ `(字面量, False)`；
    * 给了**非字面量**（变量/表达式）⇒ `(None, True)` ⇒ 判定不出，按写处理（fail-closed）。
    """
    if len(call.args) > pos:
        if isinstance(call.args[pos], ast.Constant) and isinstance(call.args[pos].value, str):
            return call.args[pos].value, False
        return None, True
    for kw in call.keywords:
        if kw.arg == "mode":
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                return kw.value.value, False
            return None, True
    return "r", False


def _is_write_mode(mode: str | None, unknown: bool) -> bool:
    return bool(unknown) or any(c in (mode or "") for c in _WRITE_MODE_CHARS)


def _is_read_mode(mode: str | None, unknown: bool) -> bool:
    return (not unknown) and ("r" in (mode or "")) \
        and not any(c in (mode or "") for c in _WRITE_MODE_CHARS)


def _classify(call: ast.Call,
              aliases: dict[str, str]) -> tuple[str, str, ast.AST] | None:
    """认出「读」/「写」⇒ `(kind, 键, 路径表达式)`；都不像 ⇒ None。

    覆盖：`X.read_text/read_bytes/write_text/write_bytes`、`open(p, mode)`、
    `Path(p).open(mode)`、`os.replace(src, dst)`、`shutil.copy*(src, dst)`、
    `f.write(...)`（`f` 由 `f = open(...)` 绑定）。
    """
    fn = call.func
    name = _callee_name(fn)
    if isinstance(fn, ast.Attribute) and name in _READ_ATTRS:
        return "read", _key(fn.value), fn.value
    if isinstance(fn, ast.Attribute) and name in _WRITE_ATTRS:
        return "write", _key(fn.value), fn.value
    if isinstance(fn, ast.Attribute) and name in _COPY_FUNCS and len(call.args) >= 2:
        return "write", _key(call.args[1]), call.args[1]
    if isinstance(fn, ast.Attribute) and name == "replace" and len(call.args) >= 1:
        inner = fn.value
        if isinstance(inner, ast.Call) and _callee_name(inner.func) == "open":
            return "write", _key(call.args[0]), call.args[0]
    if isinstance(fn, ast.Attribute) and name == "open":
        mode, unknown = _open_mode(call, 0)
        if _is_write_mode(mode, unknown):
            return "write", _key(fn.value), fn.value
        if _is_read_mode(mode, unknown):
            return "read", _key(fn.value), fn.value
        return None
    if name == "open" and call.args:
        mode, unknown = _open_mode(call, 1)
        if _is_write_mode(mode, unknown):
            return "write", _key(call.args[0]), call.args[0]
        if _is_read_mode(mode, unknown):
            return "read", _key(call.args[0]), call.args[0]
        return None
    if isinstance(fn, ast.Attribute) and name in ("write", "read") \
            and isinstance(fn.value, ast.Name) and fn.value.id in aliases:
        return ("write" if name == "write" else "read"), \
            aliases[fn.value.id], fn.value
    return None


class _ScopeFacts:
    """一个作用域（函数或模块顶）里收集到的事实。"""

    def __init__(self, name: str, node: ast.AST) -> None:
        self.name = name
        self.node = node
        self.reads: list[tuple[int, str]] = []
        self.writes: list[tuple[int, str]] = []
        self.backup_calls: list[tuple[int, str, str]] = []   # (行, 被调名, 路径键)
        self.copy_backups: list[tuple[int, str]] = []        # (行, 源路径键)
        self.bak_names: set[str] = set()                     # 变量名 ⇒ 值里含 `.bak`
        self.helper_writes: list[tuple[int, str, str]] = []  # (行, 路径键, helper 说明)


def _path_writer_params(tree: ast.AST) -> dict[str, dict[str, int]]:
    """同文件里「**会写自己某个形参**」的函数 ⇒ `{函数名: {形参名: 位置}}`。

    **为什么需要这条轻量跨函数规则**：真正的就地写经常被封在 helper 里
    （`_write_and_readback(path, text)`、`_atomic_write(path, data)`、`dump(path, obj)`）
    ⇒ 只看调用点会**漏掉**它。规则刻意保守：只认「形参**直接**出现在写操作的目标位置」
    的函数，与函数命名无关；参数经过拼接/重赋值后不再追踪（宁可漏报，不猜测）。
    """
    out: dict[str, dict[str, int]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names = [a.arg for a in list(getattr(fn.args, "posonlyargs", []))
                 + list(fn.args.args)]
        hits: dict[str, int] = {}
        for call in ast.walk(fn):
            if not isinstance(call, ast.Call):
                continue
            c = _classify(call, {})
            if c is None or c[0] != "write":
                continue
            if c[1] in names and c[1] not in hits:
                hits[c[1]] = names.index(c[1])
        if hits:
            out.setdefault(fn.name, {}).update(hits)
    return out


def _collect(path: pathlib.Path, root: pathlib.Path, label_base: pathlib.Path) \
        -> list[Finding]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [Finding(path=_label(path, root, label_base), lineno=0, scope="<file>",
                        target="", verdict="unparsed",
                        detail="读不出/非 UTF-8：%s: %s" % (type(exc).__name__, exc))]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)   # 别人脚本里的转义告警不该刷屏
            tree = ast.parse(text)
    except SyntaxError as exc:
        return [Finding(path=_label(path, root, label_base), lineno=exc.lineno or 0,
                        scope="<file>", target="", verdict="unparsed",
                        detail="AST 解析失败（不猜）：%s" % exc.msg)]
    lines = text.splitlines()
    path_writers = _path_writer_params(tree)

    scopes: list[_ScopeFacts] = []
    module_scope = _ScopeFacts("<module>", tree)
    scopes.append(module_scope)

    def walk(node: ast.AST, scope: _ScopeFacts) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = _ScopeFacts(node.name, node)
            scopes.append(scope)
        aliases: dict[str, str] = {}
        for child in ast.iter_child_nodes(node):
            # ① `f = open(x, "w")` / `f = Path(x).open("w")` ⇒ 记住别名
            if isinstance(child, ast.Assign) and isinstance(child.value, ast.Call):
                callee = _callee_name(child.value.func)
                par = None
                if callee == "open":
                    if isinstance(child.value.func, ast.Attribute):
                        par = child.value.func.value          # `X.open(mode)`：路径在接收者
                    elif child.value.args:
                        par = child.value.args[0]             # `open(path, mode)`
                if par is not None:
                    for tgt in child.targets:
                        if isinstance(tgt, ast.Name):
                            aliases[tgt.id] = _key(par)
            # ② `bk = REPO/"work/logs"/("x.%s.md.bak" % ts)` ⇒ 记住这是「备份名变量」
            #    注意：值常常是 BinOp 而不是 Call ⇒ 这一条**不能**挂在上面那个 if 里面
            if isinstance(child, ast.Assign) and _BAK_HINT_RE.search(ast.unparse(child.value)):
                for tgt in child.targets:
                    if isinstance(tgt, ast.Name):
                        scope.bak_names.add(tgt.id)
            if isinstance(child, ast.Call):
                c = _classify(child, aliases)
                if c is not None:
                    kind, key, _expr = c
                    (scope.writes if kind == "write" else scope.reads).append(
                        (child.lineno, key))
                # ③ 调用「会写自己形参」的同文件 helper ⇒ 那个实参就是写目标
                if isinstance(child.func, ast.Name) and child.func.id in path_writers:
                    for pname, pos in path_writers[child.func.id].items():
                        if len(child.args) > pos:
                            scope.writes.append((child.lineno, _key(child.args[pos])))
                            scope.helper_writes.append(
                                (child.lineno, _key(child.args[pos]),
                                 "%s(…%s…)" % (child.func.id, pname)))
                callee = _callee_name(child.func)
                if _BACKUP_NAME_RE.search(callee):
                    key = _key(child.args[0]) if child.args else ""
                    scope.backup_calls.append((child.lineno, callee, key))
                if callee in _COPY_FUNCS and len(child.args) >= 2:
                    dst = ast.unparse(child.args[1])
                    dst_names = {n.id for n in ast.walk(child.args[1])
                                 if isinstance(n, ast.Name)}
                    if _BAK_HINT_RE.search(dst) or (dst_names & scope.bak_names):
                        scope.copy_backups.append((child.lineno, _key(child.args[0])))
            walk(child, scope)

    walk(tree, module_scope)

    def scope_src(sc: _ScopeFacts) -> str:
        n = getattr(sc.node, "lineno", 1) or 1
        m = getattr(sc.node, "end_lineno", len(lines)) or len(lines)
        return "\n".join(lines[max(0, n - 1):m])

    findings: list[Finding] = []
    rel = _label(path, root, label_base)
    for sc in scopes:
        allow_reason = ""
        for ln in scope_src(sc).splitlines():
            i = ln.find(INPLACE_ALLOW_MARKER)
            if i >= 0:
                cand = ln[i + len(INPLACE_ALLOW_MARKER):].strip()
                if len(cand) >= _MIN_REASON_CHARS:
                    allow_reason = cand
                    break
        reads_by_key: dict[str, int] = {}
        for rline, rkey in sc.reads:
            reads_by_key.setdefault(rkey, rline)          # 取最早一次读
        for wline, wkey in sc.writes:
            if wkey not in reads_by_key:
                continue                                   # 没被读过 ⇒ 不是「就地改」
            rline = reads_by_key[wkey]
            order = "读在写之前（就地改的典型形态）" if rline < wline else "读在写之后"
            evidence: list[str] = []
            canonical = [(ln, nm) for ln, nm, key in sc.backup_calls
                         if ln < wline and nm == "backup_before_edit" and key == wkey]
            named = [(ln, nm) for ln, nm, key in sc.backup_calls
                     if ln < wline and nm != "backup_before_edit" and key == wkey]
            copies = [ln for ln, srckey in sc.copy_backups if ln < wline and srckey == wkey]
            if canonical:
                evidence.append("backup_before_edit @L%d" % canonical[0][0])
            if named:
                evidence.append("备份调用 %s @L%d" % (named[0][1], named[0][0]))
            if copies:
                evidence.append("shutil 复制到 *.bak @L%d" % copies[0])
            late = [ln for ln, _nm, key in sc.backup_calls if ln > wline and key == wkey]
            if allow_reason:
                verdict = "exempt"
                detail = "显式豁免理由：%s" % allow_reason
            elif evidence:
                verdict = "backup_call" if (canonical or named) else "copy_to_bak"
                detail = "写前已有备份证据（%s）" % "；".join(evidence)
            else:
                verdict = "unbacked"
                detail = "写之前**没有**备份调用、也没有 `%s <理由>` 豁免" % INPLACE_ALLOW_MARKER
                if late:
                    detail += "（备份调用在写之后 @L%d ⇒ 不算「写前备份」）" % late[0]
            findings.append(Finding(path=rel, lineno=wline, scope=sc.name,
                                    target=wkey,
                                    verdict=verdict,
                                    detail="%s；该路径在 L%d 被读（%s）%s"
                                           % (detail, rline, order, _helper_note(sc, wline, wkey))))
    return findings


def _helper_note(sc: "_ScopeFacts", wline: int, wkey: str) -> str:
    """若这次写是经「同文件 helper」发生的，补一句说明（便于人工核对该 helper）。"""
    for line, key, how in sc.helper_writes:
        if line == wline and key == wkey:
            return "；写经 helper `%s`" % how
    return ""


def _label(path: pathlib.Path, root: pathlib.Path, label_base: pathlib.Path) -> str:
    """报告里用的路径：能相对仓库根就相对仓库根，否则相对扫描根。"""
    for base in (label_base, root):
        try:
            return str(path.relative_to(base))
        except ValueError:
            continue
    return str(path)


#: 只在**写之前**有备份/豁免证据才算数（顺序敏感，见 `_collect` 的 `ln < wline`）
SCAN_VERDICTS = ("unbacked", "copy_to_bak", "backup_call", "exempt", "unparsed")


def scan_inplace_writers(roots: Iterable[str | pathlib.Path] | None = None, *,
                         repo: str | pathlib.Path | None = None) -> list[Finding]:
    """扫「读+写同一路径」的脚本，返回**全部**判定（含已备份/已豁免的，便于复核）。

    缺省根 = `<repo>/scripts` 与 `<repo>/work/tools`。**只报不修**。
    """
    base = pathlib.Path(repo) if repo is not None else repo_root()
    root_list = [pathlib.Path(r) for r in roots] if roots is not None \
        else [base / "scripts", base / "work" / "tools"]
    out: list[Finding] = []
    for root in root_list:
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            out.extend(_collect(p, root, base))
    return out


def format_findings(findings: Iterable[Finding]) -> str:
    """把判定渲染成可读清单（先报 `unbacked`，再列其余，便于「只报不修」对齐）。"""
    fs = list(findings)
    unbacked = [f for f in fs if f.verdict == "unbacked"]
    order = {"unbacked": 0, "unparsed": 1, "copy_to_bak": 2, "backup_call": 3, "exempt": 4}
    lines = ["就地改（读+写同一路径）静态清单：共 %d 处判定，其中**未备份 %d 处**（只报不修）"
             % (len(fs), len(unbacked))]
    for f in sorted(fs, key=lambda x: (order.get(x.verdict, 9), x.path, x.lineno)):
        lines.append("  [%s] %s:%d（%s）目标 `%s` —— %s"
                     % (f.verdict, f.path, f.lineno, f.scope, f.target, f.detail))
    if not fs:
        lines.append("  （扫描根下没有「读+写同一路径」的脚本）")
    return "\n".join(lines)


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    """`python -X utf8 -m memsharness.guards_inplace backup|scan`。"""
    ap = argparse.ArgumentParser(description="就地编辑守卫：默认先备份 + 静态清单")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("backup", help="就地改之前先备份（失败即拒绝）")
    b.add_argument("path")
    b.add_argument("--log-dir", default=None)
    b.add_argument("--repo", default=None)

    s = sub.add_parser("scan", help="列出「读+写同一路径」的脚本（只报不修）")
    s.add_argument("--root", action="append", default=None)
    s.add_argument("--repo", default=None)
    s.add_argument("--strict", action="store_true",
                   help="存在未备份判定时以 rc=3 退出（缺省只打印、rc=0）")

    a = ap.parse_args(argv)
    if a.cmd == "backup":
        try:
            rec = backup_before_edit(a.path, log_dir=a.log_dir, repo=a.repo)
        except InplaceEditRefused as exc:
            print("[REFUSED] %s" % exc, file=sys.stderr)
            return 2
        print("[OK] 改前备份已落盘：%s（%d B，sha256 %s）"
              % (rec.bak_path, rec.bytes, rec.sha256))
        print("     源文件：%s（%d B，sha256 %s）"
              % (rec.src_path, rec.src_bytes, rec.src_sha256))
        # 「状态字段不得是字面量」：这里的 True/False 是现算的比较结果
        print("     复核：备份与源逐字节一致 = %s；备份是复用既有文件 = %s"
              % (rec.sha256 == rec.src_sha256 and rec.bytes == rec.src_bytes,
                 rec.existed_before))
        return 0

    findings = scan_inplace_writers(a.root, repo=a.repo)
    print(format_findings(findings))
    n_unbacked = sum(1 for f in findings if f.verdict == "unbacked")
    if a.strict and n_unbacked:
        print("[STRICT] 未备份 %d 处 ⇒ rc=3" % n_unbacked, file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":                                   # pragma: no cover
    sys.exit(main())
