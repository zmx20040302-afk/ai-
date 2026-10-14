# -*- coding: utf-8 -*-
"""数据版本冻结与隔离表修订的离线自测（`scripts/freeze_data_version.py` /
`scripts/amend_data_version_quarantine.py`）。

锁住的行为（裁定 §5.1 / §6）：
* **追加**新 run 进同一版本时，必须记录 `based_on`（父版本 label + sha256）与 `delta_vs_parent`，
  且**父版本文件一字不改**；
* **不可变版本永不覆盖**：目标文件已存在 ⇒ 拒绝；
* `--label` 与父版本同名 ⇒ 拒绝（会覆盖历史）；
* 频率网格不唯一 / 非升序 ⇒ **拒绝冻结**（fail-closed）；
* 隔离表修订必须 **append-only**：同 `(版本, 组合)` 重复 ⇒ 拒绝；无证据文件 ⇒ 拒绝；
  版本清单不存在 ⇒ 拒绝；每条记录必须带版本的 sha256。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import _subproc  # noqa: E402  （tests/ 目录由 pytest 加进 sys.path）

REPO = Path(__file__).resolve().parents[1]
FREEZE = REPO / "scripts/freeze_data_version.py"
AMEND = REPO / "scripts/amend_data_version_quarantine.py"

ROW = "%s %s %s %s 0 0 1+0j 0 0 2+0j 0 0 0 0 %s\n"


def _row(x, n1, n2, f, spl):
    return ROW % (x, n1, n2, f, spl)


def make_mirror(root: Path, run_name: str, n2=5,
                grid=((5e6, 100.0), (5.5e6, 101.0))):
    run = root / run_name
    run.mkdir(parents=True, exist_ok=True)
    body = "% Model: toy\n% Point: (0,0,0)\n"
    for x in (0.2, 0.3):
        for f, spl in grid:
            body += _row(x, 1, n2, f, spl)
    (run / "Table_9.txt").write_text(body, encoding="utf-8")
    return root


def run_script(script: Path, *args) -> subprocess.CompletedProcess:
    # 父子两侧都强制 UTF-8（见 tests/_subproc.py：本机默认 cp936，只改一边就变乱码，
    # 曾让本文件 11 个用例假失败 —— 断言的中文落在乱码里）。
    return _subproc.run_py(script, *args)


def freeze(root: Path, label: str, mirror: Path, out: Path, *extra):
    return run_script(FREEZE, "--label", label, "--mirror", mirror, "--out-dir", out, *extra)


def test_freeze_extra_mirror_records_parent_and_delta(tmp_path):
    m1 = make_mirror(tmp_path / "m1", "cell_te2_5_run")
    m2 = make_mirror(tmp_path / "m2", "cell_te2_8_run", n2=8)
    out = tmp_path / "ver"
    r1 = freeze(tmp_path, "V1", m1, out)
    assert r1.returncode == 0, r1.stderr
    r2 = freeze(tmp_path, "V2", m1, out, "--extra-mirror", m2,
                "--parent-manifest", out / "V1.json")
    assert r2.returncode == 0, r2.stderr
    v1 = json.loads((out / "V1.json").read_text(encoding="utf-8"))
    v2 = json.loads((out / "V2.json").read_text(encoding="utf-8"))
    assert v2["based_on"]["label"] == "V1"
    assert v2["based_on"]["n_combos"] == v1["combos"]["n"]
    assert v2["delta_vs_parent"]["added_runs"] == ["cell_te2_8_run"]
    assert v2["delta_vs_parent"]["n_added_combos"] == 2      # 两个 x，同一 (N1,N2) 各一条新组合
    assert v2["n_runs"] == 2 and v1["n_runs"] == 1
    assert v2["run_provenance"]["cell_te2_5_run"].endswith("m1")
    assert set(v2["mirrors"]) == {str(m1.resolve()).replace("\\", "/"),
                                 str(m2.resolve()).replace("\\", "/")}
    # 父版本必须**一字未改**：重算 sha256 与记录一致
    import hashlib
    assert hashlib.sha256((out / "V1.json").read_bytes()).hexdigest() == v2["based_on"]["sha256"]


def test_freeze_refuses_overwrite(tmp_path):
    m1 = make_mirror(tmp_path / "m1", "cell_te2_5_run")
    out = tmp_path / "ver"
    assert freeze(tmp_path, "V1", m1, out).returncode == 0
    again = freeze(tmp_path, "V1", m1, out)
    assert again.returncode == 2
    assert "禁止覆盖" in (again.stderr + again.stdout)


def test_freeze_refuses_same_label_as_parent(tmp_path):
    m1 = make_mirror(tmp_path / "m1", "cell_te2_5_run")
    m2 = make_mirror(tmp_path / "m2", "cell_te2_8_run", n2=8)
    out = tmp_path / "ver"
    assert freeze(tmp_path, "V1", m1, out).returncode == 0
    r = freeze(tmp_path, "V1", m1, out, "--extra-mirror", m2,
               "--parent-manifest", out / "V1.json")
    assert r.returncode == 2
    assert "同名" in (r.stderr + r.stdout)


def test_freeze_fail_closed_on_grid_mismatch(tmp_path):
    """第二个镜像的频网格与第一个不同 ⇒ 必须拒绝冻结（不是静默取其一）。"""
    m1 = make_mirror(tmp_path / "m1", "cell_te2_5_run")
    m2 = make_mirror(tmp_path / "m2", "cell_te2_8_run", n2=8,
                     grid=((5e6, 100.0), (6e6, 101.0)))       # 步长不同
    out = tmp_path / "ver"
    r = freeze(tmp_path, "V1", m1, out, "--extra-mirror", m2)
    assert r.returncode == 2
    assert "频率网格不唯一" in (r.stderr + r.stdout)
    assert not (out / "V1.json").exists()


def test_freeze_fail_closed_on_duplicate_combo(tmp_path):
    """同一组合出现在两个 run 里 ⇒ 归属不明，必须**显式**报组合重复
    （不能退化成误导性的「频点非严格升序」）。"""
    m1 = make_mirror(tmp_path / "m1", "cell_te2_5_run", n2=5)
    m2 = make_mirror(tmp_path / "m2", "cell_te2_8_run", n2=5)    # 故意与 m1 同组合
    out = tmp_path / "ver"
    r = freeze(tmp_path, "V1", m1, out, "--extra-mirror", m2)
    assert r.returncode == 2
    assert "归属不明" in (r.stderr + r.stdout)
    assert "非严格升序" not in (r.stderr + r.stdout)


def test_freeze_fail_closed_on_duplicate_run_name(tmp_path):
    m1 = make_mirror(tmp_path / "m1", "cell_te2_5_run")
    m2 = make_mirror(tmp_path / "m2", "cell_te2_5_run")          # 同名 run
    out = tmp_path / "ver"
    r = freeze(tmp_path, "V1", m1, out, "--extra-mirror", m2)
    assert r.returncode == 2
    assert "同名重复" in (r.stderr + r.stdout)


def _amend(ledger: Path, manifest: Path, evidence: Path, combo="0.2,1,8", *extra):
    return run_script(AMEND, "--version-manifest", manifest, "--combo", combo,
                      "--evidence", evidence, "--why", "测试用", "--rule", "测试规则",
                      "--ledger", ledger, *extra)


def test_amend_appends_and_binds_version_sha(tmp_path):
    import hashlib
    m1 = make_mirror(tmp_path / "m1", "cell_te2_5_run")
    out = tmp_path / "ver"
    assert freeze(tmp_path, "V1", m1, out).returncode == 0
    man = out / "V1.json"
    ev = tmp_path / "EV.md"
    ev.write_text("# 证据\n", encoding="utf-8")
    ledger = out / "QUARANTINE_AMENDMENTS.jsonl"
    r = _amend(ledger, man, ev, "0.2,1,8", "--discovered-after", "测试")
    assert r.returncode == 0, r.stderr
    recs = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(recs) == 1
    assert recs[0]["seq"] == 1 and recs[0]["action"] == "add_quarantine"
    assert recs[0]["data_version"] == "V1"
    assert recs[0]["data_version_sha256"] == hashlib.sha256(man.read_bytes()).hexdigest()
    assert recs[0]["combo"] == {"x_scale": 0.2, "N_w_te1": 1.0, "N_w_te2": 8.0}
    assert recs[0]["evidence"]["sha256"] == hashlib.sha256(ev.read_bytes()).hexdigest()
    # 版本清单必须**一字未改**
    assert json.loads(man.read_text(encoding="utf-8"))["quarantine"][0]["combo"]["N_w_te2"] == 7.0


def test_amend_refuses_duplicate_combo(tmp_path):
    m1 = make_mirror(tmp_path / "m1", "cell_te2_5_run")
    out = tmp_path / "ver"
    assert freeze(tmp_path, "V1", m1, out).returncode == 0
    ev = tmp_path / "EV.md"
    ev.write_text("# 证据\n", encoding="utf-8")
    ledger = out / "Q.jsonl"
    assert _amend(ledger, out / "V1.json", ev).returncode == 0
    dup = _amend(ledger, out / "V1.json", ev, "0.2,1,8", "--discovered-after", "再次")
    assert dup.returncode == 2
    assert "已登记过" in (dup.stderr + dup.stdout)
    assert len(ledger.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_amend_refuses_missing_evidence(tmp_path):
    m1 = make_mirror(tmp_path / "m1", "cell_te2_5_run")
    out = tmp_path / "ver"
    assert freeze(tmp_path, "V1", m1, out).returncode == 0
    r = _amend(out / "Q.jsonl", out / "V1.json", tmp_path / "不存在.md")
    assert r.returncode == 2
    assert "无证据隔离" in (r.stderr + r.stdout)
    assert not (out / "Q.jsonl").exists()


def test_amend_refuses_missing_manifest(tmp_path):
    ev = tmp_path / "EV.md"
    ev.write_text("# 证据\n", encoding="utf-8")
    r = _amend(tmp_path / "Q.jsonl", tmp_path / "没有这个.json", ev)
    assert r.returncode == 2
    assert "版本清单不存在" in (r.stderr + r.stdout)


def test_amend_refuses_bad_combo(tmp_path):
    m1 = make_mirror(tmp_path / "m1", "cell_te2_5_run")
    out = tmp_path / "ver"
    assert freeze(tmp_path, "V1", m1, out).returncode == 0
    ev = tmp_path / "EV.md"
    ev.write_text("# 证据\n", encoding="utf-8")
    r = _amend(out / "Q.jsonl", out / "V1.json", ev, "0.2,1")
    assert r.returncode == 2
    assert "三个数" in (r.stderr + r.stdout)


def test_amend_reinterpret_requires_supersedes(tmp_path):
    """`reinterpret_attribution`（归因更正）必须指明更正的来源，否则拒绝。"""
    m1 = make_mirror(tmp_path / "m1", "cell_te2_5_run")
    out = tmp_path / "ver"
    assert freeze(tmp_path, "V1", m1, out).returncode == 0
    ev = tmp_path / "EV.md"
    ev.write_text("# 证据\n", encoding="utf-8")
    r = _amend(out / "Q.jsonl", out / "V1.json", ev, "0.2,1,7",
               "--action", "reinterpret_attribution")
    assert r.returncode == 2
    assert "--supersedes-seq" in (r.stderr + r.stdout)


def test_amend_reinterpret_rejects_unknown_supersedes(tmp_path):
    m1 = make_mirror(tmp_path / "m1", "cell_te2_5_run")
    out = tmp_path / "ver"
    assert freeze(tmp_path, "V1", m1, out).returncode == 0
    ev = tmp_path / "EV.md"
    ev.write_text("# 证据\n", encoding="utf-8")
    r = _amend(out / "Q.jsonl", out / "V1.json", ev, "0.2,1,7",
               "--action", "reinterpret_attribution", "--supersedes-seq", "99")
    assert r.returncode == 2
    assert "不存在" in (r.stderr + r.stdout)


def test_amend_reinterpret_allows_second_record_for_same_combo(tmp_path):
    """同一组合可以**再追加**一条归因更正（append-only 的核心用法），
    但同一 `(版本, 组合, action)` 不得重复。"""
    m1 = make_mirror(tmp_path / "m1", "cell_te2_5_run")
    out = tmp_path / "ver"
    assert freeze(tmp_path, "V1", m1, out).returncode == 0
    ev = tmp_path / "EV.md"
    ev.write_text("# 证据\n", encoding="utf-8")
    ledger = out / "Q.jsonl"
    assert _amend(ledger, out / "V1.json", ev, "0.2,1,8").returncode == 0
    r2 = _amend(ledger, out / "V1.json", ev, "0.2,1,8",
                "--action", "reinterpret_attribution", "--supersedes-seq", "1")
    assert r2.returncode == 0, r2.stderr
    recs = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert [r["action"] for r in recs] == ["add_quarantine", "reinterpret_attribution"]
    assert recs[1]["supersedes_seq"] == 1
    # 同一 (版本, 组合, action) 再来一次 ⇒ 拒绝
    dup = _amend(ledger, out / "V1.json", ev, "0.2,1,8",
                 "--action", "reinterpret_attribution", "--supersedes-seq", "1")
    assert dup.returncode == 2
    assert len(ledger.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_amend_supersedes_zero_means_manifest_table(tmp_path):
    """`--supersedes-seq 0` 专指"更正版本 manifest 自带的 quarantine 表"。"""
    m1 = make_mirror(tmp_path / "m1", "cell_te2_5_run")
    out = tmp_path / "ver"
    assert freeze(tmp_path, "V1", m1, out).returncode == 0
    ev = tmp_path / "EV.md"
    ev.write_text("# 证据\n", encoding="utf-8")
    ledger = out / "Q.jsonl"
    r = _amend(ledger, out / "V1.json", ev, "0.2,1,7",
               "--action", "reinterpret_attribution", "--supersedes-seq", "0")
    assert r.returncode == 0, r.stderr
    rec = json.loads(ledger.read_text(encoding="utf-8").strip())
    assert rec["supersedes_seq"] == 0 and rec["action"] == "reinterpret_attribution"


def test_amend_refuses_clear_quarantine(tmp_path):
    """清除隔离需要人工拍板 ⇒ 脚本一律拒绝。"""
    m1 = make_mirror(tmp_path / "m1", "cell_te2_5_run")
    out = tmp_path / "ver"
    assert freeze(tmp_path, "V1", m1, out).returncode == 0
    ev = tmp_path / "EV.md"
    ev.write_text("# 证据\n", encoding="utf-8")
    r = _amend(out / "Q.jsonl", out / "V1.json", ev, "0.2,1,7",
               "--action", "clear_quarantine")
    assert r.returncode == 2
    assert "不允许清除隔离" in (r.stderr + r.stdout)
