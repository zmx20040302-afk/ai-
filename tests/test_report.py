"""A10 测试：报告与出图（Pareto 判定、证据表溯源、报告装配、图文件产出）。"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from memsharness import report as rp  # noqa: E402
from memsharness import store  # noqa: E402
from memsharness.paths import work_root  # noqa: E402


# ---------------- Pareto 判定 ----------------

def test_pareto_front_simple_tradeoff() -> None:
    """目标1↑、目标2↓：仅 (2,0.5) 与 (5,1) 互不支配；(3,3) 被 (5,1) 支配，(1.5,6) 被 (2,0.5) 支配。"""
    pts = [(2.0, 0.5), (3.0, 3.0), (5.0, 1.0), (1.5, 6.0)]
    front = rp.pareto_front(pts, maximize=[True, False])
    assert sorted(front) == [0, 2], f"前沿判定错误：{front}"


def test_pareto_front_handles_duplicates_and_domination() -> None:
    pts = [(1.0, 1.0), (1.0, 1.0), (0.5, 0.5)]
    front = rp.pareto_front(pts, maximize=[True, True])
    # 第三点被前两点支配；前两点互为重复，保留但不互相支配
    assert 2 not in front
    assert front == [0, 1]


def test_pareto_front_single_point_is_front() -> None:
    assert rp.pareto_front([(1.0, 2.0)], maximize=[True, True]) == [0]


# ---------------- 证据表 ----------------

@pytest.fixture()
def conn():
    root = work_root() / ".test-tmp" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    with store.connect(root / "test.duckdb") as connection:
        store.init_schema(connection)
        yield connection


def test_evidence_rows_trace_to_run_and_sample(conn) -> None:
    store.insert_run(conn, run_id="r-1", design_id="d-1", status="succeeded")
    store.insert_sample(
        conn, sample_id="s-1", run_id="r-1", design_id="d-1", fidelity="F2",
        source_type="simulation", inputs={"x": 1.0}, outputs={"y": 2.0}, extractor="e@1",
    )
    rows = rp.evidence_rows(conn, ["s-1"])
    assert len(rows) == 1
    assert rows[0].run_id == "r-1" and rows[0].sample_id == "s-1"
    assert "y=2" in rows[0].value and rows[0].source_type == "simulation"
    assert "run_id" not in rows[0].as_markdown().split("|")[1] or "`r-1`" in rows[0].as_markdown()


def test_evidence_rows_flag_missing_sample(conn) -> None:
    """缺失样本必须显式标注，不能静默跳过（否则报告会少数据而看不出来）。"""
    rows = rp.evidence_rows(conn, ["does-not-exist"])
    assert len(rows) == 1
    assert "缺失样本" in rows[0].value and rows[0].note == "样本不存在"


# ---------------- 报告装配 ----------------

def test_write_report_includes_caveats_and_evidence(conn, tmp_path=None) -> None:
    store.insert_run(conn, run_id="r-2", design_id="d-2", status="succeeded")
    store.insert_sample(
        conn, sample_id="s-2", run_id="r-2", design_id="d-2", fidelity="F0",
        source_type="analytic", inputs={"x": 1.0}, outputs={"y": 3.0}, extractor="e@2",
    )
    prefix = f"test-{uuid.uuid4().hex[:8]}"
    path = rp.write_report(
        title="测试报告", summary_lines=["结论一"], figures=[],
        rows=rp.evidence_rows(conn, ["s-2"]),
        caveats=["样本量不足，指标仅供管线验证"], prefix=prefix,
    )
    text = Path(path).read_text(encoding="utf-8")
    assert "测试报告" in text and "结论一" in text
    assert "如实声明" in text and "样本量不足" in text
    assert "`r-2`" in text and "`s-2`" in text     # 证据表可回溯


# ---------------- 出图 ----------------

def test_plot_functions_create_files() -> None:
    prefix = f"test-{uuid.uuid4().hex[:8]}"
    pareto = rp.plot_pareto([(1.0, 5.0), (2.0, 3.0), (3.0, 1.0)], maximize=(True, False), prefix=prefix)
    curves = rp.plot_curves([0.0, 1.0, 2.0], {"仿真": [1.0, 2.0, 3.0], "解析": [1.0, 2.0, 3.0]}, prefix=prefix)
    field = rp.plot_field_comparison(
        [(x / 10.0, y / 10.0) for x in range(10) for y in range(10)],
        [float(x + y) for x in range(10) for y in range(10)],
        [float(x + y) + 0.1 for x in range(10) for y in range(10)],
        prefix=prefix,
    )
    for fig in (pareto, curves, field):
        assert Path(fig["figure"]).is_file() and Path(fig["figure"]).stat().st_size > 1000
    assert pareto["n_front"] == 1            # 单调排列时只有最右点不被支配
    # 合成扰动 0.1 对场范数（≈9.9）约 1%，故用 2% 阈值；同时断言它确实被算出来（非 0/NaN）
    assert 0.0 < field["field_rel_l2"] < 0.02
    assert field["n_points"] == 100
