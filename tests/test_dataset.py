"""A4 数据契约测试：第六来源 ai_solver、多人预留字段、dataset 构建与**强制泄漏检查**。"""

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

from memsharness import dataset as ds  # noqa: E402
from memsharness import store  # noqa: E402
from memsharness.paths import work_root  # noqa: E402


@pytest.fixture()
def conn():
    root = work_root() / ".test-tmp" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    with store.connect(root / "test.duckdb") as connection:
        store.init_schema(connection)
        yield connection


def _add(family: str, fid: str, conn, *, status: str = "succeeded", source: str = "simulation", x: float = 1.0) -> None:
    design_id, run_id, sample_id = f"d-{family}-{fid}", f"r-{family}-{fid}", f"s-{family}-{fid}"
    conn.execute(
        "INSERT INTO design (design_id, params, units, geometry_family, source_type, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [design_id, json.dumps({"x": x}), json.dumps({"x": "m"}), family, source, store.now_utc()],
    )
    store.insert_run(conn, run_id=run_id, design_id=design_id, status=status, backend="local")
    kwargs = dict(
        sample_id=sample_id, run_id=run_id, design_id=design_id, fidelity="F2",
        source_type=source, inputs={"x": x}, outputs={"y": 2 * x}, extractor="t@1",
    )
    if source == "ai_solver":
        kwargs.pop("run_id")
        kwargs.update(model_id="mdl-x", uncertainty={"y": 0.01})
    store.insert_sample(conn, **kwargs)


# ---------------- 第六来源 ai_solver ----------------

def test_ai_solver_is_a_valid_source_type() -> None:
    assert "ai_solver" in store.SOURCE_TYPES
    assert len(store.SOURCE_TYPES) == 6


def test_ai_solver_requires_model_id(conn) -> None:
    """AI 解必须挂到具体模型版本，否则无法回答"这是哪个模型哪一版给的"。"""
    with pytest.raises(ValueError, match="model_id"):
        store.insert_sample(
            conn, sample_id="a1", source_type="ai_solver",
            inputs={"x": 1.0}, outputs={"y": 2.0}, uncertainty={"y": 0.1}, extractor="e@1",
        )


def test_ai_solver_requires_uncertainty(conn) -> None:
    """红线 7：无误差界的 AI 解不得入库。"""
    with pytest.raises(ValueError, match="uncertainty"):
        store.insert_sample(
            conn, sample_id="a2", source_type="ai_solver", model_id="mdl-x",
            inputs={"x": 1.0}, outputs={"y": 2.0}, extractor="e@1",
        )


def test_ai_solver_sample_round_trip(conn) -> None:
    store.insert_sample(
        conn, sample_id="a3", source_type="ai_solver", model_id="mdl-x",
        inputs={"x": 1.0}, outputs={"y": 2.0}, uncertainty={"y": 0.1}, extractor="e@1",
    )
    row = conn.execute("SELECT model_id, source_type FROM sample WHERE sample_id='a3'").fetchone()
    assert row == ("mdl-x", "ai_solver")


# ---------------- 多人预留字段 ----------------

def test_multiuser_columns_exist(conn) -> None:
    """事后补字段会断掉历史归属，故第一天就要有。"""
    cols = {
        table: {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for table in ("run", "dataset", "model", "task")
    }
    assert "owner" in cols["run"]
    assert "created_by" in cols["dataset"]
    assert {"approved_by", "approved_at"} <= cols["model"]
    assert "created_by" in cols["task"]


# ---------------- dataset 构建与泄漏检查 ----------------

def test_build_dataset_split_is_family_wise(conn) -> None:
    for fam in ("F-A", "F-B", "F-C", "F-D"):
        for i in range(3):
            _add(fam, str(i), conn, x=1.0 + i)
    out = ds.build_dataset(conn, purpose="train", holdout_frac=0.5, seed=1)
    assert out["created"] and out["leak_check_passed"]
    report = out["report"]["split"]
    assert report["cross_family_holdout"] is True
    assert not (set(report["train_families"]) & set(report["holdout_families"]))
    # 整族不拆分：每个族的所有样本必须在同一侧
    assert len(report["train_sample_ids"]) + len(report["holdout_sample_ids"]) == 12


def test_single_family_dataset_is_marked_degraded_not_silent(conn) -> None:
    """只有一族时不得假装做了跨族留出——必须显式降级并写进报告。"""
    for i in range(4):
        _add("F-ONLY", str(i), conn, x=1.0 + i)
    out = ds.build_dataset(conn, purpose="train", seed=0)
    assert out["created"] is True
    assert out["cross_family_holdout"] is False
    assert "无法检验跨族泛化" in out["report"]["split"]["degraded_reason"]
    assert out["report"]["warning"]


def test_require_cross_family_rejects_single_family(conn) -> None:
    """需要声称跨族泛化的场合（如场级求解器放行）必须直接拒绝构建。"""
    for i in range(3):
        _add("F-ONLY", str(i), conn, x=1.0 + i)
    out = ds.build_dataset(conn, purpose="train", require_cross_family=True)
    assert out["created"] is False
    assert "跨族留出" in out["reason"]


def test_simulations_from_failed_runs_are_excluded(conn) -> None:
    """失败点不得当有效输出——必须被排除且给出原因。"""
    _add("F-A", "1", conn, x=1.0)
    _add("F-A", "2", conn, status="failed", x=2.0)
    _add("F-B", "3", conn, x=3.0)
    usable, excluded = ds.load_groupable_samples(conn)
    assert len(usable) == 2
    assert len(excluded) == 1
    assert "run 状态" in excluded[0]["reasons"][0]


def test_samples_without_geometry_family_are_excluded(conn) -> None:
    conn.execute(
        "INSERT INTO design (design_id, params, units, geometry_family, source_type, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        ["d-nofam", json.dumps({"x": 1.0}), "{}", None, "simulation", store.now_utc()],
    )
    store.insert_run(conn, run_id="r-nofam", design_id="d-nofam", status="succeeded")
    store.insert_sample(
        conn, sample_id="s-nofam", run_id="r-nofam", design_id="d-nofam", fidelity="F2",
        source_type="simulation", inputs={"x": 1.0}, outputs={"y": 2.0}, extractor="t@1",
    )
    usable, excluded = ds.load_groupable_samples(conn)
    assert usable == []
    assert "geometry_family" in excluded[0]["reasons"][0]


def test_dataset_row_records_source_and_fidelity_mix(conn) -> None:
    """红线 4：混用来源必须在数据集报告里显式声明。"""
    for fam in ("F-A", "F-B"):
        _add(fam, "1", conn, x=1.0)
    _add("F-A", "2", conn, x=2.0, source="analytic")
    out = ds.build_dataset(conn, purpose="train", seed=0)
    counts = out["report"]["source_counts"]
    assert counts.get("simulation") and counts.get("analytic")
    row = conn.execute("SELECT report, created_by FROM dataset WHERE dataset_id=?", [out["dataset_id"]]).fetchone()
    assert json.loads(row[0])["dataset_id"] == out["dataset_id"]
