"""P0 基础测试：环境探测、元数据库契约、MCP 工具注册。

运行：
    work\\.venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from memsharness import env as env_mod  # noqa: E402
from memsharness import store  # noqa: E402


# ---------------- 环境探测 ----------------

def test_collect_env_shape() -> None:
    """环境快照必须包含四块事实，且版本可读。"""
    report = env_mod.collect_env()
    for key in ("platform", "comsol", "matlab", "mphserver"):
        assert key in report, f"缺少 {key}"
    assert report["comsol"]["home_exists"] is True
    assert report["comsol"]["version"], "读不到 COMSOL 版本"
    assert report["comsol"]["executables"]["comsolbatch.exe"] is True


def test_license_number_is_masked() -> None:
    """授权号必须脱敏：不得出现原始 LicenseNumber 字段。"""
    info = env_mod.parse_license_info(
        Path(env_mod.DEFAULT_COMSOL_HOME) / "licenseinfo.ini"
    )
    assert "LicenseNumber" not in info
    masked = info.get("LicenseNumber_masked", "")
    assert masked.startswith("*") and len(masked) > 3


def test_capability_matrix_never_claims_solve_verified() -> None:
    """未做真实求解前，任何模块的 solve_verified 都必须是 None（红线 1）。"""
    matrix = env_mod.capability_matrix()
    assert matrix["modules"], "模块清单为空"
    assert all(
        item["solve_verified"] is None for item in matrix["modules"].values()
    ), "未验证的模块被标成了已验证"


def test_capability_matrix_reads_recorded_evidence(monkeypatch) -> None:
    """真实求解冒烟写入的能力表必须被读取，且只影响被记录的模块。"""
    import uuid

    from memsharness.paths import work_root

    root = work_root() / ".test-tmp" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MEMS_WORK_ROOT", str(root))

    env_mod.save_capability_matrix(
        {
            "modules": {
                "MEMS_Module": {
                    "solve_verified": True,
                    "evidence": {"run_id": "run-smoke-1"},
                }
            }
        }
    )
    matrix = env_mod.capability_matrix()
    assert matrix["modules"]["MEMS_Module"]["solve_verified"] is True
    assert matrix["modules"]["MEMS_Module"]["evidence"]["run_id"] == "run-smoke-1"
    # 未记录的模块仍必须是 null，不能被"顺带"标成已验证
    assert matrix["modules"]["RF_Module"]["solve_verified"] is None
    assert matrix["matrix_source"] is not None


# ---------------- 元数据库契约 ----------------

@pytest.fixture()
def conn():
    """使用工作区内自管临时目录建库。

    不用 pytest 的 ``tmp_path``：本机沙箱会拒绝系统临时目录的写入。
    """
    import uuid

    from memsharness.paths import ensure_work_tree, work_root

    ensure_work_tree()
    tmp_dir = work_root() / ".test-tmp" / uuid.uuid4().hex
    tmp_dir.mkdir(parents=True, exist_ok=True)
    with store.connect(tmp_dir / "test.duckdb") as connection:
        store.init_schema(connection)
        yield connection


def test_schema_has_all_tables(conn) -> None:
    expected = {
        "task", "design", "run", "sample", "artifact", "dataset",
        "model", "prediction", "experiment", "evidence", "feedback", "validation",
    }
    assert expected.issubset(set(store.list_tables(conn)))


def test_sample_rejects_unknown_source_type(conn) -> None:
    """来源不明或非法来源的样本必须被拒绝入库（红线 4）。"""
    with pytest.raises(ValueError):
        store.insert_sample(
            conn,
            sample_id="s1",
            source_type="guess",
            inputs={"L": 1.0},
            outputs={"Tmax": 300.0},
        )


def test_sample_rejects_empty_payload(conn) -> None:
    with pytest.raises(ValueError):
        store.insert_sample(
            conn, sample_id="s2", source_type="simulation", inputs={}, outputs={"y": 1}
        )


def test_run_and_sample_round_trip(conn) -> None:
    store.insert_run(
        conn,
        run_id="r1",
        design_id="d1",
        backend="local",
        pathway="comsolbatch",
        model_path="work/runs/r1/in.mph",
        model_sha256="0" * 64,
        software={"comsol": "6.4.0.293"},
        settings={"mesh": "normal"},
        status="succeeded",
    )
    store.insert_sample(
        conn,
        sample_id="s3",
        run_id="r1",
        design_id="d1",
        fidelity="F2",
        source_type="simulation",
        inputs={"L": 0.1},
        outputs={"Tmax": 310.0},
        uncertainty={"Tmax": 1.5},
        extractor="test@0.0.1",
    )
    stats = store.store_stats(conn)
    assert stats["run"] == 1 and stats["sample"] == 1
    rows = store.query(conn, "SELECT * FROM sample WHERE run_id = ?", ["r1"])
    assert rows[0]["source_type"] == "simulation"
    assert rows[0]["fidelity"] == "F2"


def test_sample_requires_traceability_per_source(conn) -> None:
    """红线 1 的可执行化：不同来源必须带各自的溯源 ID，缺一不可。"""
    with pytest.raises(ValueError, match="run_id"):
        store.insert_sample(
            conn, sample_id="t1", source_type="simulation",
            inputs={"x": 1.0}, outputs={"y": 1.0}, extractor="e@1",
        )
    with pytest.raises(ValueError, match="evidence_id"):
        store.insert_sample(
            conn, sample_id="t2", source_type="literature",
            inputs={"x": 1.0}, outputs={"y": 1.0}, extractor="e@1",
        )
    with pytest.raises(ValueError, match="experiment_id"):
        store.insert_sample(
            conn, sample_id="t3", source_type="experiment",
            inputs={"x": 1.0}, outputs={"y": 1.0}, extractor="e@1",
        )
    with pytest.raises(ValueError, match="feedback_id"):
        store.insert_sample(
            conn, sample_id="t4", source_type="human_feedback",
            inputs={"x": 1.0}, outputs={"y": 1.0}, extractor="e@1",
        )
    # analytic 来自公式而非运行/实验，不要求运行类 ID，但 extractor 必填
    store.insert_sample(
        conn, sample_id="t5", source_type="analytic",
        inputs={"x": 1.0}, outputs={"y": 2.0}, extractor="closed_form@0.1",
    )


def test_sample_requires_extractor(conn) -> None:
    """抽取器版本缺失则无法追溯抽取逻辑，必须拒绝。"""
    with pytest.raises(ValueError, match="extractor"):
        store.insert_sample(
            conn, sample_id="t6", source_type="analytic",
            inputs={"x": 1.0}, outputs={"y": 2.0},
        )


# ---------------- MCP 工具 ----------------

def test_mcp_tools_registered() -> None:
    """MCP 服务器必须注册出预期的只读工具集。"""
    from fastmcp import Client

    from memsharness.mcp_server import mcp

    async def _names() -> set[str]:
        async with Client(mcp) as client:
            return {tool.name for tool in await client.list_tools()}

    names = asyncio.run(_names())
    assert {
        "ping", "env_report", "module_capability",
        "data_stats", "records", "run_trace",
    }.issubset(names)


def test_records_tool_rejects_unknown_table() -> None:
    """查询工具必须拒绝白名单外的表名。"""
    from memsharness.mcp_server import records

    result = records(table="sqlite_master")
    assert "error" in result
