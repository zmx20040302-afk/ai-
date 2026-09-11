"""A7 测试：解析/降阶数据工厂（F0 模型、自基准、生成器、入库）。

核心不变量：**自基准必须全过**。没有基准的解析数据不得进入训练集——它可能与仿真
系统性偏差而无人发现（这正是"多保真"最容易翻车的地方）。
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from memsharness import analytic as an  # noqa: E402
from memsharness import store  # noqa: E402
from memsharness.paths import work_root  # noqa: E402


# ---------------- 自基准 ----------------

def test_all_benchmarks_pass() -> None:
    report = an.run_benchmarks()
    assert report["n_models"] >= 4
    failures = {
        name: [c for c in info["checks"] if not c["passed"]]
        for name, info in report["models"].items() if not info["passed"]
    }
    assert report["all_passed"], f"以下模型自基准未通过：{failures}"


def test_each_model_has_benchmark_checks() -> None:
    """每个模型都至少要有一条基准，且必须包含极限或标度律检查。"""
    for model in an.MODELS.values():
        checks = model.benchmark()
        assert checks, f"{model.name} 没有基准检查"
        assert any(
            any(k in c["check"] for k in ("极限", "标度", "×", "减半", "加倍", "一致", "自洽", "量级"))
            for c in checks
        ), f"{model.name} 的基准缺少极限/标度/一致性检查"


# ---------------- 参数校验 ----------------

def test_validate_rejects_out_of_range() -> None:
    model = an.get_model("heat_slab_1d")
    with pytest.raises(ValueError, match="超出声明范围"):
        model.validate({"q_in": 1000.0, "L": 0.01, "k_cond": 1.0, "T0": -5.0})


def test_validate_rejects_missing_param() -> None:
    with pytest.raises(ValueError, match="缺少参数"):
        an.get_model("heat_slab_1d").validate({"q_in": 1000.0})


def test_get_model_rejects_unknown_name() -> None:
    with pytest.raises(KeyError):
        an.get_model("no_such_model")


# ---------------- 生成器 ----------------

def test_generate_respects_declared_ranges_and_overrides() -> None:
    rows = an.generate_designs("heat_slab_1d", n_samples=32, overrides={"L": 0.01, "k_cond": 1.0}, seed=1)
    assert len(rows) == 32
    for row in rows:
        assert row["inputs"]["L"] == 0.01 and row["inputs"]["k_cond"] == 1.0
        assert 0.0 <= row["inputs"]["q_in"] <= 1e7
        # 解析关系必须成立：T_max = T0 + q·L/k
        expected = row["inputs"]["T0"] + row["inputs"]["q_in"] * 0.01 / 1.0
        assert row["outputs"]["T_max"] == pytest.approx(expected, rel=1e-12)
        assert row["fidelity"] == "F0"
        assert row["geometry_family"] == "GF-heat-slab-2d"


def test_generate_is_reproducible_with_seed() -> None:
    a = an.generate_designs("cantilever_resonance", n_samples=8, seed=7)
    b = an.generate_designs("cantilever_resonance", n_samples=8, seed=7)
    assert [r["inputs"] for r in a] == [r["inputs"] for r in b]


def test_generate_rejects_fully_fixed_model() -> None:
    model = an.get_model("thermal_noise_amplitude")
    with pytest.raises(ValueError, match="无法生成设计点"):
        an.generate_designs(
            "thermal_noise_amplitude", n_samples=4, overrides={k: 1.0 for k in model.inputs}
        )


# ---------------- 入库 ----------------

@pytest.fixture()
def conn():
    root = work_root() / ".test-tmp" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    with store.connect(root / "test.duckdb") as connection:
        store.init_schema(connection)
        yield connection


def test_insert_analytic_samples_writes_design_and_sample(conn) -> None:
    rows = an.generate_designs("heat_slab_1d", n_samples=12, seed=3)
    result = an.insert_analytic_samples(conn, rows, design_prefix="an-test")
    assert result["inserted"] == 12
    assert conn.execute("SELECT count(*) FROM sample WHERE source_type='analytic'").fetchone()[0] == 12
    assert conn.execute("SELECT count(*) FROM design WHERE source_type='analytic'").fetchone()[0] == 12
    # 溯源与保真度必须正确
    row = conn.execute(
        "SELECT fidelity, extractor, quality FROM sample WHERE source_type='analytic' LIMIT 1"
    ).fetchone()
    assert row[0] == "F0"
    assert row[1].startswith("memsharness.analytic@")
    assert "模型形式误差" in row[2]


def test_analytic_samples_are_groupable(conn) -> None:
    """解析样本必须带 geometry_family，否则数据集构建时会因无法防泄漏而被排除。"""
    rows = an.generate_designs("cantilever_resonance", n_samples=6, seed=5)
    an.insert_analytic_samples(conn, rows, design_prefix="an-cant")
    n = conn.execute(
        "SELECT count(*) FROM sample s JOIN design d ON s.design_id=d.design_id"
        " WHERE d.geometry_family IS NOT NULL AND s.source_type='analytic'"
    ).fetchone()[0]
    assert n == 6
