"""``memsharness.modelio`` 的单元测试。

覆盖范围与**不覆盖**范围（如实说明，不假装验证过）：

- ✅ 纯逻辑路径（**不依赖 COMSOL，也不需要真实 .mph**）：
  Java 源码渲染与全 ASCII 守卫、参数效验四分类、相对变化口径、
  MATLAB Model M-file 解析（含枚举原文与续行）、``cross_check`` 的差异识别、
  ``set_parameters`` 的入参校验（保留名/空值/换行/扩展名）、``effect_audit`` 的诚实失败分支。
- ✅ 本地权威 schema（COMSOL 自带补全数据 ``physics.xml``）：
  解析、按 name/topic 过滤、枚举并集/交集口径、非法枚举值检测、缺文件时的优雅降级；
  其中"没装 COMSOL / 没有补全数据"的分支用**自造 XML fixture** 覆盖，
  "真实补全数据的取值"另有 skip 保护的用例。
- ✅ 真实 GUI 导出的 Model M-file 回归（``work/models/bGEtask2-*/bGEtask2.m``，纯文本解析，
  **不启动 COMSOL**）：研究段/扫频/求解器绑定/unknown 收敛。
- ⏭ **真起 COMSOL 的用例默认跳过**，必须显式设 ``MEMSHARNESS_RUN_COMSOL_TESTS=1`` 才跑；
  并且若队列单实例锁被占用（已有求解在跑）仍然跳过。原因见文件顶部那段实测说明
  （与并发求解抢 license/内存，违反「求解环节禁止并行扇出」红线）。
  绝不用假数据冒充真实读回（红线 1/3）。
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from memsharness import modelio as mio  # noqa: E402
from memsharness.onboard import EFFECT_TOL, GEOMETRY_TOL  # noqa: E402
from memsharness.paths import work_root  # noqa: E402


# ======================================================================================
# 公共装置
# ======================================================================================


# 真起 COMSOL 的用例默认**不跑**，必须显式打开：``MEMSHARNESS_RUN_COMSOL_TESTS=1``。
#
# 为什么必须默认跳过（实测，不是理论担心）：
# 2026-09-11 本机在跑一次基线求解任务的同时执行了 ``pytest``，本文件里那 3 项会真起
# ``comsolcompile.exe`` + ``comsolbatch.exe`` 的用例与那次求解**窗口重叠**，导致那次求解的
# 墙钟读数只能当**保守上界**用。项目红线（AGENTS.md 第 4 节）明确「求解环节禁止并行扇出：
# COMSOL 受 license 与内存约束，必须单实例串行队列」——测试默认启动求解器就是在违反它。
#
# 需要跑时请**先确认队列空闲**（``work/queue/locks/worker.lock`` 未被占用、没有 running
# 的 run），再显式打开开关。开关只影响本文件，不影响 ``work/`` 里任何既有数据。
_COMSOL_ENV_FLAG = "MEMSHARNESS_RUN_COMSOL_TESTS"


def _comsol_tests_enabled() -> bool:
    """是否显式允许跑真起 COMSOL 的用例（默认 False）。"""
    return os.environ.get(_COMSOL_ENV_FLAG, "").strip() in ("1", "true", "TRUE", "yes")


def _comsol_ready() -> bool:
    """COMSOL 批处理工具是否就绪（只读探测，不启动任何进程）。"""
    try:
        return mio._backend_ready()
    except Exception:
        return False


def _parallel_solver_running() -> bool:
    """是否已有 COMSOL 求解在跑（队列单实例锁被占用 = 正在求解）。只读探测，不抢占。"""
    try:
        from memsharness.comsol.queue import JobQueue

        return JobQueue().worker_locked()
    except Exception:
        return False


# 串行闸：显式打开开关后，若队列锁被占用（说明正在求解），仍然跳过——宁可少跑，
# 也不与别人的求解抢 license/内存。
_COMSOL_BLOCKED_REASON = (
    f"真起 COMSOL 的用例默认不跑（与并发求解冲突，见文件顶部说明）："
    f"请先确认队列空闲，再设 {_COMSOL_ENV_FLAG}=1"
)
if not _comsol_tests_enabled():
    _COMSOL_SKIP_REASON = _COMSOL_BLOCKED_REASON
elif not _comsol_ready():
    _COMSOL_SKIP_REASON = "本机没有可用的 comsolcompile/comsolbatch"
elif _parallel_solver_running():
    _COMSOL_SKIP_REASON = (
        "检测到队列单实例锁被占用（有 COMSOL 求解正在运行）：本次跳过，避免与它抢 license/内存"
    )
else:
    _COMSOL_SKIP_REASON = None

requires_comsol = pytest.mark.skipif(
    _COMSOL_SKIP_REASON is not None,
    reason=str(_COMSOL_SKIP_REASON),
)

# 真实 GUI 导出的 Model M-file（不是 fixture）：研究段解析曾在这份文件上整段落空。
_REAL_M_EXPORT = (
    work_root() / "models" / "bGEtask2-20260911T064304Z" / "bGEtask2.m"
)
requires_real_m_export = pytest.mark.skipif(
    not _REAL_M_EXPORT.is_file(),
    reason="本机没有那份真实 GUI 导出 bGEtask2.m，跳过基于真实导出的回归用例",
)

# 本地权威 schema：COMSOL 自带的 API 补全数据
_COMPLETION_XML = Path(
    r"D:\COMSOL64\Multiphysics\data\completion\physics.xml"
)
requires_completion = pytest.mark.skipif(
    not _COMPLETION_XML.is_file(),
    reason="本机没有 COMSOL 补全数据 physics.xml，跳过依赖真实 schema 的用例",
)

# 自造的最小补全数据 fixture：覆盖"有 schema 但环境不是 COMSOL 安装"的路径。
# 结构照抄真实文件（tag 是混淆 id，name 是真实属性名，props 是混淆 id 列表）。
_FAKE_COMPLETION_XML = """<?xml version="1.0" encoding="UTF-8"?>
<COMSOLCompletionData>
  <model.physics>
    <FakeFeatureA descr="Boundary_load" id="fkl" name="FakeLoad"
                  props="fake01 fake02" topic="fake_bndl"/>
    <FakeFeatureB1 descr="Boundary_load" id="fkl" name="FakeLoad"
                   props="fake03" topic="other_bndl"/>
    <FakeFeatureB2 descr="Boundary_load" id="fkl" name="FakeLoad"
                   props="fake04" topic="other_bndl"/>
  </model.physics>
  <Properties>
    <fake01 default="ForceArea" descr="Load_type"
            descrs="Force_per_area|Total_force" name="forceType"
            type="String" values="ForceArea|TotalForce"/>
    <fake02 default="0" descr="Pressure" name="pressure" type="String"/>
    <fake03 default="ForceArea" descr="Load_type" descrs="Force_per_area|Pressure"
            name="forceType" type="String" values="ForceArea|TotalForce|FollowerPressure"/>
    <fake04 default="ForceArea" descr="Load_type" descrs="Force_per_area"
            name="forceType" type="String" values="ForceArea|TotalForce"/>
  </Properties>
