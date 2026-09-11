"""A1 模型接入模块的单元测试（不依赖 COMSOL 求解）。

覆盖：参数表达式解析、包围盒/目标量偏移计算、参数分类规则、副本暂存的幂等与递增命名。
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

from memsharness import onboard as ob  # noqa: E402
from memsharness.paths import work_root  # noqa: E402


# ---------------- 参数表达式解析 ----------------

@pytest.mark.parametrize("expression,expected", [
    ("4[m]", (4.0, "[m]")),
    ("3[m]", (3.0, "[m]")),
    ("1.225[kg/m^3]", (1.225, "[kg/m^3]")),
    ("343[m/s]", (343.0, "[m/s]")),
    ("35[Hz]", (35.0, "[Hz]")),
    ("-2.5e-3[m]", (-0.0025, "[m]")),
    ("7", (7.0, "")),
])
def test_parse_numeric_accepts_plain_values(expression, expected) -> None:
    assert ob.parse_numeric(expression) == expected


@pytest.mark.parametrize("expression", [
    "c_air/(2*Lx)",          # 派生表达式
    "c_air/(6*120[Hz])",
    "sqrt(2)*Lx",
    "",
    None,
])
def test_parse_numeric_rejects_derived_expressions(expression) -> None:
    assert ob.parse_numeric(expression) is None


# ---------------- 偏移量计算 ----------------

def test_bbox_shift_zero_when_identical() -> None:
    state = {"bbox": {"x": [0.0, 4.0], "y": [0.0, 3.0], "z": None}}
    assert ob._bbox_shift(state, state) == pytest.approx(0.0)


def test_bbox_shift_detects_geometry_change() -> None:
    before = {"bbox": {"x": [0.0, 4.0], "y": [0.0, 3.0], "z": None}}
    after = {"bbox": {"x": [0.0, 4.2], "y": [0.0, 3.0], "z": None}}
    shift = ob._bbox_shift(before, after)
    assert shift == pytest.approx(0.05, rel=1e-6)


def test_bbox_shift_none_when_unmeasurable() -> None:
    assert ob._bbox_shift(None, {"bbox": {}}) is None


def test_relative_shift_ignores_noise_below_threshold() -> None:
    base = {"abs(p)": 1.0}
    assert ob.relative_shift(base, {"abs(p)": 1.0 + 1e-12}) < ob.EFFECT_TOL
    assert ob.relative_shift(base, {"abs(p)": 1.1}) > ob.EFFECT_TOL


# ---------------- 分类规则 ----------------

def _classify(**overrides):
    base = dict(geometry_rebuilt=True, solve_ok=True, selection_intact=True,
                topology_intact=True, bbox_shift=0.0, target_shift=0.0)
    base.update(overrides)
    return ob.classify_parameter(**base)


def test_classify_geometry_parameter() -> None:
    assert _classify(bbox_shift=0.05, target_shift=1e-5) == "geometry"


def test_classify_material_parameter() -> None:
    assert _classify(bbox_shift=0.0, target_shift=6e-3) == "material_or_load"


def test_classify_noise_is_not_an_effect() -> None:
    """低于噪声阈值的响应不得被当成"有效参数"（曾把 f_shift 的 6e-9 误判为有效）。"""
    assert _classify(bbox_shift=0.0, target_shift=6e-9) == "no_measured_effect"


def test_classify_unknown_when_no_targets_available() -> None:
    """没有可用目标量时必须如实标为未知，不能冒充"无可测影响"。"""
    assert _classify(bbox_shift=0.0, target_shift=None) == "unknown_no_target"


def test_classify_selection_risk_beats_geometry() -> None:
    """几何变了且选择集/拓扑计数也变了 → 选择集风险优先（可能静默绑错）。"""
    assert _classify(bbox_shift=0.05, selection_intact=False, target_shift=1e-3) == "selection_risk"
    assert _classify(bbox_shift=0.05, topology_intact=False, target_shift=1e-3) == "selection_risk"


def test_classify_failures() -> None:
    assert _classify(geometry_rebuilt=False) == "broken"
    assert _classify(solve_ok=False) == "solve_failed"


def test_whitelist_only_geometry_and_material() -> None:
    """白名单必须只收 geometry / material_or_load 两类。"""
    allowed = {"geometry", "material_or_load"}
    for shift, bbox in [(6e-3, 0.0), (1e-5, 0.05)]:
        assert _classify(bbox_shift=bbox, target_shift=shift) in allowed
    for shift, bbox in [(6e-9, 0.0), (None, 0.0)]:
        assert _classify(bbox_shift=bbox, target_shift=shift) not in allowed


# ---------------- 副本暂存 ----------------

@pytest.fixture()
def isolated_work(monkeypatch):
    root = work_root() / ".test-tmp" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MEMS_WORK_ROOT", str(root))
    return root


def test_stage_model_copies_and_hashes(isolated_work) -> None:
    source = isolated_work / "prod.mph"
    source.write_bytes(b"fake-mph-content")
    info = ob.stage_model(source, "dev-a")
    staged = Path(info["staged"])
    assert staged.is_file() and staged.read_bytes() == b"fake-mph-content"
    assert info["source_sha256"] == info["staged_sha256"]
    assert info["copy_index"] == 1
    # 原件未被修改
    assert source.read_bytes() == b"fake-mph-content"


def test_stage_model_increments_name_when_copy_is_locked(isolated_work, monkeypatch) -> None:
    """上次接入的副本可能仍被 mphserver 占用（WinError 32）→ 必须换名而不是覆盖。"""
    source = isolated_work / "prod.mph"
    source.write_bytes(b"v1")
    first = ob.stage_model(source, "dev-b")
    assert Path(first["staged"]).name == "prod.mph"

    original_unlink = Path.unlink

    def fake_unlink(self, *args, **kwargs):  # 模拟文件被占用
        if self.name == "prod.mph":
            raise PermissionError("[WinError 32] 另一个程序正在使用此文件")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fake_unlink)
    second = ob.stage_model(source, "dev-b")
    assert Path(second["staged"]).name == "prod_2.mph"
    assert second["copy_index"] == 2
    assert Path(second["staged"]).read_bytes() == b"v1"
    # 旧副本仍在（作为接入历史）
    assert Path(first["staged"]).is_file()
