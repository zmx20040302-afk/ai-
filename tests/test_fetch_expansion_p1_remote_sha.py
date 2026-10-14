# -*- coding: utf-8 -*-
"""`scripts/fetch_expansion_p1.py` 的 `--remote-sha` 修复自测（正反两侧 ＋ **投毒**）。

### 缺口（`INDEX §126.4` 实测）

预录取回器的解析行写作 `if len(t) == 2 and t[0].endswith(".mat")`，而远端 `sha256sum`
输出是 `<hex>␣␣<path>` ⇒ 检查的是**哈希字段** ⇒ `remote_sha_map()` 恒空 ⇒
**下载之前**就以 `[FAIL] … 只取到 0/80` 退出（rc=3）。

本文件锁住：

* ① **正常解析**，**含路径含空格**（`split()` 定长切法会把这一件静默丢掉）；
* ①b `sha256sum` 按 `SHA_BATCH` **分批**调用（P2）；
* ② **远端输出为空 ⇒ 必须显式报错**（rc=3），不是「0 个通过」默默过；
* ③ **投毒**：把某件 sha 改一个字符 ⇒ 必须被抓住，且**不得写 `.done`**；
* ④ **与当时那份已打补丁的副本做行为对齐**：同一输入上逐项比较，
  并把**唯一一处有意的分歧**（含空格路径）钉死。
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
NEW_SCRIPT = REPO / "scripts/fetch_expansion_p1.py"
PATCHED_COPY = (REPO / "work/runs/field-expansion-20261009"
                / "fetch_expansion_p1_copy.py")


def _load(name, path):
    """按路径加载模块；**过程中关掉 .pyc 落盘**。

    ⚠️ 实测教训：`importlib` 默认会把 `.pyc` 写进**源码旁边**的 `__pycache__/`。
    归档副本在 `work/runs/` 下 ⇒ 直接 import 会在**运行区**里留下新文件
    （本轮实测到 `work/runs/field-expansion-20261009/__pycache__/fetch_expansion_p1_copy.cpython-312.pyc`）。
    `sys.dont_write_bytecode` 只影响字节码缓存（纯性能优化），不改变任何语义。
    """
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


fetch = _load("_fetch_p1_under_test", NEW_SCRIPT)

PLAN_HDR = ["chunk", "name", "remote_path", "local_path", "bytes_remote",
            "n_points_index", "x_scale", "N_w_te1", "N_w_te2", "freq_Hz",
            "role_n", "role_x"]
CHUNK = "N1_1"


def _names(n, spaced_at=None):
    """n 个件名；`spaced_at` 指定哪一件的远端路径里**带空格**。"""
    out = []
    for i in range(n):
        name = "pod20_x1p0_n1_%d_f20p0.mat" % i
        remote = "/remote/pod_20MHz/%s" % name
        if spaced_at is not None and i == spaced_at:
            remote = "/remote/pod 20MHz/%s" % name
        out.append({"name": name, "remote_path": remote,
                    "local_path": "raw/%s/%s" % (CHUNK, name)})
    return out


def _fake_repo(tmp_path, specs, size=64):
    """在 tmp 里造出「计划 TSV + 索引 TSV + 本地文件」，返回 (rows, shas)。"""
    run = tmp_path / "work/runs/field-expansion-20261009"
    inv = tmp_path / "work/runs/field-inventory-20261009"
    run.mkdir(parents=True, exist_ok=True)
    inv.mkdir(parents=True, exist_ok=True)
    rows, shas, idx_lines = [], {}, []
    for i, s in enumerate(specs):
        content = bytes([(i * 7 + j) % 251 for j in range(size)])
        p = tmp_path / s["local_path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        sha = hashlib.sha256(content).hexdigest()
        row = {"chunk": CHUNK, "name": s["name"], "remote_path": s["remote_path"],
               "local_path": s["local_path"], "bytes_remote": str(len(content)),
               "n_points_index": str(100 + i), "x_scale": "1.0",
               "N_w_te1": "4", "N_w_te2": "9", "freq_Hz": "20e6",
               "role_n": "train", "role_x": "1.0"}
        rows.append(row)
        shas[s["name"]] = sha
        idx_lines.append("pod20\t%s\t%d" % (s["name"], 100 + i))
    plan = inv / "expansion_inputs_p1.tsv"
    plan.write_text("\t".join(PLAN_HDR) + "\n"
                    + "\n".join("\t".join(r[h] for h in PLAN_HDR) for r in rows) + "\n",
                    encoding="utf-8")
    idx = inv / "snapshot_index.tsv"
    idx.write_text("kind\tfile\tn_points\n" + "\n".join(idx_lines) + "\n",
                   encoding="utf-8")
    return run, plan, idx, rows, shas


def _wire(monkeypatch, mod, tmp_path, run, plan, idx, ssh_lines):
    """把某个模块的路径常量指到 tmp，并把远端输出换成 `ssh_lines`（返回可查询的调用记录）。"""
    monkeypatch.setattr(mod, "REPO", str(tmp_path))
    monkeypatch.setattr(mod, "RUN", str(run))
    monkeypatch.setattr(mod, "PLAN", str(plan))
    monkeypatch.setattr(mod, "IDX", str(idx))
    calls: list[str] = []

    def _fake_ssh(args):
        calls.append(args[0])
        return 0, "".join(l + "\n" for l in ssh_lines)

    monkeypatch.setattr(mod, "ssh_out", _fake_ssh)
    return calls


def _sha_lines(rows, shas, skip=None, poison=None):
    out = []
    for r in rows:
        if skip is not None and r["name"] == skip:
            continue
        sha = shas[r["name"]]
        if poison is not None and r["name"] == poison[0]:
            sha = poison[1]
        out.append("%s  %s" % (sha, r["remote_path"]))
    return out


def _flip_one_char(sha):
    return ("0" if sha[0] != "0" else "1") + sha[1:]


# ============================================================ ① 解析（含空格路径）
@pytest.mark.parametrize("line,expected", [
    ("a" * 64 + "  /remote/a.mat", ("a" * 64, "/remote/a.mat")),
    ("b" * 64 + "  /remote/带 空格 的 b.mat", ("b" * 64, "/remote/带 空格 的 b.mat")),
    ("c" * 64 + " */remote/c.mat", ("c" * 64, "/remote/c.mat")),      # 二进制模式标记
    ("d" * 64 + "  " + "x" * 64 + ".mat", ("d" * 64, "x" * 64 + ".mat")),
    ("", None),
    ("不是 sha256sum 的输出", None),
    ("e" * 63 + "  /remote/e.mat", None),                              # 63 位 hex ⇒ 不认
    ("e" * 64 + ": /remote/e.mat", None),                              # BSD 形态 ⇒ 不认（不猜）
])
def test_parse_sha256sum_line(line, expected):
    assert fetch._parse_sha256sum_line(line) == expected


def test_remote_sha_map_parses_all_entries_including_spaced_path(tmp_path, monkeypatch):
    """**正侧**：3 件（其中 1 件远端路径含空格）⇒ 三件都要解析出来（键 = 文件名）。"""
    specs = _names(3, spaced_at=1)
    run, plan, idx, rows, shas = _fake_repo(tmp_path, specs)
    _wire(monkeypatch, fetch, tmp_path, run, plan, idx, _sha_lines(rows, shas))

    got = fetch.remote_sha_map(rows)
    assert got == shas, "含空格那件被静默丢掉了（原 bug 的变体）"
    assert len(got) == 3


def test_remote_sha_map_batches_sha256sum_calls(tmp_path, monkeypatch):
    """**正侧（P2）**：件数 > `SHA_BATCH` ⇒ 分多条 ssh 调用，且每条 ≤ SHA_BATCH 个路径。"""
    specs = _names(fetch.SHA_BATCH * 2 + 5)
    run, plan, idx, rows, shas = _fake_repo(tmp_path, specs, size=16)
    calls = _wire(monkeypatch, fetch, tmp_path, run, plan, idx, _sha_lines(rows, shas))

    got = fetch.remote_sha_map(rows)
    assert got == shas
    assert len(calls) == 3, "65 件按 30 一批应为 3 条"
    assert max(c.count(".mat'") for c in calls) <= fetch.SHA_BATCH


# ============================================================ ② 远端输出为空 ⇒ 报错
def test_empty_remote_output_is_an_error_not_a_silent_zero(tmp_path, monkeypatch, capsys):
    """**反侧**：ssh 成功但**输出为空** ⇒ 必须显式报错 rc=3，绝不「0 个通过」。"""
    specs = _names(3)
    run, plan, idx, rows, shas = _fake_repo(tmp_path, specs)
    _wire(monkeypatch, fetch, tmp_path, run, plan, idx, [])

    rc = fetch.main(["--chunk", CHUNK, "--remote-sha"])
    out = capsys.readouterr().out
    assert fetch.remote_sha_map(rows) == {}
    assert rc == 3, "空输出必须 rc=3"
    assert "输出为空" in out and "0/3" in out
    assert "只取到 0/3" not in out, "空集合要单独点名，不能与「部分取到」混为一谈"
    assert not (run / ("chunk_%s.done" % CHUNK)).exists(), "失败不得写 .done"


def test_ssh_failure_is_fail_closed(tmp_path, monkeypatch, capsys):
    """**反侧**：ssh 返回非 0 ⇒ `RemoteShaError` ⇒ rc=3（不猜、不继续）。"""
    specs = _names(2)
    run, plan, idx, rows, shas = _fake_repo(tmp_path, specs)
    monkeypatch.setattr(fetch, "REPO", str(tmp_path))
    monkeypatch.setattr(fetch, "RUN", str(run))
    monkeypatch.setattr(fetch, "PLAN", str(plan))
    monkeypatch.setattr(fetch, "IDX", str(idx))
    monkeypatch.setattr(fetch, "ssh_out", lambda args: (255, "ssh: connect failed"))

    with pytest.raises(fetch.RemoteShaError) as ei:
        fetch.remote_sha_map(rows)
    assert "rc=255" in str(ei.value)
    rc = fetch.main(["--chunk", CHUNK, "--remote-sha"])
    out = capsys.readouterr().out
    assert rc == 3 and "取不到" in out


def test_partial_remote_output_is_fail_closed(tmp_path, monkeypatch, capsys):
    """**反侧**：只解析到部分（丢了一件）⇒ 仍 fail-closed rc=3（不放松原有计数校验）。"""
    specs = _names(4)
    run, plan, idx, rows, shas = _fake_repo(tmp_path, specs)
    _wire(monkeypatch, fetch, tmp_path, run, plan, idx,
          _sha_lines(rows, shas, skip=rows[2]["name"]))
    rc = fetch.main(["--chunk", CHUNK, "--remote-sha"])
    out = capsys.readouterr().out
    assert rc == 3 and "只取到 3/4" in out


# ============================================================ ③ 投毒：改一个字符
def test_poisoned_sha_is_caught_and_no_done_anchor(tmp_path, monkeypatch, capsys):
    """**投毒**：把某件 sha 改一个字符 ⇒ 被抓住（点出该件），且**不写 `.done`**。"""
    specs = _names(3)
    run, plan, idx, rows, shas = _fake_repo(tmp_path, specs)
    victim = rows[1]["name"]
    bad = _flip_one_char(shas[victim])
    _wire(monkeypatch, fetch, tmp_path, run, plan, idx,
          _sha_lines(rows, shas, poison=(victim, bad)))

    rc = fetch.do_chunk(CHUNK, rows, do_fetch=False, remote_sha=True)
    out = capsys.readouterr().out
    assert rc == 0                       # 只读模式：不下载，但**必须报出待取**
    assert "本地已校验通过 2/3，待取 1" in out
    assert victim in out and "sha256" in out, "被投毒的那件必须被点名"
    assert not (run / ("chunk_%s.done" % CHUNK)).exists(), "有未过校验件就不得写 .done"


def test_poisoned_sha_makes_fetch_fail_closed(tmp_path, monkeypatch, capsys):
    """**投毒（带 --fetch）**：下载回传的字节是对的，但远端 sha 是投毒值 ⇒ rc=6、不写 `.done`。

    这条证明「投毒一定被抓住」而不是「恰好因为本地缺文件才报错」。
    """
    specs = _names(2)
    run, plan, idx, rows, shas = _fake_repo(tmp_path, specs)
    victim = rows[0]["name"]
    _wire(monkeypatch, fetch, tmp_path, run, plan, idx,
          _sha_lines(rows, shas, poison=(victim, _flip_one_char(shas[victim]))))

    def _fake_run(cmd, **kw):
        if cmd[0] == "scp":                      # 模拟下载：把**正确字节**写进 .part
            src = tmp_path / rows[0]["local_path"]
            Path(cmd[-1]).write_bytes(src.read_bytes())
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fetch, "subprocess", types.SimpleNamespace(run=_fake_run))
    rc = fetch.do_chunk(CHUNK, rows, do_fetch=True, remote_sha=True)
    out = capsys.readouterr().out
    assert rc == 6, out
    assert "回传校验失败" in out and victim not in ("", None)
    assert not (run / ("chunk_%s.done" % CHUNK)).exists()


def test_clean_run_does_write_done_so_the_poison_test_is_falsifiable(tmp_path, monkeypatch,
                                                                    capsys):
    """**对照（可失败性）**：同样的流程、**不投毒** ⇒ 写 `.done` 且 `n_verified` 与件数一致。

    没有这一条，上面那个「投毒被抓」就不能排除「反正永远不写 .done」。
    """
    import json
    specs = _names(3)
    run, plan, idx, rows, shas = _fake_repo(tmp_path, specs)
    _wire(monkeypatch, fetch, tmp_path, run, plan, idx, _sha_lines(rows, shas))
    rc = fetch.do_chunk(CHUNK, rows, do_fetch=False, remote_sha=True)
    capsys.readouterr()
    assert rc == 0
    dots = json.loads((run / ("chunk_%s.done" % CHUNK)).read_text(encoding="utf-8"))
    assert dots["n_files"] == 3 and dots["n_verified"] == 3
    assert dots["remote_sha_available"] is True and dots["exemptions"] == []
    assert dots["items"][0]["sha256_remote"] == shas[rows[0]["name"]]


def test_without_remote_sha_the_waiver_is_declared_with_reason(tmp_path, monkeypatch, capsys):
    """**反侧（豁免必须带原因）**：不给 `--remote-sha` ⇒ 只按字节数校验，且豁免**写明理由**。"""
    import json
    specs = _names(2)
    run, plan, idx, rows, shas = _fake_repo(tmp_path, specs)
    _wire(monkeypatch, fetch, tmp_path, run, plan, idx, [])
    rc = fetch.do_chunk(CHUNK, rows, do_fetch=False, remote_sha=False)
    capsys.readouterr()
    assert rc == 0
    dots = json.loads((run / ("chunk_%s.done" % CHUNK)).read_text(encoding="utf-8"))
    assert dots["remote_sha_available"] is False
    assert dots["exemptions"] and dots["exemptions"][0]["r8_waiver"] is True
    assert "未启用 --remote-sha" in dots["exemptions"][0]["reason"]


# ============================================================ ④ 与已打补丁副本的行为对齐
@pytest.mark.skipif(not PATCHED_COPY.is_file(), reason="归档的补丁副本不存在")
def test_behaviour_matches_the_patched_copy_on_the_same_input(tmp_path, monkeypatch,
                                                              capsys):
    """**行为对齐**：同一输入上，新脚本与当时那份补丁副本逐项比较，并钉住唯一分歧。

    * **无空格路径**（80 件那种常态）：两者 `remote_sha_map()` **逐键相同**、`do_chunk` 同 rc
      且都写出 `n_verified == 件数` 的 `.done`；
    * **路径含空格**：副本按 `t[1]` 定长切分 ⇒ **丢掉那一件**（随后 fail-closed rc=3）；
      新脚本解析出全部 ⇒ 这是**有意**的分歧（任务要求「正常解析（含路径含空格）」）；
    * **空输出**：两者都 fail-closed rc=3（都拒绝继续）。

    ⚠️ 每个模块各用**独立的假仓库目录**：`.done` 是续跑锚点，共用目录会让第二个模块
    走「已有 .done ⇒ 跳过」分支，把「同 rc」变成假通过。
    """
    copy = _load("_fetch_p1_patched_copy", PATCHED_COPY)

    def _fresh(tag, specs):
        run, plan, idx, rows, shas = _fake_repo(tmp_path / tag, specs, size=32)
        return run, plan, idx, rows, shas, _sha_lines(rows, shas)

    # --- 输入 A：无空格，30 件（同时覆盖分批边界）
    specs = _names(30)
    run, plan, idx, rows, shas, lines = _fresh("a_new", specs)
    _wire(monkeypatch, fetch, tmp_path / "a_new", run, plan, idx, lines)
    got_new_a = fetch.remote_sha_map(rows)
    capsys.readouterr()
    rc_new_a = fetch.do_chunk(CHUNK, rows, do_fetch=False, remote_sha=True)
    capsys.readouterr()

    run_c, plan_c, idx_c, rows_c, shas_c, lines_c = _fresh("a_copy", specs)
    assert lines_c == lines, "同一输入：两份远端输出必须逐字节相同"
    _wire(monkeypatch, copy, tmp_path / "a_copy", run_c, plan_c, idx_c, lines_c)
    got_copy_a = copy.remote_sha_map(rows_c)
    capsys.readouterr()
    rc_copy_a = copy.do_chunk(CHUNK, rows_c, do_fetch=False, remote_sha=True)
    capsys.readouterr()

    assert got_new_a == got_copy_a == shas, "常态输入上两者必须逐键相同"
    assert rc_new_a == rc_copy_a == 0
    import json
    dn = json.loads((run / ("chunk_%s.done" % CHUNK)).read_text(encoding="utf-8"))
    dc = json.loads((run_c / ("chunk_%s.done" % CHUNK)).read_text(encoding="utf-8"))
    assert dn["n_verified"] == dc["n_verified"] == 30

    # --- 输入 B：路径含空格 ⇒ 有意分歧（新修好、副本丢件 ⇒ 副本 fail-closed rc=3）
    specs2 = _names(3, spaced_at=1)
    run2, plan2, idx2, rows2, shas2, lines2 = _fresh("b_new", specs2)
    _wire(monkeypatch, fetch, tmp_path / "b_new", run2, plan2, idx2, lines2)
    got_new = fetch.remote_sha_map(rows2)
    capsys.readouterr()
    rc_new_b = fetch.do_chunk(CHUNK, rows2, do_fetch=False, remote_sha=True)
    out_new = capsys.readouterr().out

    run2c, plan2c, idx2c, rows2c, shas2c, lines2c = _fresh("b_copy", specs2)
    _wire(monkeypatch, copy, tmp_path / "b_copy", run2c, plan2c, idx2c, lines2c)
    got_copy = copy.remote_sha_map(rows2c)
    capsys.readouterr()
    rc_copy_b = copy.do_chunk(CHUNK, rows2c, do_fetch=False, remote_sha=True)
    out_copy = capsys.readouterr().out

    assert got_new == shas2, "新脚本必须解析出全部 3 件"
    assert len(got_copy) == 2, "副本按 t[1] 定长切分 ⇒ 含空格那件被丢掉（这就是分歧）"
    assert rc_new_b == 0 and "待取 0" in out_new
    assert rc_copy_b == 3 and "只取到 2/3" in out_copy, "副本在含空格输入上 fail-closed"

    # --- 输入 C：空输出 ⇒ 两者都 rc=3（判定一致）
    specs3 = _names(2)
    run3, plan3, idx3, rows3, shas3, _l3 = _fresh("c_new", specs3)
    _wire(monkeypatch, fetch, tmp_path / "c_new", run3, plan3, idx3, [])
    capsys.readouterr()
    rc_new_c = fetch.do_chunk(CHUNK, rows3, do_fetch=False, remote_sha=True)
    out_new_c = capsys.readouterr().out

    run3c, plan3c, idx3c, rows3c, _s3c, _l3c = _fresh("c_copy", specs3)
    _wire(monkeypatch, copy, tmp_path / "c_copy", run3c, plan3c, idx3c, [])
    capsys.readouterr()
    rc_copy_c = copy.do_chunk(CHUNK, rows3c, do_fetch=False, remote_sha=True)
    out_copy_c = capsys.readouterr().out

    assert rc_new_c == rc_copy_c == 3, "空输出：两者都拒绝继续"
    assert "输出为空" in out_new_c and "只取到 0/2" in out_copy_c, \
        "报错措辞不同（新版点明「输出为空」、副本只报「只取到 0/N」），但判定一致"


def test_archived_originals_are_untouched():
    """**只读核对**：两份归档件的 sha256 与本轮登记值一致（本轮一个字节都没改）。"""
    import hashlib
    want = {
        REPO / "work/runs/field-inventory-20261009/fetch_expansion_p1.py":
            "304ddb106c50dd1db1ab6462f6c66189945345f6782154874e54b9276e40adc0",
        PATCHED_COPY: "44ffb79872239162618777959155c48dc6482cce0bdc830cc1b9f80ef06aecfc",
    }
    for p, sha in want.items():
        if not p.is_file():
            pytest.skip("归档件不存在：%s" % p)
        assert hashlib.sha256(p.read_bytes()).hexdigest() == sha, p


@pytest.mark.skipif(not PATCHED_COPY.is_file(), reason="归档的补丁副本不存在")
def test_loading_the_archived_copy_leaves_no_bytecode_in_the_run_dir():
    """**反侧（不留痕）**：加载归档副本不得在 `work/runs/` 里落下 `.pyc`。

    实测教训：`importlib` 默认会在源码旁写 `__pycache__/`，而这里的源码在**运行区**
    ⇒ 一次「只读核对」也会在既有产物目录里新增文件。本用例把 `_load()` 的
    `dont_write_bytecode` 行为钉住（并断言缓存目录里没有该副本的 `.pyc`）。
    """
    cache = PATCHED_COPY.parent / "__pycache__"
    before = sorted(p.name for p in cache.glob("fetch_expansion_p1_copy*.pyc")) \
        if cache.is_dir() else []
    assert before == [], "归档目录里已经有副本的 .pyc：%s（应清理）" % before
    _load("_fetch_p1_copy_no_bytecode", PATCHED_COPY)
    after = sorted(p.name for p in cache.glob("fetch_expansion_p1_copy*.pyc")) \
        if cache.is_dir() else []
    assert after == [], "加载归档副本写出了 .pyc（污染 work/runs）"
