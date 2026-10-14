# -*- coding: utf-8 -*-
"""**纪律 R16 守卫**（`INDEX §105`）：**校验者不得改写被校验对象**。

事故背景（实测）：`scripts\\verify_paper_evidence.py` 旧版第 0 项把主生成脚本**就地重跑一遍**
（「先覆盖现场、再比对产物」），于是 2026-10-09 9:54:53 一次「校验」把
`work\\runs\\paper-evidence-20261009\\` 31 件产物**整个重写**，且该设计**原理上无法发现篡改**。
本文件把修复后的性质钉死：

① 默认校验路径**只读**：产物目录「文件集合 + sha256 + mtime」快照前后全等，且**从不**调用重生成；
② 登记册比对**真的能报出不一致**（改内容 / 删文件 / 塞未登记文件）；
③ 快照**抓得住「内容不变但被重写」**（mtime 变化也算写盘）；
④ `--regen` 是**显式**开关，且打开时**不得声称完成了一次校验**（不产生任何校验结论）；
⑤ 源码层：重生成调用**只存在于** `regen_outputs()` 里，`main()` 正文不得直连生成脚本。
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
VERIFIER = REPO / "scripts/verify_paper_evidence.py"
GEN = "paper_evidence_dac2027.py"


def load_verifier():
    spec = importlib.util.spec_from_file_location("_ver_pe", VERIFIER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def ver():
    m = load_verifier()
    m.CHECKS.clear()
    m.FAILS.clear()
    return m


def _reset(mod):
    mod.CHECKS.clear()
    mod.FAILS.clear()


def _sha(p: pathlib.Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _mk_register(tmp_path: pathlib.Path, names=("E1_a.md", "E3_b.json")):
    """造一个**替身**产物目录 ＋ 登记册（不碰真产物）。"""
    d = tmp_path / "evidence"
    d.mkdir()
    outs = []
    for n in names:
        (d / n).write_text("内容-%s" % n, encoding="utf-8")
    for n in names:
        outs.append({"path": "work/runs/fake/%s" % n, "sha256": _sha(d / n),
                     "bytes": (d / n).stat().st_size})
    (d / "MANIFEST.json").write_text(json.dumps({"outputs": outs}), encoding="utf-8")
    return d, {"outputs": outs}


# ------------------------------------------------- ② 登记册比对真的能发现问题
def test_integrity_register_detects_tampering(ver, tmp_path):
    """改内容 / 删文件 / 塞未登记文件 ⇒ 必须逐条报出来（旧版「先覆盖再比对」做不到）。"""
    d, man = _mk_register(tmp_path)
    assert ver.integrity_problems(d, man) == [], "干净替身目录不该有问题"

    (d / "E1_a.md").write_text("被改过了", encoding="utf-8")
    probs = ver.integrity_problems(d, man)
    assert any("sha256 不符" in x and "E1_a.md" in x for x in probs), probs

    (d / "E3_b.json").unlink()
    probs = ver.integrity_problems(d, man)
    assert any("缺产物" in x and "E3_b.json" in x for x in probs), probs

    (d / "E9_sneaky.md").write_text("偷偷加的", encoding="utf-8")
    probs = ver.integrity_problems(d, man)
    assert any("未登记文件" in x and "E9_sneaky.md" in x for x in probs), probs


# ------------------------------------------------- ③ 快照抓得住「内容不变的重写」
def test_snapshot_catches_rewrite_with_identical_content(ver, tmp_path):
    """mtime 变了就算写盘：只比 sha256 会漏掉「同样的内容被重写」。"""
    d = tmp_path / "ev"
    d.mkdir()
    f = d / "a.txt"
    f.write_text("x", encoding="utf-8")
    s1 = ver.snapshot_dir(d)
    f.write_text("x", encoding="utf-8")                      # 内容逐字节相同
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))  # 显式制造 mtime 变化
    s2 = ver.snapshot_dir(d)
    assert s1["a.txt"][0] == s2["a.txt"][0], "内容相同 ⇒ sha256 应相同"
    assert s1["a.txt"][1] != s2["a.txt"][1], "mtime 变化必须被快照抓到"
    assert s1 != s2


# ------------------------------------------------- ⑤ 源码层：重生成只有一条入口
def test_regeneration_is_only_reachable_through_explicit_helper(ver):
    """**起进程**这件事只能发生在 `regen_outputs()` 里。

    旧版把 `subprocess.run([... 生成脚本 ...])` 直接写在 `main()` 第 0 项 ⇒ 默认路径必然改写产物。
    本用例钉住的是机制（起子进程），不是文案（`main()` 的提示语里允许出现脚本名）。
    """
    src_helper = inspect.getsource(ver.regen_outputs)
    assert "subprocess.run" in src_helper and GEN in src_helper, \
        "regen_outputs 才是重生成入口（且应显式点名生成脚本）"
    src_main = inspect.getsource(ver.main)
    assert "subprocess" not in src_main and "sys.executable" not in src_main, \
        "main() 正文里出现了起子进程的代码 ⇒ 默认校验路径又可能改写被校验对象"


# ------------------------------------------------- ④ --regen 不得声称校验
def test_regen_mode_declares_it_is_not_a_verification(ver, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(ver, "regen_outputs", lambda out_dir: calls.append(out_dir) or 0)
    _reset(ver)
    rc = ver.main(["--regen"])
    out = capsys.readouterr().out
    assert calls == [ver.OUT], "必须真的调用了重生成（且只调一次）"
    assert rc == 0, rc
    assert ver.CHECKS == [], "重生成模式**不得**产生任何校验结论：%s" % ver.CHECKS
    assert ver.FAILS == []
    assert "不是一次校验" in out, out


# ------------------------------------------------- ① 默认路径只读（真产物目录）
needs_evidence = pytest.mark.skipif(
    not (REPO / "work/runs/paper-evidence-20261009/MANIFEST.json").is_file(),
    reason="缺证据产物目录（work/ 不进版本库）⇒ 先跑 scripts\\paper_evidence_dac2027.py")


@needs_evidence
def test_default_verification_is_read_only_and_never_regenerates(ver, monkeypatch, capsys):
    """默认路径：产物目录「文件集合 + sha256 + mtime」快照前后全等，且不调用重生成。"""
    def _boom(*a, **k):
        raise AssertionError("默认校验路径**不得**调用 regen_outputs"
                             "（校验者不得改写被校验对象，纪律 R16）")
    monkeypatch.setattr(ver, "regen_outputs", _boom)
    _reset(ver)

    before = ver.snapshot_dir(ver.OUT)
    assert before, "产物目录快照为空 ⇒ 用例无意义"
    rc = ver.main([])
    capsys.readouterr()                     # 吞掉 94 项明细输出

    after = ver.snapshot_dir(ver.OUT)
    assert sorted(after) == sorted(before), "校验改了产物目录的文件集合"
    changed = [k for k in sorted(before) if after.get(k) != before[k]]
    assert changed == [], "校验改写了被校验对象：%s" % changed
    assert rc == 0, "默认校验未通过：%s" % ver.FAILS
