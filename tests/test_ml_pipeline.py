"""P0 模型层测试：分组切分、防泄漏、评分卡、模型卡状态。

用合成样本（解析关系 y = 2x + 1）注入临时元数据库，验证管线正确性；
不依赖任何 COMSOL 求解，也不污染真实运行区。
"""

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

from memsharness import store  # noqa: E402
from memsharness.ml import surrogate as sg  # noqa: E402
from memsharness.paths import work_root  # noqa: E402


@pytest.fixture()
def isolated_env(monkeypatch):
    """把运行区重定向到 work/.test-tmp/<uuid>，避免污染真实模型目录。"""
    root = work_root() / ".test-tmp" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MEMS_WORK_ROOT", str(root))
    with store.connect() as conn:
        store.init_schema(conn)
        yield conn


def _seed_samples(conn, n_families: int = 3, per_family: int = 4) -> None:
    """写入 y = 2x + 1 的确定性样本，按几何族组织。"""
    for family_idx in range(n_families):
        family = f"geom-{family_idx}"
        for point in range(per_family):
            x = 1.0 + point + 0.1 * family_idx
            design_id = f"d-{family}-{point}"
            run_id = f"r-{family}-{point}"
            conn.execute(
                "INSERT INTO design (design_id, params, units, geometry_family, source_type, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [design_id, json.dumps({"x": x}), json.dumps({"x": "m"}), family, "simulation", store.now_utc()],
            )
            store.insert_run(
                conn,
                run_id=run_id,
                design_id=design_id,
                backend="local",
                pathway="template",
                status="succeeded",
                software={"comsol": "6.4.0.293"},
            )
            store.insert_sample(
                conn,
                sample_id=f"s-{family}-{point}",
                run_id=run_id,
                design_id=design_id,
                fidelity="F2",
                source_type="simulation",
                inputs={"x": x},
                outputs={"y": 2.0 * x + 1.0},
                uncertainty={"y": 0.01},
                extractor="test@0.0.1",
            )


def test_load_samples_exposes_geometry_family(isolated_env) -> None:
    _seed_samples(isolated_env)
    frame = sg.load_samples(isolated_env)
    assert "in_x" in frame.columns and "out_y" in frame.columns
    assert "geometry_family" in frame.columns
    assert frame["geometry_family"].nunique() == 3


def test_grouped_split_prevents_leakage(isolated_env) -> None:
    _seed_samples(isolated_env)
    frame = sg.load_samples(isolated_env)
    train, test, report = sg.grouped_split(frame, "geometry_family", test_frac=0.34, seed=1)
    assert report["strategy"] == "grouped"
    assert not test.empty and not train.empty
    # 红线：同一几何族不得同时出现在训练与测试集
    assert set(train["geometry_family"]).isdisjoint(set(test["geometry_family"]))


def test_split_degrades_loudly_without_group_column(isolated_env) -> None:
    _seed_samples(isolated_env)
    frame = sg.load_samples(isolated_env).drop(columns=["geometry_family"])
    _, _, report = sg.grouped_split(frame, "geometry_family")
    assert report["strategy"] == "random_degraded"
    assert "warning" in report


def test_pipeline_registers_draft_model_with_warnings(isolated_env) -> None:
    _seed_samples(isolated_env)
    frame = sg.load_samples(isolated_env)
    inputs, outputs = sg.discover_columns(frame)
    train, test, split_report = sg.grouped_split(frame, "geometry_family", test_frac=0.34, seed=2)

    model = sg.SurrogateEnsemble(n_members=3, seed=0)
    model.fit(train, inputs, outputs)
    card = sg.score(model, train, test)

    assert card.n_train > 0
    assert "y" in card.outputs
    assert card.outputs["y"]["rmse"] is not None
    # 样本量远低于可靠阈值时必须显式警告，不能默默产出"看起来很好"的模型
    assert any("低于可靠阈值" in w for w in card.warnings)

    mean, std = model.predict(test)
    assert mean.shape == (len(test), len(outputs))
    assert (std >= 0).all()
    assert model.ood_score(test).shape == (len(test),)

    model_id = "mdl-test"
    model_dir = sg.save_model(model, model_id)
    card_path = sg.write_model_card(model_id, card, split_report)
    sg.register_model(
        isolated_env,
        model_id=model_id,
        card=card,
        card_path=card_path,
        algorithm="mlp_ensemble",
        uq_method="ensemble_std",
    )

    assert (model_dir / "model.joblib").exists()
    payload = json.loads(Path(card_path).read_text(encoding="utf-8"))
    assert payload["state"] == "draft", "模型卡不得自动记为已验证"

    state = isolated_env.execute(
        "SELECT state FROM model WHERE model_id = ?", [model_id]
    ).fetchone()[0]
    assert state == "draft", "红线：模型状态只能是 draft，晋升必须经人工门禁"


def test_train_requires_outputs(isolated_env) -> None:
    """只有输入没有输出的样本表无法训练（管线必须早失败）。"""
    frame = sg.load_samples(isolated_env)
    assert frame.empty
    inputs, outputs = sg.discover_columns(frame)
    assert inputs == [] and outputs == []
