# -*- coding: utf-8 -*-
"""`scripts/spawn_role.py`（方案 A：角色点名 + 契约原文注入 + 账本）的离线自测。

安全网的意义：这个脚本决定"子智能体看到的是哪一版契约"。如果它悄悄注入了**旧契约**，
或把任务注入到错误角色，事后无法察觉 ⇒ 每类拦截都必须有负向用例：

* `list` 覆盖 9 个角色；`show` 输出与 `AGENT.md` **逐字节相同**；
* `build` 生成的载荷里**逐字节包含**契约原文，旁车记录里契约/任务/载荷三个哈希与实际一致；
* 未知角色 / 空任务 / 任务文件不存在 ⇒ 拒绝（退出码 4），不产出载荷；
* **契约漂移**（载荷生成后 `AGENT.md` 被改）⇒ `verify` 判漂移并拒绝（退出码 2）；
* 载荷被改 / 旁车哈希与实际不符 ⇒ 判失败；
* 账本 append-only：同 `spawn_id` 同内容 ⇒ 幂等；内容不同 ⇒ 拒收；
* `check` 对真实仓库返回 0（集合完整、声明路径存在、名册覆盖）。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import spawn_role  # noqa: E402


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture()
def fake_repo(tmp_path: Path, monkeypatch):
    """一个只含 1 个角色的假仓库：用来测"契约漂移"而不碰真实文件。"""
    root = tmp_path / "repo"
    d = root / "agents" / "a1-fake-role"
    (d / "prompts").mkdir(parents=True)
    (d / "AGENT.md").write_text("# A1 · 假角色\n\n## 0. 一句话\n\n测试用。\n\n## 3. 输出契约\n\n- `x.json`\n",
                                encoding="utf-8")
    (d / "agent.json").write_text(json.dumps({
        "id": "A1", "name": "假角色", "kind": "llm", "status": "契约版",
        "one": "测试", "entrypoints": [], "schemas": [], "tests": [], "gaps": [],
        "concurrency": {"can": [], "cannot": []}, "stops": []}, ensure_ascii=False), encoding="utf-8")
    (d / "prompts" / "spawn.md").write_text("spawn\n", encoding="utf-8")
    (d / "README.md").write_text("readme\n", encoding="utf-8")
    monkeypatch.setattr(spawn_role, "REPO", root)
    monkeypatch.setattr(spawn_role, "AGENTS", root / "agents")
    monkeypatch.setattr(spawn_role, "SPAWN_ROOT", tmp_path / "spawns")
    monkeypatch.setattr(spawn_role, "LEDGER", tmp_path / "spawns" / "ledger.jsonl")
    return root, d


# ---------------------------------------------------------------------------
# list / show
# ---------------------------------------------------------------------------
def test_list_covers_nine_roles(capsys):
    assert spawn_role.main(["list", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 9
    ids = {r["id"] for r in rows}
    assert {"A1", "A5", "A8", "A9"} <= ids
    for r in rows:
        assert r["kind"] in ("llm", "executor", "hybrid")
        assert r["status"] and r["dir"].startswith("agents/")


def test_show_is_byte_identical_to_agent_md(capsys):
    assert spawn_role.main(["show", "a8-verification-freeze"]) == 0
    out = capsys.readouterr().out
    want = (REPO / "agents/a8-verification-freeze/AGENT.md").read_text(encoding="utf-8")
    assert out == want


def test_show_section_filters(capsys):
    assert spawn_role.main(["show", "a5-sweep-analysis-optimization", "--section", "3"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("## 3.")
    assert "## 4." not in out


def test_show_unknown_role_exits_4(capsys):
    assert spawn_role.main(["show", "a99-nope"]) == 4
    assert "未知角色" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def test_build_payload_embeds_contract_verbatim(tmp_path, capsys):
    task = "审计 A5 的 scan_analysis.json，找合成总分/跨族合并的漏检。"
    assert spawn_role.main(["build", "a8-verification-freeze", "--task", task,
                            "--out-dir", str(tmp_path / "p")]) == 0
    capsys.readouterr()
    body = (tmp_path / "p" / "prompt.md").read_text(encoding="utf-8")
    contract = (REPO / "agents/a8-verification-freeze/AGENT.md").read_text(encoding="utf-8")
    assert contract.strip("\n") in body
    assert task in body
    assert "| role_id | `A8` |" in body
    assert "<!-- BEGIN CONTRACT" in body and "<!-- END CONTRACT" in body

    rec = json.loads((tmp_path / "p" / "spawn_record.json").read_text(encoding="utf-8"))
    assert rec["contract_sha256"] == sha(contract.encode("utf-8"))
    assert rec["payload_sha256"] == sha(body.encode("utf-8"))
    assert rec["spawn_id"].startswith("spawn-") and rec["spawn_id"].endswith(rec["contract_sha256"][:8])
    assert rec["role_id"] == "A8"
    # 角色声明的入口/schema/测试必须出现在交付要求里
    meta = json.loads((REPO / "agents/a8-verification-freeze/agent.json").read_text(encoding="utf-8"))
    for rel in (meta.get("entrypoints") or []):
        assert rel in body


def test_build_rejects_empty_task_and_missing_file(tmp_path, capsys):
    assert spawn_role.main(["build", "a8-verification-freeze", "--task", "   ",
                            "--out-dir", str(tmp_path / "x")]) == 4
    assert "任务为空" in capsys.readouterr().out
    assert not (tmp_path / "x").exists()
    assert spawn_role.main(["build", "a8-verification-freeze", "--task-file",
                            str(tmp_path / "nope.md"), "--out-dir", str(tmp_path / "y")]) == 4
    assert spawn_role.main(["build", "a99-nope", "--task", "t", "--out-dir",
                            str(tmp_path / "z")]) == 4


def test_build_field_adds_task_parameters(tmp_path, capsys):
    assert spawn_role.main(["build", "a5-sweep-analysis-optimization", "--task", "分析扫描表",
                            "--field", "csv=work/x.csv", "--field", "budget=6",
                            "--out-dir", str(tmp_path / "f")]) == 0
    capsys.readouterr()
    body = (tmp_path / "f" / "prompt.md").read_text(encoding="utf-8")
    assert "### 任务参数" in body and "csv = work/x.csv" in body and "budget = 6" in body


def test_build_dry_run_writes_nothing(tmp_path, capsys):
    out = tmp_path / "dry"
    assert spawn_role.main(["build", "a9-report-augment", "--task", "写报告",
                            "--out-dir", str(out), "--dry-run"]) == 0
    assert "[dry-run]" in capsys.readouterr().out
    assert not out.exists()


# ---------------------------------------------------------------------------
# verify：漂移必须拦住
# ---------------------------------------------------------------------------
def test_verify_accepts_fresh_payload(tmp_path, capsys):
    spawn_role.main(["build", "a5-sweep-analysis-optimization", "--task", "t",
                     "--out-dir", str(tmp_path / "ok")])
    capsys.readouterr()
    assert spawn_role.main(["verify", str(tmp_path / "ok" / "prompt.md")]) == 0
    assert "结论：载荷与当前契约一致" in capsys.readouterr().out


def test_verify_detects_contract_drift_on_disk(fake_repo, tmp_path, capsys):
    root, d = fake_repo
    spawn_role.main(["build", "A1", "--task", "t", "--out-dir", str(tmp_path / "p")])
    capsys.readouterr()
    (d / "AGENT.md").write_text("# A1 · 假角色（已改）\n\n## 0. 一句话\n\n改过了。\n",
                                encoding="utf-8")
    assert spawn_role.main(["verify", str(tmp_path / "p" / "prompt.md")]) == 2
    out = capsys.readouterr().out
    assert "DRIFT" in out and "不得用于 spawn" in out


def test_verify_detects_tampered_payload(tmp_path, capsys):
    spawn_role.main(["build", "a9-report-augment", "--task", "t", "--out-dir", str(tmp_path / "p")])
    capsys.readouterr()
    p = tmp_path / "p" / "prompt.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n（手工加了一段）\n", encoding="utf-8")
    assert spawn_role.main(["verify", str(p)]) == 2
    assert "载荷与账本记录不符" in capsys.readouterr().out


def test_verify_detects_contract_body_edit_inside_payload(tmp_path, capsys):
    spawn_role.main(["build", "a9-report-augment", "--task", "t", "--out-dir", str(tmp_path / "p")])
    capsys.readouterr()
    p = tmp_path / "p" / "prompt.md"
    body = p.read_text(encoding="utf-8")
    edited = body.replace("## 0. 一句话", "## 0. 一句话（被改）", 1)
    p.write_text(edited, encoding="utf-8")          # 契约哈希单元格没变，但正文被改
    assert spawn_role.main(["verify", str(p)]) == 2
    out = capsys.readouterr().out
    assert "契约正文逐字节比对：不一致" in out


def test_verify_missing_or_bad_payload(tmp_path, capsys):
    assert spawn_role.main(["verify", str(tmp_path / "nope.md")]) == 4
    bad = tmp_path / "bad.md"
    bad.write_text("随便写的内容", encoding="utf-8")
    assert spawn_role.main(["verify", str(bad)]) == 2
    assert "载荷格式不符" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 账本：append-only
# ---------------------------------------------------------------------------
def test_ledger_is_append_only(fake_repo, tmp_path, capsys):
    root, d = fake_repo
    spawn_role.main(["build", "A1", "--task", "第一次", "--record",
                     "--out-dir", str(tmp_path / "p1")])
    capsys.readouterr()
    led = spawn_role.LEDGER
    assert led.is_file() and len(led.read_text(encoding="utf-8").strip().splitlines()) == 1
    rec = json.loads((tmp_path / "p1" / "spawn_record.json").read_text(encoding="utf-8"))
    assert spawn_role.append_ledger(rec)["status"] == "noop"          # 幂等
    conflict = dict(rec, task_excerpt="改了内容")
    res = spawn_role.append_ledger(conflict)
    assert res["status"] == "rejected" and "append-only" in res["reason"]
    assert len(led.read_text(encoding="utf-8").strip().splitlines()) == 1   # 未被覆盖


def test_ledger_command_lists_entries(fake_repo, tmp_path, capsys):
    # 必须用 fake_repo：否则会写到**真实**的 work/role-spawns/spawn_ledger.jsonl，
    # 把测试垃圾灌进溯源账本（实测踩过：默认参数在定义时求值，monkeypatch 不生效已修，
    # 但测试也不该依赖真实路径）。
    spawn_role.main(["build", "A1", "--task", "t", "--record",
                     "--out-dir", str(tmp_path / "p")])
    capsys.readouterr()
    assert spawn_role.main(["ledger", "--tail", "5"]) == 0
    out = capsys.readouterr().out
    assert "append-only" in out and "role=A1" in out
    assert spawn_role.LEDGER.is_file()
    assert str(spawn_role.LEDGER).startswith(str(tmp_path))


# ---------------------------------------------------------------------------
# check（对真实仓库）
# ---------------------------------------------------------------------------
def test_check_passes_on_real_repo(capsys):
    assert spawn_role.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "9 个角色集合完整" in out


def test_where_reports_quadruple(capsys):
    assert spawn_role.main(["where", "a9-report-augment"]) == 0
    out = capsys.readouterr().out
    assert "AGENT.md" in out and "agent.json" in out and "prompts/spawn.md" in out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
