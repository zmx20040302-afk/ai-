"""静态排查：模块内**未定义全局名**（stale/遗留引用）扫描器。

动机（D-D）：真机 run 在 solve 成功后一秒抛 `NameError: name 'state_f' is not defined`
——那是 P1-a 单写者拆分时的遗留引用，只在"求解后收尾"这条路径上被执行，冒烟测试够不到。
`py_compile` **查不出这种错**（它不是语法错），所以需要一层名字解析检查。

本工具用 AST 做保守的作用域分析：收集模块级绑定（import/def/class/赋值/for/with/comprehension）
与各函数内的绑定，然后报告「既不在本地作用域、也不在模块级、也不是内建」的 `Name` 载入。
它是启发式（不做完整闭包/条件分支数据流），但足以抓住本类遗留引用。

用法：python work/tools/check_undefined_names.py work/tools/lt2_production.py ...
退出码：0 = 未发现可疑名字；1 = 发现可疑名字（并逐条列出）
"""

from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

BUILTINS = set(dir(builtins)) | {
    # 运行时注入的模块级 dunder：源码里没有绑定语句，但一定存在（否则会误报 __file__）
    "__file__", "__name__", "__doc__", "__builtins__", "__spec__", "__package__",
    "__loader__", "__dict__", "__path__", "__debug__",
}


class Binder(ast.NodeVisitor):
    """收集某个作用域内被绑定的名字。"""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)
        self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> None:
        self.names.add(node.arg)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            self.names.add((a.asname or a.name).split(".")[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for a in node.names:
            if a.name != "*":
                self.names.add(a.asname or a.name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node) -> None:
        self.names.add(node.name)
        # 不在本层递归进入函数体（其内部名字属于子作用域）
        self._collect_decorators(node)

    def visit_AsyncFunctionDef(self, node) -> None:
        self.names.add(node.name)
        self._collect_decorators(node)

    def visit_ClassDef(self, node) -> None:
        self.names.add(node.name)
        self._collect_decorators(node)

    def _collect_decorators(self, node) -> None:
        for d in getattr(node, "decorator_list", []):
            self.visit(d)
        for d in getattr(node, "defaults", []):
            self.visit(d)
        for d in getattr(node, "kw_defaults", []):
            if d is not None:
                self.visit(d)


def bound_in(nodes) -> set[str]:
    b = Binder()
    for n in nodes:
        b.visit(n)
    return b.names


def collect_loads_this_scope(node) -> list[ast.Name]:
    """收集 node 子树中属于**本作用域**的 `Name(Load)`，**不进入嵌套作用域**。

    嵌套函数/类的名字本身在本作用域绑定（由 Binder 收集），但它们**内部**的
    名字属于子作用域，必须留给子作用域单独检查——否则会产生大量假阳性
    （实测：set_state(**kw) 里的 cur/kw、def cx(expr,i) 里的 expr/i 都会被误报）。
    """
    loads: list[ast.Name] = []

    def rec(n) -> None:
        for child in ast.iter_child_nodes(n):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.Lambda)):
                # 装饰器与默认值仍在外层作用域求值
                for d in getattr(child, "decorator_list", []):
                    rec(d)
                for d in getattr(child, "defaults", []):
                    rec(d)
                for d in getattr(child, "kw_defaults", []):
                    if d is not None:
                        rec(d)
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                loads.append(child)
            rec(child)

    rec(node)
    return loads


def _scope_locals(node) -> set[str]:
    """本作用域绑定的名字（含参数与嵌套定义名，不含嵌套体内部）。"""
    local = bound_in(getattr(node, "body", []) or [])
    args = getattr(node, "args", None)
    if args is not None:
        for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
            local.add(a.arg)
        if args.vararg:
            local.add(args.vararg.arg)
        if args.kwarg:
            local.add(args.kwarg.arg)
    return local


def check_file(path: Path) -> list[tuple[int, str, str]]:
    """返回 [(lineno, name, scope)]。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_bound = bound_in(tree.body)
    problems: list[tuple[int, str, str]] = []

    def walk_scope(node, outer: set[str], scope_name: str) -> None:
        local = _scope_locals(node)
        known = local | outer | module_bound | BUILTINS
        for nm in collect_loads_this_scope(node):
            if nm.id not in known:
                problems.append((nm.lineno, nm.id, scope_name))
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                walk_scope(child, known, f"{scope_name}.{child.name}")

    for child in ast.iter_child_nodes(tree):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            walk_scope(child, module_bound, child.name)
    return problems


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    files = [Path(a) for a in argv[1:]]
    if not files:
        files = sorted(Path(__file__).resolve().parent.glob("*.py"))
    total = 0
    for f in files:
        probs = check_file(f)
        # 去重（同一名字同一行只报一次）
        uniq = sorted(set(probs))
        print(f"=== {f.name}: {len(uniq)} 个可疑名字 ===")
        for lineno, name, scope in uniq:
            print(f"  L{lineno:<5} {name:<28} (作用域 {scope})")
            total += 1
    print(f"\n合计可疑引用 {total} 处" + ("（应为 0）" if total else " —— 通过"))
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