</COMSOLCompletionData>
"""


@pytest.fixture()
def isolated_work(monkeypatch):
    """把运行区指到 work/.test-tmp/<uuid>（与既有测试同口径，不用系统临时目录）。"""
    root = work_root() / ".test-tmp" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MEMS_WORK_ROOT", str(root))
    return root


# ======================================================================================
# 1. Java 渲染：全 ASCII 守卫 / 占位符 / 转义
# ======================================================================================


def test_render_probe_source_is_pure_ascii_even_with_chinese_paths() -> None:
    """中文路径必须经 \\uXXXX 转义后写进源码：源码全 ASCII，运行时才复原为中文。"""
    src = mio.render_probe_source(
        java_class="model_probe",
        input_name="input.mph",
        source_path="D:\\桌面\\中文路径\\model.mph",
        source_sha256="a" * 64,
        staged_path="D:\\桌面\\staged.mph",
        staged_sha256="b" * 64,
        lock_present=True,
    )
    assert src.isascii()
    assert "@@" not in src
    assert "\\u684c" in src  # 「桌」的 unicode 转义
    assert "ModelUtil.loadCopy" in src
    assert mio.PROBE_MARKER in src


def test_render_set_source_escapes_chinese_parameter_names() -> None:
    src = mio.render_set_source(
        java_class="model_set_parameters",
        input_name="input.mph",
        output_name="model_modified.mph",
        names=["Lx", "中文参数"],
        wanted=["0.012[m]", "5[V]"],
    )
    assert src.isascii()
    assert "@@" not in src
    assert "\\u4e2d\\u6587\\u53c2\\u6570" in src  # 「中文参数」
    assert '"0.012[m]"' in src


def test_render_set_source_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="长度不一致"):
        mio.render_set_source(
            java_class="c", input_name="i.mph", output_name="o.mph",
            names=["a", "b"], wanted=["1"],
        )


def test_render_set_source_rejects_empty_names() -> None:
    with pytest.raises(ValueError, match="names 为空"):
        mio.render_set_source(
            java_class="c", input_name="i.mph", output_name="o.mph", names=[], wanted=[]
        )


def test_render_set_source_rejects_newline_in_expression() -> None:
    """表达式含换行会破坏 Java 字面量 → 必须在渲染前拒绝。"""
    with pytest.raises(ValueError, match="不能含换行"):
        mio.render_set_source(
            java_class="c", input_name="i.mph", output_name="o.mph",
            names=["a"], wanted=["1[m]\nrm -rf"],
        )


@pytest.mark.parametrize(
    "bad",
    ["../evil.mph", "sub/input.mph", "输入.mph", 'a"b.mph', "a\\b.mph", ""],
)
def test_safe_java_filename_rejects_paths_and_non_ascii(bad) -> None:
    """交给 Java 的文件名必须是纯 ASCII 纯文件名（否则拒绝，不退化成近似方案）。"""
    with pytest.raises(mio.ModelIOError):
        mio._safe_java_filename(bad)


def test_safe_java_filename_accepts_plain_ascii() -> None:
    assert mio._safe_java_filename("input.mph") == "input.mph"


def test_java_escape_keeps_ascii_verbatim_and_escapes_rest() -> None:
    assert mio._java_escape("abc") == '"abc"'
    assert mio._java_escape("中") == '"\\u4e2d"'
    assert mio._java_escape('a"b') == '"a\\"b"'
    assert mio._java_escape("a\\b") == '"a\\\\b"'


# ======================================================================================
# 2. 参数效验分类（阈值复用 onboard）
# ======================================================================================


def test_thresholds_are_reused_from_onboard_not_redefined() -> None:
    """判据阈值必须复用 onboard，不得另造一套。"""
    assert mio.GEOMETRY_TOL == GEOMETRY_TOL
    assert mio.EFFECT_TOL == EFFECT_TOL


def test_classify_effect_geometry_wins_over_effect() -> None:
    assert (
        mio._classify_effect(geometry_shift=GEOMETRY_TOL * 10, max_shift=1.0, solve_ok=True)
        == "geometry_changing"
    )


def test_classify_effect_effective_and_inert() -> None:
    assert (
        mio._classify_effect(geometry_shift=0.0, max_shift=EFFECT_TOL * 100, solve_ok=True)
        == "effective"
    )
    assert (
        mio._classify_effect(geometry_shift=0.0, max_shift=EFFECT_TOL / 100, solve_ok=True)
        == "inert"
    )


def test_classify_effect_unknown_is_not_inert() -> None:
    """没有可用输出时必须如实标未知 —— 绝不能冒充「惰性」。"""
    assert (
        mio._classify_effect(geometry_shift=0.0, max_shift=None, solve_ok=True)
        == "unknown_no_effect_measurement"
    )


def test_classify_effect_solve_failure_takes_precedence() -> None:
    assert (
        mio._classify_effect(geometry_shift=1.0, max_shift=1.0, solve_ok=False) == "solve_failed"
    )


def test_relative_shift_is_none_for_zero_baseline() -> None:
    """基线为 0 时相对变化无定义：返回 None，不许伪造一个数值。"""
    assert mio._relative_shift(0.0, 1.0) is None
    assert mio._relative_shift(None, 1.0) is None
    assert mio._relative_shift(2.0, 3.0) == pytest.approx(0.5)


def test_effect_audit_requires_some_input() -> None:
    """两侧都没有输入 → 拒绝产出分类（不猜）。"""
    with pytest.raises(ValueError, match="没有任何可用输入"):
        mio.effect_audit()


def _probe_stub(run_id: str, params: dict[str, str]) -> dict:
    return {
        "run_id": run_id,
        "parameters": [
            {"name": name, "expression": expr} for name, expr in params.items()
        ],
    }


def test_effect_audit_reports_evidence_with_run_ids() -> None:
    """每一条分类都必须带数值证据：改了哪个参数、输出变化多少、两侧 run_id。"""
    base = _probe_stub("probe-base", {"Lx": "0.01[m]", "k_cond": "1[W/(m*K)]"})
    now = _probe_stub("probe-changed", {"Lx": "0.012[m]", "k_cond": "1[W/(m*K)]"})
    audit = mio.effect_audit(
        base, now,
        baseline_outputs={"T_max_K": 310.0},
        changed_outputs={"T_max_K": 358.0},
        solve_ok=True,
    )
    assert audit["run_ids"] == {"baseline": "probe-base", "changed": "probe-changed"}
    assert len(audit["params"]) == 1  # k_cond 没变 → 不报
    entry = audit["params"][0]
    assert entry["name"] == "Lx"
    assert entry["classification"] == "effective"
    assert entry["evidence"]["parameter_changed"] == "Lx"
    assert entry["evidence"]["output_shifts"]["T_max_K"]["baseline"] == 310.0
    assert entry["evidence"]["max_output_relative_shift"] == pytest.approx(
        abs(358.0 - 310.0) / 310.0
    )
    assert entry["evidence"]["run_id_changed"] == "probe-changed"


def test_effect_audit_inert_needs_a_measurement() -> None:
    base = _probe_stub("b", {"rho": "2330"})
    now = _probe_stub("c", {"rho": "2350"})
    without_outputs = mio.effect_audit(base, now, solve_ok=True)
    assert without_outputs["params"][0]["classification"] == "unknown_no_effect_measurement"
    with_outputs = mio.effect_audit(
        base, now, baseline_outputs={"d": 1.0}, changed_outputs={"d": 1.0}, solve_ok=True
    )
    assert with_outputs["params"][0]["classification"] == "inert"


def test_effect_audit_geometry_change_short_circuits_effect() -> None:
    base = _probe_stub("b", {"L": "4[mm]"})
    now = _probe_stub("c", {"L": "5[mm]"})
    audit = mio.effect_audit(
        base, now,
        baseline_outputs={"d": 1.0e-4}, changed_outputs={"d": 4.0e-4},
        geometry_shift=0.25, solve_ok=True,
    )
    assert audit["params"][0]["classification"] == "geometry_changing"
    assert audit["params"][0]["evidence"]["geometry_relative_shift"] == 0.25


def test_effect_audit_outputs_only_mode_uses_params_list() -> None:
    audit = mio.effect_audit(
        baseline_outputs={"T": 300.0}, changed_outputs={"T": 300.0},
        params=["q_in"], solve_ok=True,
    )
    assert [e["name"] for e in audit["params"]] == ["q_in"]
    assert audit["params"][0]["classification"] == "inert"


def test_extract_outputs_from_log_returns_empty_on_unparseable() -> None:
    """日志里没有标记 → 空字典（调用方必须当成「不可用」，不是「为零」）。"""
    assert mio.extract_outputs_from_log("") == {}
    assert mio.extract_outputs_from_log("no marker here") == {}
    assert mio.extract_outputs_from_log(
        'MEMS_RESULT_JSON={"T_max_K": 310.0, "flag": true, "name": "x"}'
    ) == {"T_max_K": 310.0}


def test_extract_outputs_from_log_reads_a_path(isolated_work) -> None:
    log = isolated_work / "batch.stdout.log"
    log.write_text('noise\nMEMS_RESULT_JSON={"d_tip_m": 2.2e-4}\n', encoding="utf-8")
    assert mio.extract_outputs_from_log(log) == {"d_tip_m": 2.2e-4}


# ======================================================================================
# 3. 入参校验（不触碰 COMSOL）
# ======================================================================================


def test_set_parameters_rejects_missing_file(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        mio.set_parameters(tmp_path / "nope.mph", {"a": "1"})


def test_set_parameters_rejects_non_mph() -> None:
    src = _tmp_model()
    other = src.with_suffix(".txt")
    src.rename(other)
    try:
        with pytest.raises(mio.ModelIOError, match=r"只接受 \.mph"):
            mio.set_parameters(other, {"a": "1"})
    finally:
        other.unlink(missing_ok=True)


def test_set_parameters_rejects_reserved_names_before_copying() -> None:
    """保留名 → 直接拒绝，且**不得留下任何副本**（拒绝即无副作用）。"""
    target = _tmp_model()
    try:
        with pytest.raises(mio.ModelIOError, match="保留名黑名单"):
            mio.set_parameters(target, {"h": "0.001[m]"}, work_root=_repo_work())
        assert not list((_repo_work() / "models").glob("*reserved*"))
    finally:
        target.unlink(missing_ok=True)


def test_set_parameters_rejects_empty_values() -> None:
    target = _tmp_model()
    try:
        with pytest.raises(ValueError, match="values 为空"):
            mio.set_parameters(target, {})
    finally:
        target.unlink(missing_ok=True)


def test_set_parameters_rejects_newline_expression() -> None:
    target = _tmp_model()
    try:
        with pytest.raises(ValueError, match="不能含换行"):
            mio.set_parameters(target, {"a": "1[m]\nx"})
    finally:
        target.unlink(missing_ok=True)


def test_probe_model_rejects_missing_and_wrong_extension() -> None:
    with pytest.raises(FileNotFoundError):
        mio.probe_model(_repo_work() / "definitely-not-here.mph")
    src = _tmp_model()
    other = src.with_suffix(".mphx")
    src.rename(other)
    try:
        with pytest.raises(mio.ModelIOError, match=r"只接受 \.mph"):
            mio.probe_model(other)
    finally:
        other.unlink(missing_ok=True)


def test_save_probe_refuses_result_without_run_id() -> None:
    """没有 run_id 的成果不得落档（红线 1）。"""
    with pytest.raises(ValueError, match="run_id"):
        mio.save_probe({"ok": True})


def _repo_work() -> Path:
    return work_root()


def _tmp_model() -> Path:
    """在 work/.test-tmp 下造一个占位 .mph（只用于**前置校验**用例，不喂给 COMSOL）。"""
    root = work_root() / ".test-tmp" / f"modelio-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    target = root / "placeholder.mph"
    target.write_bytes(b"not-a-real-mph")
    return target


# ======================================================================================
# 4. MATLAB Model M-file 解析（权威文本来源）
# ======================================================================================

_M_SAMPLE_HEAD = (
    "function out = model\n"
    "% COMSOL Model M-file (synthetic sample for parser tests)\n"
    "%\n"
    "% IMPORTANT: this is a hand-written fixture, not a COMSOL export.\n"
    "\n"
    "import com.comsol.model.*\n"
    "import com.comsol.model.util.*\n"
    "\n"
    "model = ModelUtil.create('Model');\n"
    "\n"
    "model.modelNode.create('comp1');\n"
    "\n"
    "model.component('comp1').geom.create('geom1', 2);\n"
    "\n"
    "model = model_parameters(model);\n"
    "model = model_geometry(model);\n"
    "model = model_material(model);\n"
    "model = model_physics(model);\n"
    "model = model_study(model);\n"
    "\n"
    "model.sol('sol1').runAll;\n"
    "\n"
    "out = model;\n"
    "end\n"
    "\n"
    "function model = model_parameters(model)\n"
    "model.param.set('Lx', '0.01[m]', 'slab length along x');\n"
    "model.param.set('Ly', '8[mm]', 'slab width');\n"
    "model.param.set('k_cond', '1[W/(m*K)]', 'thermal conductivity');\n"
    "model.param.set('T_max_ref', 'T0+q_in*Lx/k_cond', 'derived reference');\n"
    "end\n"
    "\n"
    "function model = model_geometry(model)\n"
    "model.component('comp1').geom('geom1').lengthUnit('m');\n"
    "model.component('comp1').geom('geom1').create('r1', 'Rectangle');\n"
    "model.component('comp1').geom('geom1').feature('r1').set('size', {'Lx' 'Ly'});\n"
    "model.component('comp1').geom('geom1').run;\n"
    "end\n"
    "\n"
    "function model = model_material(model)\n"
    "model.component('comp1').material.create('mat1', 'Common');\n"
    "model.component('comp1').material('mat1').label('SlabSolid');\n"
    "model.component('comp1').material('mat1').propertyGroup('def')"
    ".set('thermalconductivity', 'k_cond');\n"
    "end\n"
)

_M_SAMPLE_PHYSICS = (
    "function model = model_physics(model)\n"
    "model.component('comp1').physics.create('solid', 'SolidMechanics', 'geom1');\n"
    "model.component('comp1').physics('solid').create('load1', 'BoundaryLoad', 1);\n"
    "model.component('comp1').physics('solid').feature('load1')"
    ".selection.set([4 5]);\n"
    "model.component('comp1').physics('solid').feature('load1')"
    ".set('forceType', 'Pressure');\n"
    "model.component('comp1').physics('solid').feature('load1')"
    ".set('pressure', 'p_load');\n"
    "model.component('comp1').physics('solid').create('fix1', 'Fixed', 1);\n"
    "model.component('comp1').physics('solid').feature('fix1').selection.set(1);\n"
    "end\n"
    "\n"
    "function model = model_study(model)\n"
    "model.study.create('std1');\n"
    "model.study('std1').create('stat', 'Stationary');\n"
    "model.study('std1').feature('stat').set('activate', {'solid' 'on' 'ht' 'off'});\n"
    "end\n"
)


def _sample_text() -> str:
    return _M_SAMPLE_HEAD + _M_SAMPLE_PHYSICS


def test_parse_matlab_export_extracts_parameters() -> None:
    spec = mio.parse_matlab_export(_sample_text())
    assert spec["parsed"] is True
    by_name = {row["name"]: row for row in spec["parameters"]}
    assert set(by_name) == {"Lx", "Ly", "k_cond", "T_max_ref"}
    # 表达式原样保留：单位与派生表达式一字不改
    assert by_name["Lx"]["expression"] == "0.01[m]"
    assert by_name["Ly"]["expression"] == "8[mm]"
    assert by_name["Lx"]["description"] == "slab length along x"
    assert by_name["T_max_ref"]["expression"] == "T0+q_in*Lx/k_cond"


def test_parse_matlab_export_keeps_bare_number_expression() -> None:
    """无单位声明的纯数字表达式原样保留（0.01 ≠ 0.01[m]，不得替它补单位）。"""
    text = (
        "function out = model\n"
        "model = ModelUtil.create('Model');\n"
        "model.param.set('nu', 0.27, 'poisson ratio');\n"
        "out = model;\n"
        "end\n"
    )
    spec = mio.parse_matlab_export(text)
    assert spec["parameters"][0]["expression"] == 0.27
    assert spec["parameters"][0]["description"] == "poisson ratio"


def test_parse_matlab_export_extracts_geometry_and_material() -> None:
    spec = mio.parse_matlab_export(_sample_text())
    assert spec["model_tag"] == "Model"
    geom = spec["geometry"][0]
    assert geom["component"] == "comp1"
    assert geom["tag"] == "geom1"
    assert [f["tag"] for f in geom["features"]] == ["r1"]
    assert geom["features"][0]["type"] == "Rectangle"
    # 几何尺寸以单元数组给出（MATLAB 空格分隔），必须拆成两项
    assert geom["properties"] == [{"name": "size", "value": ["Lx", "Ly"]}]
    material = spec["materials"][0]
    assert material["tag"] == "mat1"
    assert material["label"] == "SlabSolid"
    assert material["material_type"] == "Common"
    props = material["property_groups"][0]["properties"]
    assert props == [{"name": "thermalconductivity", "value": "k_cond"}]


def test_parse_matlab_export_reads_geom_dimension_from_main_block() -> None:
    """``geom.create('geom1', 2)`` 写在主函数里：维度必须从那里读到（不得猜）。"""
    text = (
        "function out = model\n"
        "model = ModelUtil.create('Model');\n"
        "model.modelNode.create('comp1');\n"
        "model.component('comp1').geom.create('geom1', 2);\n"
        "out = model;\n"
        "end\n"
    )
    spec = mio.parse_matlab_export(text)
    assert spec["geometry"][0]["tag"] == "geom1"
    assert spec["geometry"][0]["component"] == "comp1"
    assert spec["geometry"][0]["dimension"] == 2


def test_parse_matlab_export_preserves_enum_原文() -> None:
    """枚举必须保留原文（forceType 的 Pressure 不得被归一成 pressure/ForceArea）。"""
    spec = mio.parse_matlab_export(_sample_text())
    features = {f["tag"]: f for f in spec["physics"][0]["features"]}
    force_type = [
        p for p in features["load1"]["properties"] if p["name"] == "forceType"
    ]
    assert force_type == [{"name": "forceType", "value": "Pressure"}]


def test_parse_matlab_export_extracts_selection_entities() -> None:
    spec = mio.parse_matlab_export(_sample_text())
    features = {f["tag"]: f for f in spec["physics"][0]["features"]}
    assert features["load1"]["selection"] == {"tag": None, "entities": [4, 5]}
    assert features["fix1"]["selection"] == {"tag": None, "entities": [1]}
    assert features["load1"]["type"] == "BoundaryLoad"
    # 全局选择集索引里也能查到（owner 级）
    owners = {sel["owner"] for sel in spec["selections"]}
    assert any(o.endswith("feature('load1')") for o in owners)


def test_parse_matlab_export_extracts_study_steps() -> None:
    spec = mio.parse_matlab_export(_sample_text())
    study = spec["study"][0]
    assert study["tag"] == "std1"
    assert study["steps"][0]["tag"] == "stat"
    assert study["steps"][0]["type"] == "Stationary"
    assert study["steps"][0]["properties"] == [
        {"name": "activate", "value": ["solid", "on", "ht", "off"]}
    ]


def test_parse_matlab_export_handles_continuation_and_comments() -> None:
    """续行 ``...`` 与 ``%`` 注释都必须正确处理（真实导出就是长这样）。"""
    text = (
        "function out = model\n"
        "model = ModelUtil.create('Model');\n"
        "model.param.set('a', ...\n"
        "    1.5, ...\n"
        "    'description with % not a comment'); % trailing comment\n"
        "out = model;\n"
        "end\n"
    )
    spec = mio.parse_matlab_export(text)
    assert spec["parsed"] is True
    assert spec["parameters"] == [
        {"name": "a", "expression": 1.5, "description": "description with % not a comment",
         "block": "main"}
    ]


def test_parse_matlab_export_rejects_non_comsol_text() -> None:
    """不是 Model M-file 时必须如实说「不是」，不得硬猜出内容。"""
    spec = mio.parse_matlab_export("plain text, no functions here\n")
    assert spec["parsed"] is False
    assert "function" in spec["reason"]
    assert spec["parameters"] == []


def test_parse_matlab_export_rejects_plain_livelink_script(tmp_path) -> None:
    """LiveLink 教程脚本（无 function 定义）必须如实报「不是 Model M-file」。

    实测：``D:\\COMSOL64\\Multiphysics\\applications\\LiveLink_for_MATLAB\\Tutorials\\*.m``
    是**普通脚本**（`model = mphopen(...)` 之类），不是 GUI 导出的 Model M-file；
    解析器对它返回 parsed=False 是**正确行为**（红线 3：不猜内容），不得为它编造参数表。
    """
    script = tmp_path / "livelink_script.m"
    script.write_text(
        "% scripted model\n"
        "model = mphopen('some_model');\n"
        "model.param.set('L', 0.1);\n"
        "model.study('std1').run;\n",
        encoding="utf-8",
    )
    spec = mio.parse_matlab_export(script)
    assert spec["parsed"] is False
    assert "function" in spec["reason"]
    assert spec["parameters"] == []


def test_parse_matlab_export_empty_text() -> None:
    spec = mio.parse_matlab_export("\n\n% only comments\n")
    assert spec["parsed"] is False
    assert spec["reason"]


def test_parse_matlab_export_from_path_records_sha256(isolated_work) -> None:
    path = isolated_work / "export.m"
    path.write_text(_sample_text(), encoding="utf-8")
    spec = mio.parse_matlab_export(path)
    assert spec["source_kind"] == "path"
    assert spec["source_path"] == str(path)
    assert isinstance(spec["sha256"], str) and len(spec["sha256"]) == 64


def test_parse_matlab_export_missing_path_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        mio.parse_matlab_export(tmp_path / "nope.m")


def test_parse_matlab_export_keeps_unparsable_assignments() -> None:
    """识别不了的赋值要留原文，不能被静默丢弃。"""
    text = (
        "function out = model\n"
        "model = ModelUtil.create('Model');\n"
        "model.param.set(variable_name, 'x');\n"
        "out = model;\n"
        "end\n"
    )
    spec = mio.parse_matlab_export(text)
    assert spec["parameters"] == []
    assert len(spec["unknown_assignments"]) == 1
    assert spec["unknown_assignments"][0]["line"] == 3
    assert "variable_name" in spec["unknown_assignments"][0]["text"]


# ======================================================================================
# 5. cross_check：只报差异
# ======================================================================================


def _probe_fixture(**overrides) -> dict:
    probe = {
        "run_id": "probe-1",
        "comsol_version": "6.4",
        "parameters": [
            {"name": "Lx", "expression": "0.01[m]", "value": 0.01, "value_error": None},
            {"name": "Ly", "expression": "8[mm]", "value": 0.008, "value_error": None},
            {"name": "k_cond", "expression": "1[W/(m*K)]", "value": 1.0, "value_error": None},
            {"name": "T_max_ref", "expression": "T0+q_in*Lx/k_cond", "value": None,
             "value_error": "unit error"},
        ],
        "physics": [
            {
                "component": "comp1", "tag": "solid", "type": "SolidMechanics",
                "selection": [1], "features": [
                    {"tag": "load1", "type": "BoundaryLoad", "selection": [4, 5], "properties": [
                        {"name": "forceType", "value": "Pressure"},
                        {"name": "pressure", "value": "p_load"},
                    ]},
                    {"tag": "fix1", "type": "Fixed", "selection": [1], "properties": []},
                ],
            }
        ],
        "studies": [{"tag": "std1", "steps": [{"tag": "stat", "type": "Stationary"}]}],
        "readback": [{"level": "unreadable", "item": "mesh.num_elements",
                      "source": "mesh.getNumElem()", "reason": "NaN"}],
    }
    probe.update(overrides)
    return probe


def test_cross_check_identical_returns_only_readback_noise() -> None:
    """两侧一致时只应剩下「运行时读不到」这类必须上报的项（不得报假差异）。"""
    spec = mio.parse_matlab_export(_sample_text())
    probe = _probe_fixture()
    # probe 侧补上枚举校验（与探针真实行为一致）：否则会多出 enum_validation_missing
    probe["enum_validation"] = mio.build_enum_validation(probe["physics"])
    diffs = mio.cross_check(spec, probe)
    kinds = {d["kind"] for d in diffs}
    assert kinds <= {"unreadable_in_probe", "illegal_enum_value", "enum_not_checked"}
    # spec 与 probe 的 forceType 都是 "Pressure"（历史 bug），两侧都非法 → 两条非法枚举差异
    illegal = [d for d in diffs if d["kind"] == "illegal_enum_value"]
    if mio.schema_available():
        assert len(illegal) == 2, [d["evidence"] for d in illegal]
        assert all(d["key"] == "load1.forceType" for d in illegal)
    else:
        assert illegal == []
    readback = [d for d in diffs if d["kind"] == "unreadable_in_probe"]
    assert sorted(d["key"] for d in readback) == ["T_max_ref", "mesh.num_elements"]


def test_cross_check_reports_parameter_expression_mismatch() -> None:
    spec = mio.parse_matlab_export(_sample_text())
    probe = _probe_fixture()
    probe["parameters"][0]["expression"] = "0.02[m]"
    diffs = mio.cross_check(spec, probe)
    hit = [d for d in diffs if d["dimension"] == "parameter.expression" and d["key"] == "Lx"]
    assert len(hit) == 1
    assert hit[0]["kind"] == "value_mismatch"
    assert hit[0]["spec_value"] == "0.01[m]"
    assert hit[0]["probe_value"] == "0.02[m]"

def test_cross_check_reports_unit_mismatch_without_converting() -> None:
    """数值相同但单位声明不同 → 报 ``unit_mismatch``，绝不做单位换算后当作一致。"""
    spec = mio.parse_matlab_export(_sample_text())
    probe = _probe_fixture()
    probe["parameters"][1]["expression"] = "8[m]"  # spec 侧是 8[mm]：数值同为 8、单位不同
    diffs = mio.cross_check(spec, probe)
    hit = [d for d in diffs if d["dimension"] == "parameter.unit" and d["key"] == "Ly"]
    assert len(hit) == 1
    assert hit[0]["kind"] == "unit_mismatch"
    assert hit[0]["spec_value"] == "[mm]"
    assert hit[0]["probe_value"] == "[m]"


def test_number_and_unit_extraction() -> None:
    assert mio._number_and_unit("0.01[m]") == (0.01, "[m]")
    assert mio._number_and_unit("1[W/(m*K)]") == (1.0, "[W/(m*K)]")
    assert mio._number_and_unit(0.27) == (0.27, None)
    assert mio._number_and_unit("T0+q_in*Lx/k_cond") == (None, None)


def test_cross_check_does_not_merge_enum_differences() -> None:
    """枚举原文不同必须报差异，不得归一成「差不多」。"""
    spec = mio.parse_matlab_export(_sample_text())
    probe = _probe_fixture()
    probe["physics"][0]["features"][0]["properties"][0]["value"] = "ForceArea"
    diffs = mio.cross_check(spec, probe)
    hit = [d for d in diffs if d["key"] == "load1.forceType" and d["dimension"].startswith("physics")]
    assert len(hit) == 1
    assert hit[0]["probe_value"] == "ForceArea"
    assert hit[0]["spec_value"] == "Pressure"


def test_cross_check_reports_selection_entity_mismatch() -> None:
    spec = mio.parse_matlab_export(_sample_text())
    probe = _probe_fixture()
    probe["physics"][0]["features"][0]["selection"] = [4]
    diffs = mio.cross_check(spec, probe)
    hit = [d for d in diffs if d["dimension"] == "physics.feature.selection"]
    assert len(hit) == 1, [d["key"] for d in hit]
    assert hit[0]["key"] == "load1"
    assert hit[0]["spec_value"] == [4, 5]
    assert hit[0]["probe_value"] == [4]


def test_cross_check_reports_missing_both_ways() -> None:
    spec = mio.parse_matlab_export(_sample_text())
    probe = _probe_fixture()
    probe["parameters"].append({"name": "extra", "expression": "1", "value": 1})
    diffs = mio.cross_check(spec, probe)
    kinds = {d["kind"] for d in diffs}
    assert "missing_in_spec" in kinds  # probe 有 extra
    assert not any(d["kind"] == "missing_in_probe" for d in diffs)


def test_cross_check_treats_unreadable_value_as_difference() -> None:
    """表达式一致但运行时求值失败 → 报 unreadable_in_probe，不得当成一致。"""
    spec = mio.parse_matlab_export(_sample_text())
    diffs = mio.cross_check(spec, _probe_fixture())
    hit = [d for d in diffs if d["dimension"] == "parameter.value"]
    assert len(hit) == 1
    assert hit[0]["key"] == "T_max_ref"
    assert hit[0]["kind"] == "unreadable_in_probe"


def test_cross_check_none_side_is_reported_not_assumed_equal() -> None:
    spec = mio.parse_matlab_export(_sample_text())
    diffs = mio.cross_check(spec, None)
    assert len(diffs) == 1
    assert diffs[0]["kind"] == "missing_side"
    assert "probe" in diffs[0]["key"]


def test_cross_check_reports_unparsed_spec() -> None:
    spec = mio.parse_matlab_export("garbage\n")
    diffs = mio.cross_check(spec, _probe_fixture())
    assert any(d["kind"] == "spec_not_parsed" for d in diffs)


# ======================================================================================
# 6. 依赖真实 COMSOL 的路径（环境缺失即 skip）
# ======================================================================================


# 真实模型的搜寻必须在**导入时**定下根目录：isolated_work fixture 会把 MEMS_WORK_ROOT
# 改到 work/.test-tmp/<uuid>，那时再去读 work_root() 就找不到真实的 runs 了（实测踩过：
# 两个依赖 COMSOL 的用例被静默 skip 成「没有真实模型」）。
_REAL_WORK_ROOT = work_root()


def _find_real_model() -> Path | None:
    """在真实运行区下找一个可用的 .mph（优先 runs 里的求解产物，排除测试占位文件）。"""
    runs = _REAL_WORK_ROOT / "runs"
    if not runs.is_dir():
        return None
    for pattern in ("out_Model.mph", "out.mph", "input.mph"):
        for candidate in sorted(runs.glob(f"*/{pattern}")):
            try:
                if candidate.is_file() and candidate.stat().st_size > 100_000:
                    return candidate
            except OSError:
                continue
    for candidate in sorted(runs.glob("*/*.mph")):
        try:
            if candidate.is_file() and candidate.stat().st_size > 100_000:
                return candidate
        except OSError:
            continue
    return None


def _probe_work_root() -> Path:
    """探针产物落点：真实运行区下的临时子目录（不要污染 runs/）。"""
    target = _REAL_WORK_ROOT / ".test-tmp" / f"modelio-probe-{uuid.uuid4().hex}"
    target.mkdir(parents=True, exist_ok=True)
    return target


@requires_comsol
def test_probe_model_on_real_model() -> None:
    """真实 .mph 的只读探针：必须有 run_id、参数表非空、原件哈希不变。"""
    model = _find_real_model()
    if model is None:
        pytest.skip("work/runs 下没有可用的真实 .mph（未跑过任何求解）")
    result = mio.probe_model(model, work_root=_probe_work_root())
    assert result["run_id"].startswith("probe-")
    assert Path(result["run_dir"]).is_dir()
    assert result["source"]["original_untouched"] is True
    if not result["ok"]:
        pytest.fail(
            f"探针失败：diagnostic={(result.get('diagnostic') or {}).get('code')} "
            f"payload_error={result.get('payload_error')} log_tail={result.get('log_tail')}"
        )
    assert result["parameters"], "真实模型应当有全局参数表"
    assert isinstance(result["readback"], list) and result["readback"]
    # 包围盒必须来自网格顶点坐标，且是真实跨度（曾把 [ndim][nvert] 读成 [nvert][ndim]，
    # 得到 (0,0)x(0,1.25e-05) 这种与模型无关的假盒子）
    boxes = result["bounding_box"]
    assert boxes, "真实模型应当能读到网格顶点包围盒"
    box = boxes[0]
    assert box["n_vertices"] and box["n_vertices"] > 10
    for axis in ("x", "y"):
        lo, hi = box[axis]
        assert hi > lo, f"{axis} 方向跨度为 0：包围盒读取有问题（{box}）"
    # 物理场特征与网格统计必须读到具体内容（不是空列表/None）
    assert result["physics"] and result["physics"][0]["features"]
    assert result["mesh"] and result["mesh"][0]["num_elements"]


@requires_comsol
def test_set_parameters_rejects_unknown_name_on_real_model() -> None:
    """未知参数名必须整体拒绝，并回列合法参数名（绝不新建参数）。"""
    model = _find_real_model()
    if model is None:
        pytest.skip("work/runs 下没有可用的真实 .mph（未跑过任何求解）")
    result = mio.set_parameters(
        model, {"definitely_not_a_parameter_xyz": "1"}, work_root=_probe_work_root()
    )
    assert result["rejected"] is True
    assert result["ok"] is False
    assert result["unknown_parameters"] == ["definitely_not_a_parameter_xyz"]
    assert result["legal_parameter_names"], "被拒时必须回列合法参数名"
    assert result["output_path"] is None


@requires_comsol
def test_set_parameters_round_trip_on_real_model() -> None:
    """真实写入通路：把某个参数设成它**当前**的表达式，验证「设值 + 回读 + 另存」闭环。

    用当前表达式是为了不动模型语义（等价于幂等写入），但足以证实：
    参数确实被写入、回读值等于所写、新副本确实生成且哈希与源模型不同、
    源模型哈希未变。几何比较关掉（省两次批处理）：此时 ``geometry_changing`` 必须是
    ``None``（= 未判定），**不是** ``False``。
    """
    model = _find_real_model()
    if model is None:
        pytest.skip("work/runs 下没有可用的真实 .mph（未跑过任何求解）")
    work = _probe_work_root()
    probe = mio.probe_model(model, work_root=work)
    if not probe.get("ok") or not probe.get("parameters"):
        pytest.skip(f"探针未取得参数表：{probe.get('payload_error') or probe.get('diagnostic')}")
    # 挑一个表达式可原样写回的参数（跳过派生表达式，避免与「不得猜内部」相冲突）
    pick = None
    for row in probe["parameters"]:
        expr = row.get("expression")
        if isinstance(expr, str) and expr and "(" not in expr and not expr.startswith("-"):
            pick = (row["name"], expr)
            break
    if pick is None:
        pytest.skip("该模型的参数表达式都是派生式，无法做幂等写回")

    result = mio.set_parameters(
        model, {pick[0]: pick[1]}, work_root=work, baseline_geometry=False
    )
    assert result["ok"] is True, result["diagnostic"]
    entry = next(item for item in result["diff"] if item["name"] == pick[0])
    assert entry["applied"] is True, entry
    assert entry["expression_after"] == pick[1]
    # 幂等写入：写前读回也应等于同一个表达式（且来源标注为 before_readback）
    assert entry["expression_before"] == pick[1]
    assert entry["expression_before_source"] == "before_readback"
    assert entry["value_before_source"] == "before_readback"
    assert entry["value_after_source"] == "after_readback"
    assert entry["value_before"] == entry["value_after"]
    assert entry["apply_error"] is None
    assert result["source_original_untouched"] is True
    output = Path(result["output_path"])
    assert output.is_file() and output.stat().st_size > 0
    assert result["output_sha256"] != result["source_sha256"]


@requires_comsol
def test_set_parameters_real_change_reports_true_before_value() -> None:
    """真改一个数值参数：``value_before`` 必须是**改动前**的读数（实测 case 01 的回归）。

    历史缺陷：改 ``v0`` 时 diff 里 ``value_before == value_after == 2.0``，而改动前是 1.0。
    这里选一个"纯数值 + 单位"的参数，把它改成**两倍**（语义上仍可求解，只多跑一次批处理），
    断言 ``value_before`` 等于改动前表达式算出的值、``value_after`` 等于两倍值，且二者不同。
    """
    model = _find_real_model()
    if model is None:
        pytest.skip("work/runs 下没有可用的真实 .mph（未跑过任何求解）")
    work = _probe_work_root()
    probe = mio.probe_model(model, work_root=work)
    if not probe.get("ok") or not probe.get("parameters"):
        pytest.skip(f"探针未取得参数表：{probe.get('payload_error') or probe.get('diagnostic')}")

    import re as _re

    pick = None
    for row in probe["parameters"]:
        expr = row.get("expression")
        value = row.get("value")
        match = _re.fullmatch(r"\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*(\[[^\]]*\])\s*", expr or "")
        if match and isinstance(value, (int, float)) and float(value) != 0.0:
            pick = (row["name"], float(match.group(1)), match.group(2))
            break
    if pick is None:
        pytest.skip("该模型没有'纯数值+单位'形式的参数，无法做确定性的改值验证")

    name, original, unit = pick
    target = original * 2.0
    # 用简单小数形式写回（repr 可能给出 '2e-05'，COMSOL 未必认这种写法）
    wanted = f"{target:.12g}{unit}"
    result = mio.set_parameters(model, {name: wanted}, work_root=work, baseline_geometry=False)
    assert result["ok"] is True, result["diagnostic"]
    entry = next(item for item in result["diff"] if item["name"] == name)
    assert entry["applied"] is True, entry
    assert entry["value_before"] == pytest.approx(original), (
        f"value_before 不是改动前的值：{entry}"
    )
    assert entry["value_after"] == pytest.approx(target)
    assert entry["value_before"] != entry["value_after"], "改值前后必须不同，否则这次验证没有意义"
    assert entry["expression_before"] != entry["expression_after"]


# ======================================================================================
# 7. 本地权威 schema（COMSOL 补全数据 physics.xml）
# ======================================================================================


@pytest.fixture()
def fake_completion(tmp_path: Path) -> Path:
    """自造的补全数据 XML（覆盖"有 schema 但环境不是本机 COMSOL"的路径）。"""
    path = tmp_path / "physics.xml"
    path.write_text(_FAKE_COMPLETION_XML, encoding="utf-8")
    mio.clear_schema_cache()
    yield path
    mio.clear_schema_cache()


def test_schema_missing_degrades_gracefully(tmp_path: Path) -> None:
    """找不到 XML 时必须**优雅降级 + 说明缺失**，绝不静默返回空结果假装成功。"""
    missing = tmp_path / "no-such-dir" / "physics.xml"
    assert mio.schema_available(missing) is False
    source = mio.schema_source(missing)
    assert source["available"] is False
    assert source["path"] is None
    assert source["error"]
    assert source["features_parsed"] == 0
    assert source["probes"] and source["probes"][0]["exists"] is False
    assert "不存在" in (source["probes"][0]["reason"] or "")

    schema = mio.lookup_feature_schema("BoundaryLoad", path=missing)
    assert schema["available"] is False
    assert schema["ok"] is False
    assert schema["reason"]
    assert schema["variants"] == []
    assert schema["note"] and "未校验" in schema["note"]

    enum = mio.lookup_enum("forceType", feature="BoundaryLoad", path=missing)
    assert enum["ok"] is False
    assert enum["values"] is None, "不可用时必须是 None（未校验），不能是空列表（会被当成无限制）"
    assert enum["probes"]

    check = mio.validate_enum_value("BoundaryLoad", "forceType", "X", path=missing)
    assert check["checked"] is False
    assert check["in_union"] is None
    assert check["reason"]


def test_validate_enum_value_reports_unchecked_for_broken_xml(tmp_path: Path) -> None:
    """XML 损坏 → available=True（路径存在）但 ok=False，并且仍然不是「校验通过」。"""
    broken = tmp_path / "physics.xml"
    broken.write_text("<COMSOLCompletionData><unclosed>", encoding="utf-8")
    mio.clear_schema_cache()
    try:
        assert mio.schema_available(broken) is False
        source = mio.schema_source(broken)
        assert source["available"] is False
        assert "解析失败" in (source["error"] or "")
        check = mio.validate_enum_value("BoundaryLoad", "forceType", "ForceArea", path=broken)
        assert check["checked"] is False
    finally:
        mio.clear_schema_cache()


def test_fake_schema_rejects_unknown_root(tmp_path: Path) -> None:
    """根标签不是 COMSOLCompletionData → 拒绝使用（不猜格式）。"""
    other = tmp_path / "physics.xml"
    other.write_text('<?xml version="1.0"?><SomethingElse><a name="x" props="p"/></SomethingElse>',
                     encoding="utf-8")
    mio.clear_schema_cache()
    try:
        assert mio.schema_available(other) is False
        assert "COMSOLCompletionData" in (mio.schema_source(other)["error"] or "")
    finally:
        mio.clear_schema_cache()


def test_lookup_feature_schema_with_fake_xml(fake_completion: Path) -> None:
    """按 name + topic 过滤：同名特征的两个变体必须能分开取。"""
    all_variants = mio.lookup_feature_schema("FakeLoad", path=fake_completion)
    assert all_variants["ok"] is True
    assert all_variants["variant_count"] == 3
    assert all_variants["topics"] == ["fake_bndl", "other_bndl"]
    # 并集：三个变体的 forceType 取值合并
    assert all_variants["enum_union"]["forceType"] == ["ForceArea", "TotalForce", "FollowerPressure"]
    # 交集：只有 fake03 具备 FollowerPressure
    assert all_variants["enum_intersection"]["forceType"] == ["ForceArea", "TotalForce"]
    assert all_variants["enum_variant_dependent"]["forceType"] == ["FollowerPressure"]

    one = mio.lookup_feature_schema("FakeLoad", topic="other_bndl", path=fake_completion)
    assert one["variant_count"] == 2  # other_bndl 有 fake03 / fake04 两个变体
    assert one["topics"] == ["fake_bndl", "other_bndl"]  # topics 恒为该特征的全部 topic
    assert one["topic_filter"] == "other_bndl"
    assert one["enum_union"]["forceType"] == ["ForceArea", "TotalForce", "FollowerPressure"]
    assert one["enum_intersection"]["forceType"] == ["ForceArea", "TotalForce"]
    assert one["enum_variant_dependent"]["forceType"] == ["FollowerPressure"]

    # 非枚举属性（pressure，只出现在 fake_bndl 变体里）：values 为空但属性存在
    # —— 必须与"查不到该属性"区分开
    with_pressure = mio.lookup_feature_schema("FakeLoad", topic="fake_bndl", path=fake_completion)
    assert with_pressure["docs"]["pressure"][0]["values"] == []
    assert with_pressure["docs"]["pressure"][0]["is_enum"] is False
    assert "pressure" not in one["docs"], "other_bndl 变体没有 pressure 属性——不得跨变体混入"


def test_lookup_feature_schema_missing_feature_and_topic(fake_completion: Path) -> None:
    absent = mio.lookup_feature_schema("NoSuchFeature", path=fake_completion)
    assert absent["available"] is True
    assert absent["ok"] is False
    assert "没有特征" in (absent["reason"] or "")

    no_topic = mio.lookup_feature_schema("FakeLoad", topic="nope", path=fake_completion)
    assert no_topic["ok"] is False
    assert no_topic["topics"] == ["fake_bndl", "other_bndl"], "必须回列可用 topic，不静默退回全部变体"
    assert no_topic["variant_count"] == 0


def test_lookup_feature_schema_requires_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="非空"):
        mio.lookup_feature_schema("", path=tmp_path / "physics.xml")


def test_lookup_enum_with_fake_xml(fake_completion: Path) -> None:
    enum = mio.lookup_enum("forceType", feature="FakeLoad", path=fake_completion)
    assert enum["ok"] is True
    assert enum["is_enum"] is True
    assert enum["values"] == ["ForceArea", "TotalForce", "FollowerPressure"]
    assert enum["intersection_values"] == ["ForceArea", "TotalForce"]
    assert enum["variant_dependent_values"] == ["FollowerPressure"]
    assert enum["default"] == "ForceArea"
    assert enum["descr"] == "Load_type"

    # 按 topic 收窄：other_bndl 的两个变体仍有差异（fake03 多一个 FollowerPressure）
    narrowed = mio.lookup_enum(
        "forceType", feature="FakeLoad", topic="other_bndl", path=fake_completion
    )
    assert narrowed["values"] == ["ForceArea", "TotalForce", "FollowerPressure"]
    assert narrowed["intersection_values"] == ["ForceArea", "TotalForce"]
    assert narrowed["variant_dependent_values"] == ["FollowerPressure"]

    # 属性存在但不是枚举：ok=True + values=[]，与"查不到"（ok=False + values=None）严格区分
    non_enum = mio.lookup_enum(
        "pressure", feature="FakeLoad", topic="fake_bndl", path=fake_completion
    )
    assert non_enum["ok"] is True and non_enum["is_enum"] is False
    assert non_enum["values"] == []
    assert "没有枚举取值" in (non_enum["note"] or "")

    missing_prop = mio.lookup_enum("notAProperty", feature="FakeLoad", path=fake_completion)
    assert missing_prop["ok"] is False
    assert missing_prop["values"] is None

    # 不给 feature：全表同名属性并集；口径更宽，必须显式标注
    global_enum = mio.lookup_enum("forceType", path=fake_completion)
    assert global_enum["ok"] is True
    assert global_enum["values"] == ["ForceArea", "TotalForce", "FollowerPressure"]
    assert "全表同名属性" in (global_enum["note"] or "")

    with pytest.raises(ValueError, match="非空"):
        mio.lookup_enum("", path=fake_completion)


def test_labels_are_not_used_as_legality_criterion(fake_completion: Path) -> None:
    """``descrs``（人类标签）里有 ``Pressure``，但它**不是**合法取值——判定必须看 values。

    这正是历史 bug 的成因：标签像"压力"，就被当成了能写进去的枚举值。
    """
    schema = mio.lookup_feature_schema("FakeLoad", topic="fake_bndl", path=fake_completion)
    head = schema["docs"]["forceType"][0]
    assert head["values"] == ["ForceArea", "TotalForce"]
    assert "Pressure" not in head["values"]
    # 标签里确实出现 Pressure 字样（fake03 的 descrs），但它不是任何变体的合法取值
    enum = mio.lookup_enum("forceType", feature="FakeLoad", topic="fake_bndl", path=fake_completion)
    assert "Pressure" not in enum["values"]
    check = mio.validate_enum_value(
        "FakeLoad", "forceType", "Pressure", topic="fake_bndl", path=fake_completion
    )
    assert check["checked"] is True
    assert check["in_union"] is False
    assert "不是" in (check["reason"] or "")


def test_validate_enum_value_levels(fake_completion: Path) -> None:
    ok = mio.validate_enum_value("FakeLoad", "forceType", "FollowerPressure", path=fake_completion)
    assert ok["checked"] is True and ok["in_union"] is True
    assert ok["variant_dependent"] is True, "只在部分变体合法 → 必须标出来让人确认"

    safe = mio.validate_enum_value("FakeLoad", "forceType", "TotalForce", path=fake_completion)
    assert safe["in_union"] is True and safe["variant_dependent"] is False

    bad = mio.validate_enum_value("FakeLoad", "forceType", "Bogus", path=fake_completion)
    assert bad["in_union"] is False

    non_enum = mio.validate_enum_value(
        "FakeLoad", "pressure", "123", topic="fake_bndl", path=fake_completion
    )
    assert non_enum["checked"] is True, "属性存在但没有枚举取值：可区分，不是「没查到」"
    assert non_enum["legal_values"] == []
    assert non_enum["in_union"] is None

    with pytest.raises(ValueError, match="非空"):
        mio.validate_enum_value("", "forceType", "x", path=fake_completion)


def test_build_enum_validation_unknown_feature_is_unresolved(fake_completion: Path) -> None:
    """特征类型在 schema 里查不到 → 进 unresolved，且**不计入已校验**。"""
    physics = [
        {
            "component": "comp1",
            "interface_tag": "solid",
            "interface_type": "SolidMechanics",
            "features": [
                {
                    "tag": "load1",
                    "type": "FakeLoad",
                    "properties": [
                        {"name": "forceType", "value": "FollowerPressure"},
                        {"name": "forceTypeBad", "value": "nope"},
                    ],
                },
                {
                    "tag": "weird1",
                    "type": "NotInSchema",
                    "properties": [{"name": "forceType", "value": "whatever"}],
                },
            ],
        }
    ]
    report = mio.build_enum_validation(physics, path=fake_completion)
    assert report["available"] is True
    assert report["enum_checked"] == 1
    assert report["variant_dependent"] and report["variant_dependent"][0]["feature_tag"] == "load1"
    assert report["illegal"] == []
    # forceTypeBad 在全表里存在但无枚举取值 → 归为「无需枚举校验」，不算未校验；
    # 只有 NotInSchema 这个未知特征才是真正的 unresolved。
    assert len(report["unresolved"]) == 1
    assert report["unresolved"][0]["feature_type"] == "NotInSchema"
    bad_item = [
        item for entry in report["by_feature"] for item in entry["items"]
        if item["property"] == "forceTypeBad"
    ]
    assert bad_item and bad_item[0]["resolution"] == "not_an_enum_property"
    assert report["by_feature"][0]["topic_hint"] == "solid"  # 由接口类型推出的族前缀（仅提示）
    assert any("未能校验" in note for note in report["notes"])


def test_build_enum_validation_unavailable_is_explicit(tmp_path: Path) -> None:
    missing = tmp_path / "physics.xml"
    report = mio.build_enum_validation(
        [{"features": [{"tag": "a", "type": "BoundaryLoad",
                        "properties": [{"name": "forceType", "value": "Bogus"}]}]}],
        path=missing,
    )
    assert report["available"] is False
    assert report["checked_count"] == 0
    assert report["illegal"] == []
    assert any("未校验" in note for note in report["notes"])


@requires_completion
def test_real_completion_data_force_type_has_no_pressure() -> None:
    """真实补全数据：2D 结构力学的 BoundaryLoad 里 **不存在** ``"Pressure"``。

    实测证据（本机 COMSOL 6.4，``physics.xml``）：``topic="solid_bndl"`` 的 9 个变体，
    forceType 的合法取值并集 = ``ForceArea|ForceDefArea|TotalForce|FollowerPressure|Resultant``
    （还含 ForceLength/ForceDefLength），**每个变体都不含 Pressure**；
    ``Pressure`` 只出现在人类标签 ``descrs`` 里。
    这正是当初 ``set("forceType","Pressure")`` 抛异常被吞、载荷为零的根因。
    """
    mio.clear_schema_cache()
    try:
        source = mio.schema_source()
        assert source["available"] is True
        assert source["features_parsed"] > 1000
        assert source["enum_properties_parsed"] > 1000
        assert source["sha256"] and source["size_bytes"]

        enum = mio.lookup_enum("forceType", feature="BoundaryLoad", topic="solid_bndl")
        assert enum["ok"] is True
        values = set(enum["values"])
        required = {"ForceArea", "ForceDefArea", "TotalForce", "FollowerPressure", "Resultant"}
        assert required <= values, f"缺少用户实测给出的合法值：{required - values}"
        assert "Pressure" not in values
        assert "Pressure" not in set(enum["intersection_values"])
        # 每个变体单独看也都不含 Pressure
        for definition in enum["definitions"]:
            assert "Pressure" not in set(definition["values"])

        check = mio.validate_enum_value("BoundaryLoad", "forceType", "Pressure", topic="solid_bndl")
        assert check["checked"] is True
        assert check["in_union"] is False
        assert "FollowerPressure" in (check["reason"] or "")
    finally:
        mio.clear_schema_cache()


@requires_completion
def test_real_completion_data_feature_docs() -> None:
    """真实补全数据里能取到特征的真实属性名与默认值（供报告与改参前核对）。"""
    mio.clear_schema_cache()
    try:
        schema = mio.lookup_feature_schema("BoundaryLoad", topic="solid_bndl")
        assert schema["ok"] is True
        assert schema["variant_count"] >= 1
        force_type = schema["docs"]["forceType"][0]
        assert force_type["default"] == "ForceArea"
        assert force_type["type"] == "String"
        assert force_type["labels"], "人类标签也要取到（用于报告展示，但不参与合法性判定）"
    finally:
        mio.clear_schema_cache()


# ======================================================================================
# 8. schema 用于 M-file 解析与交叉校验
# ======================================================================================


def test_m_parser_flags_illegal_enum_with_real_schema() -> None:
    """``forceType='Pressure'``（历史 bug）必须被解析器标成非法枚举值。"""
    if not mio.schema_available():
        pytest.skip("本机没有 COMSOL 补全数据，枚举校验不可用（已由降级用例覆盖）")
    spec = mio.parse_matlab_export(_sample_text())
    report = spec["enum_validation"]
    assert report["available"] is True
    assert report["enum_checked"] >= 1
    illegal = {(item["feature_tag"], item["property"]): item for item in report["illegal"]}
    assert ("load1", "forceType") in illegal, report["illegal"]
    entry = illegal[("load1", "forceType")]
    assert entry["value"] == "Pressure"
    assert entry["in_union"] is False
    assert "FollowerPressure" in entry["legal_values"]

    # 合法值不应被误报
    good = _sample_text().replace(
        ".set('forceType', 'Pressure')", ".set('forceType', 'FollowerPressure')"
    )
    assert mio.parse_matlab_export(good)["enum_validation"]["illegal"] == []


def test_m_parser_validate_enums_can_be_switched_off() -> None:
    spec = mio.parse_matlab_export(_sample_text(), validate_enums=False)
    assert spec["enum_validation"] is None


def test_m_parser_notes_missing_schema(tmp_path: Path) -> None:
    """schema 不可用时必须在 notes 里说明，而不是静默无差异。"""
    missing = tmp_path / "physics.xml"
    report = mio.build_enum_validation(
        mio.parse_matlab_export(_sample_text(), validate_enums=False)["physics"], path=missing
    )
    assert report["available"] is False
    spec = mio.parse_matlab_export(_sample_text(), validate_enums=False)
    spec["enum_validation"] = report
    diffs = mio.cross_check(spec, None)
    assert diffs and diffs[0]["kind"] == "missing_side"


def test_cross_check_reports_enum_validation_gaps() -> None:
    """两侧都没有校验结果时，必须报 "未校验"，不能表现为"零差异=没问题"。"""
    spec = mio.parse_matlab_export(_sample_text(), validate_enums=False)
    probe = _probe_fixture()
    probe.pop("enum_validation", None)
    diffs = mio.cross_check(spec, probe)
    kinds = {d["kind"] for d in diffs}
    assert "enum_validation_missing" in kinds
    assert {d["key"] for d in diffs if d["kind"] == "enum_validation_missing"} == {"spec", "probe"}


def test_cross_check_reports_illegal_enum_on_either_side() -> None:
    """非法枚举值必须作为差异报出（即使文本与运行态"一致地错"）。"""
    spec = mio.parse_matlab_export(_sample_text(), validate_enums=False)
    probe = _probe_fixture()
    illegal_item = {
        "feature_type": "BoundaryLoad",
        "feature_tag": "load1",
        "property": "forceType",
        "value": "Pressure",
        "checked": True,
        "in_union": False,
        "variant_dependent": False,
        "legal_values": ["ForceArea", "FollowerPressure"],
        "reason": "'Pressure' 不是合法取值",
        "resolution": "illegal_enum_value",
    }
    report = {
        "available": True,
        "checked_count": 1,
        "enum_checked": 1,
        "illegal": [illegal_item],
        "variant_dependent": [],
        "unresolved": [],
        "by_feature": [],
        "notes": [],
    }
    spec["enum_validation"] = report
    probe["enum_validation"] = {**report, "illegal": [{**illegal_item, "value": "ForceArea2"}]}
    diffs = mio.cross_check(spec, probe)
    illegal = [d for d in diffs if d["kind"] == "illegal_enum_value"]
    assert len(illegal) == 2, "两侧各自的非法值都要报（不合并、不取平均）"
    assert {d["key"] for d in illegal} == {"load1.forceType"}
    assert any("spec" in d["reason"] for d in illegal)
    assert any("probe" in d["reason"] for d in illegal)
    assert all(d["evidence"] for d in illegal)


def test_cross_check_reports_variant_dependent_and_unresolved() -> None:
    spec = mio.parse_matlab_export(_sample_text(), validate_enums=False)
    probe = _probe_fixture()
    item = {
        "feature_type": "BoundaryLoad",
        "feature_tag": "load1",
        "property": "forceType",
        "value": "FollowerPressure",
        "checked": True,
        "in_union": True,
        "variant_dependent": True,
        "legal_values": ["ForceArea", "FollowerPressure"],
        "reason": "只在部分变体合法",
        "resolution": "variant_dependent",
    }
    un = {**item, "resolution": "unresolved", "checked": False, "in_union": None,
          "reason": "属性在 schema 里查不到", "property": "unknownProp"}
    report = {
        "available": True,
        "checked_count": 2,
        "enum_checked": 1,
        "illegal": [],
        "variant_dependent": [item],
        "unresolved": [un],
        "by_feature": [],
        "notes": [],
    }
    spec["enum_validation"] = report
    probe["enum_validation"] = report
    diffs = mio.cross_check(spec, probe)
    kinds = {d["kind"] for d in diffs}
    assert "variant_dependent_enum_value" in kinds
    assert "enum_not_checked" in kinds


def test_cross_check_reports_no_enum_targets() -> None:
    """schema 可用但没有任何枚举被校验过 → 必须显式说"没有校验对象"。"""
    empty = {
        "available": True,
        "checked_count": 0,
        "enum_checked": 0,
        "illegal": [],
        "variant_dependent": [],
        "unresolved": [],
        "by_feature": [],
        "notes": [],
    }
    spec = mio.parse_matlab_export(_sample_text(), validate_enums=False)
    probe = _probe_fixture()
    spec["enum_validation"] = empty
    probe["enum_validation"] = empty
    # 去掉其它差异源，只看枚举那一条：两侧参数/特征/选择/研究步骤全部对齐，
    # 并且把 probe 的 readback 清空、T_max_ref 求值错误清掉。
    probe["readback"] = []
    probe["parameters"][3]["value_error"] = None
    probe["physics"][0]["features"][1]["selection"] = [1]   # fix1：与 spec 一致
    probe["physics"][0]["features"][0]["selection"] = [4, 5]  # load1：与 spec 一致
    diffs = mio.cross_check(spec, probe)
    assert [d["kind"] for d in diffs] == ["enum_validation_no_targets"], diffs


# ======================================================================================
# 9. 真实 GUI 导出（不是 fixture）的回归用例
# ======================================================================================
#
# 为什么必须有这一节：`bGEtask2.m` 是真实 GUI 导出（sha256 03a8629…c44d0），
# 它暴露了两个只靠自造 fixture 发现不了的结构性缺口：
#   1) 研究段整段写在主函数里（没有 ``model_study`` 子函数），而 ``_parse_study`` 当时
#      只拿 ``blocks["study"]`` ⇒ study 解析为**空列表**；
#   2) 研究/求解器/几何/网格/后处理的赋值都是 ``...feature('x').set(...)`` 形状，
#      被物理场解析器误记成"指向未见过的物理场特征"（255 条 unknown_assignments）。
# 自造 fixture 全都是"教科书式"的 ``model_parameters`` 分块导出，永远碰不到这两点。


@requires_real_m_export
def test_real_gui_export_parses_study_section() -> None:
    """真实导出的研究段必须解析出来（这是本节的直接回归目标）。"""
    spec = mio.parse_matlab_export(_REAL_M_EXPORT, validate_enums=False)
    assert spec["parsed"] is True
    assert spec["study"], "真实导出的 study 段不得为空（曾整段落空）"
    studies = {s["tag"]: s for s in spec["study"]}
    assert "std1" in studies, list(studies)
    steps = {st["tag"]: st for st in studies["std1"]["steps"]}
    assert "freq" in steps, steps
    freq = steps["freq"]
    assert freq["type"] == "Frequency"


@requires_real_m_export
def test_real_gui_export_frequency_sweep_is_readable() -> None:
    """扫频信息必须可读：频点列表（含最后一次赋值）与研究步激活的物理场。"""
    spec = mio.parse_matlab_export(_REAL_M_EXPORT, validate_enums=False)
    freq = next(
        st for s in spec["study"] for st in s["steps"] if st["tag"] == "freq"
    )
    # plist 在导出里被 set 多次（不同扫描范围的历史）→ 历史与"最后一次"都要留着
    plist_history = [p["value"] for p in freq["properties"] if p["name"] == "plist"]
    assert len(plist_history) > 1, plist_history
    assert any("range(" in str(v) for v in plist_history)
    assert freq["last_wins"]["plist"] == plist_history[-1]
    # 实测：最后一次是 5/10/15/20/25/30/35 MHz 的显式列表
    assert "35[MHz]" in str(freq["last_wins"]["plist"])
    # 研究步激活的物理场接口（原文，含布尔）
    activated = {a["interface"]: a["active"] for a in freq["activated_physics"]}
    assert {"acpr", "solid", "es"} <= set(activated)
    assert activated["acpr"] == "true"


@requires_real_m_export
def test_real_gui_export_solver_binding_is_readable() -> None:
    """求解器序列：绑定到哪个研究、有哪些占位名（st1/v1/s1），且**不重复**。"""
    spec = mio.parse_matlab_export(_REAL_M_EXPORT, validate_enums=False)
    assert spec["solvers"], "求解器段不得为空"
    sol = spec["solvers"][0]
    assert sol["tag"] == "sol1"
    assert sol["study"] == "std1"
    tags = [f["tag"] for f in sol["features"]]
    assert tags == ["st1", "v1", "s1"], f"求解器特征应去重且保序，实际 {tags}"
    assert {f["tag"]: f["type"] for f in sol["features"]}["st1"] == "StudyStep"


@requires_real_m_export
def test_real_gui_export_unknown_assignments_stay_bounded() -> None:
    """``unknown_assignments`` 必须收敛到极少数**真**未归类项。

    实测口径：修复前 255 条（其中 244 条是研究/求解器赋值被物理场解析器误收）；
    修复后 4 条（3 条是导出里确实缺 create 语句的物理场属性 + 1 条缺父绘图组的后处理特征）。
    这个上限是防回归的哨兵：一旦分类逻辑退化，数字会立刻反弹。
    """
    spec = mio.parse_matlab_export(_REAL_M_EXPORT, validate_enums=False)
    unknown = spec["unknown_assignments"]
    assert len(unknown) <= 10, f"unknown_assignments 反弹到 {len(unknown)} 条：{unknown[:5]}"
    # 误报过的三类必须**不再**出现在 unknown 里
    texts = " ".join(str(u.get("text")) for u in unknown)
    for bad in ("plist", "studystep", "geom('geom1').feature", "result('pg1')"):
        assert bad not in texts, bad
    # 剩下的是真问题（缺 create 语句），且原因写得清楚
    assert all(u.get("reason") for u in unknown)


@requires_real_m_export
def test_real_gui_export_sections_and_enums() -> None:
    """同一份真实导出的其它段落：参数/材料/几何维数/物理场/后处理都要正确。"""
    spec = mio.parse_matlab_export(_REAL_M_EXPORT)
    unique_params = {p["name"] for p in spec["parameters"]}
    assert len(unique_params) == 37, sorted(unique_params)
    assert len(spec["materials"]) == 5
    geom = {g["tag"]: g for g in spec["geometry"]}
    assert geom["geom1"]["dimension"] == 3, "维数必须是数值 3，不得被局部几何的 'Rectangle' 覆盖"
    assert {"wp1", "sca1", "sph1"} <= {f["tag"] for f in geom["geom1"]["features"]}
    ifaces = {i["interface_tag"]: i["interface_type"] for i in spec["physics"]}
    assert ifaces["acpr"] == "PressureAcoustics"
    assert ifaces["solid"] == "SolidMechanics"
    assert ifaces["es"] == "Electrostatics"
    assert any(g["tag"] == "pg1" for g in spec["results"]), [g["tag"] for g in spec["results"]]
    # 枚举校验：确实执行过（不是"零校验却零差异"）
    if mio.schema_available():
        report = spec["enum_validation"]
        assert report["available"] is True
        assert report["checked_count"] > 0


# ======================================================================================
# 10. 参数 diff 的 before/after 同源缺陷（实测 case 01）
# ======================================================================================
#
# 实测缺陷（效验 case 01，真实模型 bGEtask2.mph）：改 v0 时 diff 里 value_before=2.0、
# value_after=2.0，而改动前是 **1.0**。根因是 Java 里 `beforeValue` 的 evaluate() 写在
# `set()` **之后**，"写前值"其实是写后重算的读数——diff 的 before 侧被 after 顶替。
# 这个字段是溯源证据（红线 1 + append-only 可回溯），错一次会让后续审计得出错误结论。
# 现在改成：Java 分两组独立读回（before_readback / after_readback），Python 由纯函数
# `build_parameter_diff` 组装，两侧不同源、结构上不可互换。


def _readback_pair(
    *,
    name: str = "v0",
    requested: Any = "2[V]",
    before_expr: Any = "1[V]",
    before_value: Any = 1.0,
    after_expr: Any = "2[V]",
    after_value: Any = 2.0,
    before_error: str | None = None,
    before_value_error: str | None = None,
    apply_error: str | None = None,
    before_read: bool = True,
) -> dict:
    """构造一条"模拟的 Java 读回"（before / after 两组分别给值）。"""
    return {
        "name": name,
        "requested": requested,
        "apply_error": apply_error,
        "before_readback": {
            "read": before_read,
            "expression": before_expr,
            "expression_error": before_error,
            "value": before_value,
            "value_error": before_value_error,
        },
        "after_readback": {
            "read": True,
            "expression": after_expr,
            "expression_error": None,
            "value": after_value,
            "value_error": None,
        },
    }


def test_diff_value_before_comes_from_before_readback_not_after() -> None:
    """核心回归：写前读回值 ≠ 写后读回值时，两侧必须各归各位（实测 case 01 的形状）。"""
    diff = mio.build_parameter_diff([_readback_pair()])
    assert len(diff) == 1
    entry = diff[0]
    assert entry["value_before"] == 1.0, f"before 被 after 顶替了：{entry}"
    assert entry["value_after"] == 2.0
    assert entry["value_before"] != entry["value_after"], "这一对读数本来就不同，不该相等"
    assert entry["expression_before"] == "1[V]"
    assert entry["expression_after"] == "2[V]"
    # 来源字段显式标注，审计时能一眼看出两侧不同源
    assert entry["value_before_source"] == "before_readback"
    assert entry["value_after_source"] == "after_readback"
    assert entry["value_before_reason"] is None
    assert entry["applied"] is True


def test_diff_value_before_none_is_not_backfilled_by_after() -> None:
    """写前读不到 → ``None`` + 原因；**绝不用 after 顶替**，也不静默省略。"""
    diff = mio.build_parameter_diff([
        _readback_pair(
            before_expr=None,
            before_value=None,
            before_error="com.comsol.util.exceptions.FlException: undefined parameter",
            before_value_error="com.comsol.util.exceptions.FlException: cannot evaluate",
            before_read=False,
        )
    ])
    entry = diff[0]
    assert entry["value_before"] is None, f"before 不得被 after 顶替：{entry}"
    assert entry["value_after"] == 2.0
    assert entry["value_before_reason"], "必须给出读不到的原因"
    assert "FlException" in entry["value_before_reason"]
    assert entry["expression_before"] is None
    assert "FlException" in (entry["expression_before_reason"] or "")
    # 显式写清"这不是 after 顶替"，避免审计误读
    assert "顶替" in entry.get("value_before_note", "")
    # 字段本身必须存在（不得静默省略）
    assert "value_before" in entry and "expression_before" in entry


def test_diff_missing_before_readback_section_is_explicit() -> None:
    """整段 before 读回缺失（结构都没有）→ 也要 None + 原因，而不是拿 after 充数。"""
    item = _readback_pair()
    item.pop("before_readback")
    entry = mio.build_parameter_diff([item])[0]
    assert entry["value_before"] is None
    assert entry["expression_before"] is None
    assert "缺失" in (entry["value_before_reason"] or "")


def test_diff_no_substitution_even_when_before_is_none_and_after_matches() -> None:
    """极端情形：before 读不到，而 after 恰好等于 requested —— 仍然不得回填。"""
    diff = mio.build_parameter_diff([
        _readback_pair(before_expr=None, before_value=None, before_value_error="no read")
    ])
    entry = diff[0]
    assert entry["value_before"] is None
    assert entry["applied"] is True  # applied 只看 after 侧，与 before 缺失无关


def test_diff_applied_detects_swallowed_write() -> None:
    """写入被静默吞掉（after 没变）→ applied=False，且 before/after 都如实记录。"""
    diff = mio.build_parameter_diff([
        _readback_pair(after_expr="1[V]", after_value=1.0)
    ])
    entry = diff[0]
    assert entry["applied"] is False
    assert entry["value_before"] == 1.0
    assert entry["value_after"] == 1.0


def test_diff_applied_is_none_when_after_unreadable() -> None:
    """写后表达式读不到 → applied 为 None（未判定），不是 False。"""
    item = _readback_pair()
    item["after_readback"] = {
        "read": False,
        "expression": None,
        "expression_error": "readback failed",
        "value": None,
        "value_error": "readback failed",
    }
    entry = mio.build_parameter_diff([item])[0]
    assert entry["applied"] is None
    assert entry["value_after"] is None
    assert entry["value_after_reason"]
    assert entry["value_before"] == 1.0
    assert entry["expression_after_reason"]


def test_diff_carries_apply_error_verbatim() -> None:
    """apply_error 只反映 set() 自身是否报错，不得被其它字段掩盖。"""
    diff = mio.build_parameter_diff([
        _readback_pair(apply_error="com.comsol.util.exceptions.FlException: bad value")
    ])
    assert diff[0]["apply_error"] == "com.comsol.util.exceptions.FlException: bad value"


def test_diff_empty_and_malformed_inputs() -> None:
    """空/畸形输入不得产出假条目（不猜内容）。"""
    assert mio.build_parameter_diff(None) == []
    assert mio.build_parameter_diff([]) == []
    assert mio.build_parameter_diff([None, "x", {"no_name": 1}]) == []


def test_diff_handles_multiple_parameters_independently() -> None:
    """多参数时每条 diff 必须各用自己那一对读数（避免索引串位）。"""
    diff = mio.build_parameter_diff([
        _readback_pair(name="v0", requested="2[V]", before_expr="1[V]", before_value=1.0,
                       after_expr="2[V]", after_value=2.0),
        _readback_pair(name="f0", requested="7[MHz]", before_expr="5[MHz]", before_value=5e6,
                       after_expr="7[MHz]", after_value=7e6),
    ])
    by_name = {d["name"]: d for d in diff}
    assert by_name["v0"]["value_before"] == 1.0 and by_name["v0"]["value_after"] == 2.0
    assert by_name["f0"]["value_before"] == 5e6 and by_name["f0"]["value_after"] == 7e6


def test_rendered_set_template_reads_before_value_before_writing() -> None:
    """静态不变量：生成的 Java 源码里，before 侧读回必须**全部早于** ``set()``。

    这条直接钉住那个缺陷的成因（beforeValue 的 evaluate 曾被放在 set 之后）；
    它不需要跑 COMSOL，因此能在默认测试里拦住回归。
    """
    src = mio.render_set_source(
        java_class="model_set_parameters",
        input_name="input.mph",
        output_name="m_modified.mph",
        names=["v0"],
        wanted=["2[V]"],
    )
    idx = {
        "expr_before": src.index("parameter_expression_before"),
        "value_before": src.index("parameter_value_before"),
        "set": src.index("model.param().set(name, WANTED[i])"),
        "expr_after": src.index("parameter_expression_after"),
        "value_after": src.index("parameter_value_after"),
    }
    assert idx["expr_before"] < idx["set"], idx
    assert idx["value_before"] < idx["set"], f"写前数值读回必须在 set 之前：{idx}"
    assert idx["set"] < idx["expr_after"], idx
    assert idx["set"] < idx["value_after"], idx
    # 结构上也必须是"两组独立读回"，不是一组变量复用
    # （Java 源码里 JSON 键写作 \"readbacks\"，故只断言裸标识符）
    assert "readbacks" in src
    assert '"changes"' not in src, "旧的单组 changes 结构已废除"
    # 两组读回各自成段（before 段 + after 段），不是一组变量复用
    assert src.count("before_readback") >= 1 and src.count("after_readback") >= 1
    # 旧的单组变量名不得回来：正是它让 before 与 after 同源
    assert "parameter_value:" not in src
    # Java 侧不再自行拼 diff 字段，只发两组原始读回；diff 由 Python 组装
    assert '"value_before"' not in src
    assert '"value_after"' not in src
    assert '"applied"' not in src
