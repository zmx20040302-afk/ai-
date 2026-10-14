# -*- coding: utf-8 -*-
"""子智能体**集合**的结构与"自描述诚实性"测试。

为什么需要它：集合里写的 `entrypoints` / `schemas` / `tests` 是**给主智能体看的路标**。
若路标指向不存在的文件，子智能体就会拿着空头支票去干活（本会话已经吃过"以为有其实没有"的亏）。
因此本测试逐条校验**声明的路径在磁盘上真实存在**。

覆盖：
* 九个集合齐备、目录名与 `role_id` 一致、`kind` 合法；
* 每个集合四件套齐（`AGENT.md` / `agent.json` / `prompts/spawn.md` / `README.md`）；
* `AGENT.md` 含 0–9 全部章节标题；
* `agent.json` 必填键齐、并**逐个校验** entrypoints/schemas/tests 的存在性；
* 名册 `agents/README.md` 与索引 `docs/ROLE_MAP.md` 覆盖全部九个；
* 生成器 `--check` 一致（契约与磁盘无漂移）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
import _subproc  # noqa: E402  （tests/ 目录由 pytest 加进 sys.path）
AGENTS = REPO / "agents"
REQUIRED_FILES = ["AGENT.md", "agent.json", "prompts/spawn.md", "README.md"]
REQUIRED_JSON_KEYS = ["role_id", "slug", "name", "kind", "status", "inputs", "outputs",
                      "entrypoints", "schemas", "tests", "concurrency", "forbidden",
                      "stop_conditions", "contract", "spawn_prompt"]
SECTIONS = ["## 0.", "## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.", "## 7.", "## 8.",
            "## 9."]
VALID_KINDS = {"llm", "executor", "hybrid"}


def collections() -> list[Path]:
    return sorted(p for p in AGENTS.iterdir() if p.is_dir() and p.name.startswith("a"))


def test_nine_collections_present() -> None:
    cols = collections()
    assert len(cols) == 9, [c.name for c in cols]
    ids = sorted(c.name.split("-")[0] for c in cols)
    assert ids == ["a%d" % i for i in range(1, 10)]


@pytest.mark.parametrize("cid", ["a%d" % i for i in range(1, 10)])
def test_collection_is_self_contained(cid: str) -> None:
    matches = [p for p in collections() if p.name.startswith(cid + "-")]
    assert len(matches) == 1, "集合 %s 数量异常：%s" % (cid, matches)
    d = matches[0]
    for f in REQUIRED_FILES:
        assert (d / f).is_file(), "%s 缺 %s" % (d.name, f)

    meta = json.loads((d / "agent.json").read_text(encoding="utf-8"))
    for k in REQUIRED_JSON_KEYS:
        assert k in meta, "%s 的 agent.json 缺键 %s" % (d.name, k)
    assert meta["kind"] in VALID_KINDS, meta["kind"]
    assert d.name.startswith(meta["role_id"].lower() + "-")
    assert meta["contract"] == "AGENT.md" and meta["spawn_prompt"] == "prompts/spawn.md"

    body = (d / "AGENT.md").read_text(encoding="utf-8")
    for s in SECTIONS:
        assert s in body, "%s 的 AGENT.md 缺章节 %s" % (d.name, s)

    # 子智能体必须知道自己在什么情况下要停
    assert meta["stop_conditions"], "%s 未声明停止条件" % d.name
    spawn = (d / "prompts/spawn.md").read_text(encoding="utf-8")
    assert "立即停并上报" in spawn, "%s 的 spawn 提示词未写停止条件" % d.name


@pytest.mark.parametrize("cid", ["a%d" % i for i in range(1, 10)])
def test_declared_paths_exist(cid: str) -> None:
    """**声明的入口点/契约/测试必须真实存在**（不许空头支票）。"""
    d = [p for p in collections() if p.name.startswith(cid + "-")][0]
    meta = json.loads((d / "agent.json").read_text(encoding="utf-8"))
    missing = []
    for key in ("entrypoints", "schemas", "tests"):
        for rel in meta.get(key) or []:
            if not (REPO / rel).exists():
                missing.append("%s: %s" % (key, rel))
    assert not missing, "%s 声明了不存在的路径：%s" % (d.name, missing)


def test_a8_collection_declares_executable_gate() -> None:
    """已实现的角色必须声明**可执行**入口与测试（本会话新增的 A8）。"""
    d = AGENTS / "a8-verification-freeze"
    meta = json.loads((d / "agent.json").read_text(encoding="utf-8"))
    assert meta["status"].startswith("**已实现并验证**")
    assert "scripts/verify_and_freeze.py" in meta["entrypoints"]
    assert "tests/test_freeze_gate_offline.py" in meta["tests"]
    for rel in meta["entrypoints"] + meta["tests"] + meta["schemas"]:
        assert (REPO / rel).is_file(), rel


def test_roster_and_map_cover_all() -> None:
    roster = (AGENTS / "README.md").read_text(encoding="utf-8")
    rmap = (REPO / "docs" / "ROLE_MAP.md").read_text(encoding="utf-8")
    for i in range(1, 10):
        assert "A%d " % i in roster, "名册缺 A%d" % i
        assert "**A%d " % i in rmap, "索引缺 A%d" % i
    assert "只有 A3 能触发 COMSOL" in roster, "名册缺并发铁律"


def test_generator_check_is_clean() -> None:
    """契约由生成器产出：磁盘内容必须与生成器一致（防手改漂移）。"""
    r = _subproc.run_py(REPO / "scripts" / "gen_agent_collections.py", "--check")
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")
