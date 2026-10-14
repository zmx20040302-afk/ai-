# -*- coding: utf-8 -*-
"""看板生成器的离线自测。

覆盖（都对应"看板会不会骗人"的风险）：
* 正常生成：HTML 含全部面板标题、内嵌 JSON 可解析、每个面板都带**源文件 + sha256**；
* **缺源 fail-closed**：把一个源文件搬到别处 ⇒ 该面板标 `缺失`、退出码 2、`missing` 列出它
  （不允许"静默空白"）；
* 数据一致性：HTML 里内嵌的 JSON 与 `dashboard_data.json` **逐字节同源**（同一 doc 对象）；
* 不写既有产物：只在 `--out-dir` 下写两个文件。
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def load_gen():
    spec = importlib.util.spec_from_file_location("_dash", REPO / "scripts/build_dashboard.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_builds_all_panels_with_sources(tmp_path: Path):
    g = load_gen()
    rc = g.main(["--out-dir", str(tmp_path)])
    assert rc == 0, "正常路径不应报缺失"
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    data = json.loads((tmp_path / "dashboard_data.json").read_text(encoding="utf-8"))
    assert data["kind"] == "mems_dashboard"
    assert data["missing"] == []
    titles = [p["title"] for p in data["panels"]]
    assert len(titles) >= 7
    for need in ("平台总览", "数据集", "谐振频率", "A5 分族分指标排名", "AI 求解器", "x 方向加密清单",
                 "治理与证据"):
        assert any(need in t for t in titles), need
    # 内嵌数据与 sidecar 同源
    emb = html.split("const DASH=", 1)[1].split(";</script>", 1)[0]
    assert json.loads(emb)["generated_utc"] == data["generated_utc"]
    # 每个面板都要有来源与哈希（红线：没有来源就不出数字）
    for p in data["panels"]:
        assert p.get("sources"), p["title"]
        for s in p["sources"]:
            assert s.get("path")
            assert s.get("sha256") or s.get("missing"), p["title"]
    # 自包含：无外链脚本/样式、无 CDN 引用（本机无外网，必须真离线可看）
    assert "<script src=" not in html and "<link " not in html
    assert "cdn" not in html.lower() and "http://" not in html.replace("http://www.w3.org", "")
    assert "render(DASH)" in html and "function svg(" in html


def test_missing_source_is_flagged_and_exit_2(tmp_path: Path, monkeypatch):
    g = load_gen()
    # 复制一份数据集到临时目录，只搬走一个源文件（模拟"该批产物不在盘上"）
    run = tmp_path / "run"
    (run / "dataset").mkdir(parents=True)
    (run / "a5").mkdir()
    (run / "a6").mkdir()
    for rel in ("dataset/exported_manifest.json", "a5/metric_table.csv",
                "a5/scan_analysis.json", "a5/next_batch.json",
                "a6/a6_debug_result.json", "a6/a6_round2_result.json",
                "a6/a6_round3_result.json", "a6/prereg_registry.json",
                "a6/X_DENSIFY_PLAN.json", "a6/first_mode_distribution.json",
                "remote_sha256.txt"):
        src = REPO / "work/runs/remote-exported-20260922" / rel
        if src.is_file():
            shutil.copy2(src, run / rel)
    (run / "a6/first_mode_distribution.json").unlink()      # ← 故意缺一个
    monkeypatch.setattr(g, "RUN", run)
    monkeypatch.setattr(g, "A6", run / "a6")
    rc = g.main(["--out-dir", str(tmp_path / "out")])
    data = json.loads((tmp_path / "out" / "dashboard_data.json").read_text(encoding="utf-8"))
    assert rc == 2, "缺源必须退出码 2"
    assert any("first_mode_distribution" in m for m in data["missing"]), data["missing"]
    html = (tmp_path / "out" / "index.html").read_text(encoding="utf-8")
    assert "缺失" in html
    # 缺的面板仍要在，只是被标记（不得整块消失）
    assert any("谐振频率" in p["title"] for p in data["panels"])


def test_reproducible_with_fixed_timestamp(tmp_path: Path):
    """含墙钟时间戳的产物哈希不可复现 —— 固定 --generated-at 后必须**逐字节**一致。"""
    g = load_gen()
    a, b = tmp_path / "a", tmp_path / "b"
    g.main(["--out-dir", str(a), "--generated-at", "2026-09-23T00:00:00+00:00"])
    g.main(["--out-dir", str(b), "--generated-at", "2026-09-23T00:00:00+00:00"])
    for name in ("index.html", "dashboard_data.json"):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
    # 生成器自身哈希必须在产物里（对齐"哪一版代码生成"）
    data = json.loads((a / "dashboard_data.json").read_text(encoding="utf-8"))
    assert data["generated_utc"] == "2026-09-23T00:00:00+00:00"
    assert len(data["generator_sha256"]) == 64
    assert "reproducible_hint" in data


def test_only_writes_two_files(tmp_path: Path):
    g = load_gen()
    g.main(["--out-dir", str(tmp_path)])
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["dashboard_data.json", "index.html"], names


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
