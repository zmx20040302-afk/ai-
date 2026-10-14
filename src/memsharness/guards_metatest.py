# -*- coding: utf-8 -*-
"""**可失败性元测试**：给「检查器」投毒，证明它**真的会失败**。

## 为什么需要它（同一类事故在本仓库发生过三次）

`docs\\INDEX-records-and-rulings.md` 实测登记过三次「我写的门禁自己不可靠」：

1. 校验脚本里写了 `n_prod == 0 or True` —— **恒真**，必然打印「一致」却什么都没检查
   （索引行 4307，§90 段第 5 条）；
2. 期望值写成**通配**（与 `"*"` 比较、或 `fnmatch(..., "*")`）⇒ 比对必然成立，同上；
3. 初版扫描器按 `node.args` 找 `sys.executable`，而 argv 是**列表字面量**
   （`[sys.executable, …]`）⇒ 永远匹配不到 ⇒ **永远不会失败**
   （`tests\\test_subprocess_encoding.py` 行 119 的原话：「守卫的守卫」）。

这类缺陷**不会被常规用例抓住**：常规用例只喂「正常输入」，检查器返回「无问题」
既可能是「真的没问题」，也可能是「它根本不看」。本模块用**投毒**把两者分开：

    同一检查器，干净输入 ⇒ **不得**报错；必然不一致的输入 ⇒ **必须**报错。
    任一侧不成立 ⇒ 该检查器**不可失败**（`NotFalsifiable`）⇒ 元测试失败。

只做「必须报错」这一侧是不够的：一个**恒假**的检查器（无脑报错）能轻松骗过投毒测试，
所以干净输入那一侧同样钉死。

## 契约（任何新写的校验/断言函数挂上来只需满足它）

* 签名固定为 **`checker(payload)`**：单参数，payload 由**工厂函数**构造
  （工厂而不是值，是为了每个用例拿到干净、互不污染的数据）；
* 返回值语义（`reports_problem()`，逐条实现）：
  * `None` / `True` / 空串 / 空白串 / 空列表·元组·集合 / 无问题键的 `{"ok": True}` ⇒ **无问题**；
  * `False` / 非空串 / 非空容器 / `{"problems": [...]}` 非空（`fails|errors|violations` 同义）
    / `{"ok": False}` ⇒ **报错**；
  * **抛出 `Exception`** ⇒ 记为**报错**（`reported=True`，信息里带类型与原文）；
  * **其它类型**（如裸数字、含义不明的非空字典）⇒ `CheckerContractError`
    —— **不猜**：契约不明的检查器既不判通过也不判失败，直接让元测试失败；
  * `KeyboardInterrupt` / `SystemExit` 直接向上冒（那是中断，不是判定）。

## 挂载

`REGISTRY` 里的每一件都会被 `tests\\test_guards_metatest.py` **逐件**投毒。本模块自带
2 个示例挂载（哈希比对器 / 计数一致性检查器）；跨模块示例（分母纪律、目录只读快照、
环境事实时间戳）在测试文件里用 `register()` 挂上 —— 新校验函数照抄那几行即可。
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import pathlib
from collections.abc import Callable, Iterable, Mapping, Sized
from dataclasses import dataclass
from typing import Any

__all__ = [
    "CheckerContractError", "NotFalsifiable", "PoisonCase", "CheckerMount",
    "reports_problem", "evaluate", "falsifiability_report", "assert_falsifiable",
    "mount", "register", "registry", "clear_registry",
    "hash_compare", "counts_consistent", "builtin_mounts",
    "find_tautology_smells", "TAUTOLOGY_KINDS",
]

#: 字典返回值里表示「问题清单」的键（任一命中即按清单判）
_PROBLEM_KEYS = ("problems", "fails", "errors", "violations")
#: 字典返回值里表示「总体判定」的键
_VERDICT_KEYS = ("ok", "passed", "fine", "consistent")


class CheckerContractError(TypeError):
    """检查器的返回值不在约定内 —— **不猜**，元测试直接失败。"""


class NotFalsifiable(AssertionError):
    """检查器在投毒输入上不报错，或（反过来）在干净输入上报错 ⇒ 不可失败。"""


def _clip(text: object, cap: int = 240) -> str:
    s = "" if text is None else str(text)
    return s if len(s) <= cap else s[:cap] + "…"


# --------------------------------------------------------------------------- 判定语义
def reports_problem(result: Any) -> tuple[bool, str]:
    """把检查器返回值翻译成（是否报错, 依据）。契约不明 ⇒ `CheckerContractError`。"""
    if isinstance(result, bool):
        return (not result), ("显式返回 %s" % result)
    if result is None:
        return False, "返回 None（无问题）"
    if isinstance(result, str):
        return bool(result.strip()), "返回字符串 %r" % _clip(result)
    if isinstance(result, Mapping):
        for key in _PROBLEM_KEYS:
            if key in result:
                v = result[key]
                n = len(v) if isinstance(v, Sized) else (1 if v else 0)
                return bool(n), "键 %r 有 %d 项" % (key, n)
        for key in _VERDICT_KEYS:
            if key in result:
                v = result[key]
                if isinstance(v, bool):
                    return (not v), "键 %r = %s" % (key, v)
                raise CheckerContractError(
                    "字典键 %r 的值不是布尔：%r（不猜）" % (key, _clip(v, 60)))
        raise CheckerContractError(
            "字典返回值里既没有 %s 也没有 %s ⇒ 判定不明（不猜）：键=%s"
            % ("/".join(_PROBLEM_KEYS), "/".join(_VERDICT_KEYS),
               sorted(str(k) for k in result)[:8]))
    if isinstance(result, (list, tuple, set, frozenset)):
        return len(result) > 0, "容器有 %d 项" % len(result)
    raise CheckerContractError(
        "返回值类型不在契约内：%s（合法：None/bool/str/容器/带 %s 的字典）"
        % (type(result).__name__, "|".join(_PROBLEM_KEYS)))


def evaluate(checker: Callable[[Any], Any], payload: Any) -> dict:
    """跑一次检查器，返回**结构化**结果（不抛异常，异常也被记成一次「报错」）。

    返回键：
    * `reported`：True=报错 / False=无问题 / **None=契约不明**（调用方必须当成失败）；
    * `detail`：判定依据（中文，可直接进报告）；
    * `raised`：若抛出异常，这里是 `类型: 原文`；
    * `result_repr`：返回值摘要（裁剪到 240 字符）。
    """
    try:
        result = checker(payload)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # noqa: BLE001 —— 检查器抛异常 = 报错，这是契约的一部分
        return {"reported": True, "detail": "抛出 %s" % type(exc).__name__,
                "raised": "%s: %s" % (type(exc).__name__, _clip(exc)), "result_repr": ""}
    try:
        reported, detail = reports_problem(result)
    except CheckerContractError as exc:
        return {"reported": None, "detail": str(exc), "raised": None,
                "result_repr": _clip(repr(result)), "contract_error": str(exc)}
    return {"reported": reported, "detail": detail, "raised": None,
            "result_repr": _clip(repr(result))}


# --------------------------------------------------------------------------- 挂载结构
@dataclass(frozen=True)
class PoisonCase:
    """一条投毒用例：`make()` 造出**必然不一致**的输入。"""

    name: str
    make: Callable[[], Any]
    note: str = ""


@dataclass(frozen=True)
class CheckerMount:
    """一个检查器的挂载点：干净输入 + 至少一条投毒输入。"""

    name: str
    checker: Callable[[Any], Any]
    clean: Callable[[], Any]
    poisons: tuple[PoisonCase, ...]
    doc: str = ""


def mount(name: str, checker: Callable[[Any], Any], clean: Callable[[], Any],
          poisons: Iterable[PoisonCase | tuple[str, Callable[[], Any]]],
          doc: str = "") -> CheckerMount:
    """构造一个挂载点（`poisons` 里的 `(名, 工厂)` 二元组会被自动包装成 `PoisonCase`）。"""
    cases: list[PoisonCase] = []
    for p in poisons:
        cases.append(p if isinstance(p, PoisonCase) else PoisonCase(p[0], p[1]))
    return CheckerMount(name=name, checker=checker, clean=clean,
                        poisons=tuple(cases), doc=doc)


#: 注册表（**有序**；测试逐件投毒）。跨模块挂载请用 `register()`。
REGISTRY: list[CheckerMount] = []


def register(entry: CheckerMount) -> CheckerMount:
    """登记一个挂载点；**同名重复登记直接拒绝**（免得后登记的悄悄盖掉前一个）。"""
    if any(e.name == entry.name for e in REGISTRY):
        raise ValueError("挂载点重名：%r（已登记：%s）"
                         % (entry.name, [e.name for e in REGISTRY]))
    REGISTRY.append(entry)
    return entry


def registry() -> tuple[CheckerMount, ...]:
    return tuple(REGISTRY)


def clear_registry() -> None:
    """清空注册表（测试夹具用；清空后调用 `builtin_mounts()` 可复位）。"""
    REGISTRY.clear()


# --------------------------------------------------------------------------- 元测试本体
def falsifiability_report(entry: CheckerMount) -> dict:
    """对一个挂载点做**两侧**检查，返回结构化结果与问题清单。

    * 干净输入上报错 ⇒ 问题（误报，检查器本身不成立）；
    * 任一投毒输入上不报错 ⇒ 问题（**假校验**：它在这个输入上什么都没检查）；
    * 契约不明（`reported is None`）⇒ 问题（不猜）；
    * **没有任何投毒用例** ⇒ 问题（无法证明可失败）。
    """
    problems: list[str] = []
    clean_ev = evaluate(entry.checker, entry.clean())
    if clean_ev["reported"] is None:
        problems.append("干净输入：契约不明 —— %s" % clean_ev["detail"])
    elif clean_ev["reported"]:
        problems.append("干净输入上**误报**（检查器不成立）：%s" % clean_ev["detail"])

    poison_rows: list[dict] = []
    if not entry.poisons:
        problems.append("没有提供任何投毒用例 ⇒ 无法证明该检查器可失败")
    for case in entry.poisons:
        try:
            payload = case.make()
        except Exception as exc:  # noqa: BLE001 —— 投毒输入自己造不出来也是问题
            poison_rows.append({"case": case.name, "reported": None,
                                "detail": "投毒输入构造失败：%s: %s"
                                          % (type(exc).__name__, _clip(exc))})
            problems.append("投毒用例 %r 构造失败：%s" % (case.name, _clip(exc)))
            continue
        ev = evaluate(entry.checker, payload)
        poison_rows.append({"case": case.name, "reported": ev["reported"],
                            "detail": ev["detail"], "raised": ev["raised"]})
        if ev["reported"] is None:
            problems.append("投毒用例 %r：契约不明 —— %s" % (case.name, ev["detail"]))
        elif not ev["reported"]:
            problems.append(
                "投毒用例 %r：**未报错** ⇒ 该检查器在这份必然不一致的输入上是**假校验**"
                "（判定依据：%s；返回值 %s）"
                % (case.name, ev["detail"], ev["result_repr"]))

    return {"name": entry.name, "doc": entry.doc, "clean": clean_ev,
            "poisons": tuple(poison_rows), "problems": tuple(problems),
            "falsifiable": not problems}


def assert_falsifiable(entry: CheckerMount) -> dict:
    """`falsifiability_report()` 的断言版：不可失败即抛 `NotFalsifiable`。"""
    rep = falsifiability_report(entry)
    if not rep["falsifiable"]:
        raise NotFalsifiable("检查器 %r 不可失败：\n  - %s"
                             % (entry.name, "\n  - ".join(rep["problems"])))
    return rep


# --------------------------------------------------------------------------- 示例挂载 ①
def hash_compare(payload: Mapping) -> list[str]:
    """**哈希比对器**（payload = `{"path":…, "expected_sha256":…[, "label":…]}`）。

    返回问题清单：缺文件 / 读不出 / sha256 不符。**不符时把两个哈希都写进问题文本**
    （只说「不一致」的报告没法用）。
    """
    label = str(payload.get("label") or payload.get("path") or "?")
    p = pathlib.Path(str(payload.get("path", "")))
    expected = str(payload.get("expected_sha256", "") or "").strip().lower()
    if not expected:
        return ["%s：期望 sha256 为空 —— 空期望与通配同类，一律判不合格" % label]
    if not p.is_file():
        return ["%s：文件不存在（%s）" % (label, p)]
    try:
        got = hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError as exc:
        return ["%s：读不出（%s: %s）" % (label, type(exc).__name__, exc)]
    if got != expected:
        return ["%s：sha256 不符 期望 %s 实得 %s" % (label, expected, got)]
    return []


class _LazyTmp:
    """**惰性**临时目录：import 本模块**不落任何盘**（工厂被调用时才建目录）。"""

    def __init__(self, root: pathlib.Path | None = None) -> None:
        self._root = root
        self._made: pathlib.Path | None = None

    def dir(self) -> pathlib.Path:
        if self._made is None:
            if self._root is None:
                import tempfile
                self._root = pathlib.Path(tempfile.mkdtemp(prefix="mems-guards-metatest-"))
            self._root.mkdir(parents=True, exist_ok=True)
            self._made = self._root
        return self._made


def _hash_clean_factory(tmp: _LazyTmp) -> Callable[[], Any]:
    def make() -> dict:
        f = tmp.dir() / "artifact.bin"
        f.write_bytes(b"MEMS-guard-demo\n")
        return {"path": f, "expected_sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
                "label": "artifact.bin"}
    return make


def _hash_poison_factory(tmp: _LazyTmp) -> Callable[[], Any]:
    def make() -> dict:
        f = tmp.dir() / "artifact.bin"
        f.write_bytes(b"MEMS-guard-demo\n")
        good = hashlib.sha256(f.read_bytes()).hexdigest()
        f.write_bytes(b"MEMS-guard-demo\nTAMPERED-BY-POISON\n")   # 与期望不符的一个字节级改动
        return {"path": f, "expected_sha256": good, "label": "artifact.bin"}
    return make


# --------------------------------------------------------------------------- 示例挂载 ②
def counts_consistent(payload: Mapping) -> list[str]:
    """**计数一致性检查器**（payload = `{"counts": {...}, "total": n[, "label":…]}`）。

    分桶之和必须等于合计；`nan`/`None`/非整数桶一律报错（这类值混进分母正是
    「146 vs 108」事故的成因，见 `guards_denominator`）。
    """
    label = str(payload.get("label") or "计数")
    counts = payload.get("counts")
    total = payload.get("total")
    if not isinstance(counts, Mapping):
        return ["%s：counts 不是字典（%r）" % (label, type(counts).__name__)]
    if not isinstance(total, int) or isinstance(total, bool):
        return ["%s：合计不是整数（%r）" % (label, total)]
    problems: list[str] = []
    bad = sorted(str(k) for k, v in counts.items()
                 if isinstance(v, bool) or not isinstance(v, int))
    if bad:
        problems.append("%s：桶 %s 不是整数（不可判定值不得计入桶）" % (label, bad))
        return problems
    s = sum(int(v) for v in counts.values())
    if s != total:
        problems.append("%s：分桶之和 %d ≠ 合计 %d（差 %+d）" % (label, s, total, s - total))
    return problems


def _counts_clean_factory() -> Callable[[], Any]:
    def make() -> dict:
        return {"label": "E3 拒答分桶", "counts": {"a": 51, "b": 102, "c": 323}, "total": 476}
    return make


def _counts_poison_factory() -> Callable[[], Any]:
    def make() -> dict:
        # 正是 §109.3 的形状：桶和 374 ≠ 合计 476（102 条在两侧同时落 0）
        return {"label": "E3 拒答分桶（投毒：374≠476）",
                "counts": {"a": 51, "b": 0, "c": 323}, "total": 476}
    return make


def builtin_mounts(tmp_root: pathlib.Path | None = None) -> list[CheckerMount]:
    """本模块自带的 **2 个示例挂载**（哈希比对器 / 计数一致性检查器）。

    `tmp_root` 是哈希示例的工作目录（缺省惰性建在系统临时目录下，**import 时不落盘**）。
    """
    tmp = _LazyTmp(tmp_root)
    return [
        mount(
            "sha256 比对器（guards_metatest.hash_compare）",
            hash_compare,
            _hash_clean_factory(tmp),
            [PoisonCase("内容被改一个字节后仍拿旧哈希比对", _hash_poison_factory(tmp),
                        note="等价于 §109 的「E3 证据包被重写」：旧 sha256 必须报不符")],
            doc="文件集合里的 sha256 必须与期望逐位相同；空期望也判不合格。",
        ),
        mount(
            "计数一致性（guards_metatest.counts_consistent）",
            counts_consistent,
            _counts_clean_factory(),
            [PoisonCase("分桶之和 374 ≠ 合计 476", _counts_poison_factory(),
                        note="§109.3 实测的 v1 直方图内部矛盾形状")],
            doc="分桶之和必须等于合计；nan/None/非整数桶一律不合格。",
        ),
    ]


def _init_registry() -> None:
    for _e in builtin_mounts():
        register(_e)


_init_registry()


# --------------------------------------------------------------------------- 静态：恒真写法
#: 可机械判定的「写了等于没写」写法（**基于 AST**，不是正则扫文本）。
#: ⚠️ 之所以走 AST：正则会把**文档串/注释里引用这些写法**的地方也算命中
#: （本模块自己的文档里就引用了 `n_prod == 0 or True`）⇒ 那是假阳性。
TAUTOLOGY_KINDS: tuple[tuple[str, str], ...] = (
    ("or_true", "`or True`：整个条件恒真（索引行 4307 的原事故写法）"),
    ("assert_true", "`assert True`：恒真的断言"),
    ("if_true", "`if True:`：恒真分支"),
    ("wildcard_compare", "与纯通配字符串（`\"*\"`）比较：比对必然成立"),
    ("fnmatch_wildcard", "`fnmatch(..., \"*\")`：恒真匹配"),
)


def _is_pure_wildcard(node: ast.AST) -> bool:
    return (isinstance(node, ast.Constant) and isinstance(node.value, str)
            and bool(node.value.strip()) and set(node.value.strip()) <= {"*", "?"})


class _TautologyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.hits: list[tuple[int, str]] = []

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        if isinstance(node.op, ast.Or) and any(
                isinstance(v, ast.Constant) and v.value is True for v in node.values):
            self.hits.append((node.lineno, "or_true"))
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        if isinstance(node.test, ast.Constant) and node.test.value is True:
            self.hits.append((node.lineno, "assert_true"))
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        if isinstance(node.test, ast.Constant) and node.test.value is True:
            self.hits.append((node.lineno, "if_true"))
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        if any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
            if any(_is_pure_wildcard(x) for x in [node.left, *node.comparators]):
                self.hits.append((node.lineno, "wildcard_compare"))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _dotted_name(node.func)
        if name and name.split(".")[-1].lower() in ("fnmatch", "fnmatchcase", "filter"):
            if any(_is_pure_wildcard(a) for a in node.args):
                self.hits.append((node.lineno, "fnmatch_wildcard"))
        self.generic_visit(node)


def _dotted_name(node: ast.AST) -> str:
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


def find_tautology_smells(source: str) -> list[dict]:
    """扫描源码里**可机械判定**的恒真（假校验）写法；返回逐条命中。

    这不是完备的静态检查（真正的保证来自 `falsifiability_report()` 的投毒），
    但它能把最省事的那几种「写了等于没写」当场指出来。**基于 AST** ⇒ 文档串/注释里
    引用这些写法不会误报；源码解析不了（SyntaxError）时**不猜**，直接报一条 `unparsable`。
    """
    why = dict(TAUTOLOGY_KINDS)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [{"line": int(exc.lineno or 0), "smell": "unparsable",
                 "text": "源码解析失败：%s（扫不了 ⇒ 不得当作「没有恒真写法」）" % exc.msg}]
    vis = _TautologyVisitor()
    vis.visit(tree)
    lines = source.splitlines()
    out: list[dict] = []
    for lineno, kind in sorted(set(vis.hits)):
        text = lines[lineno - 1].strip()[:160] if 0 < lineno <= len(lines) else ""
        out.append({"line": lineno, "smell": why.get(kind, kind), "kind": kind, "text": text})
    return out


def summarize(entries: Iterable[CheckerMount] | None = None) -> dict:
    """把注册表整体跑一遍：给测试与报告用的聚合结果。"""
    items = list(entries if entries is not None else REGISTRY)
    reps = [falsifiability_report(e) for e in items]
    bad = [r["name"] for r in reps if not r["falsifiable"]]
    return {"n_mounts": len(items), "n_falsifiable": len(items) - len(bad),
            "not_falsifiable": bad, "reports": reps, "ok": not bad}


def _checker_source_smells(checker: Callable) -> list[dict]:
    """对一个真检查器函数体做恒真扫描（测试用：示例挂载自己也要干净）。"""
    try:
        src = inspect.getsource(checker)
    except (OSError, TypeError):
        return []
    return find_tautology_smells(src)
