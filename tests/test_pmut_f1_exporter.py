"""已保存解导出器的防误求解检查；可选 MATLAB 测试只使用 mphload 拒绝替身。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/pmut_f1_export_stored.m"


def test_exporter_has_no_solver_or_model_mutation_calls():
    source = SCRIPT.read_text(encoding="utf-8")
    code = "\n".join(line.split("%", 1)[0] for line in source.splitlines())
    forbidden = [r"\bmphsave\s*\(", r"\.run(?:All)?\s*\(",
                 r"\.param\s*\(", r"\.geom\s*\(", r"\.mesh\s*\(",
                 r"\.study\s*\(", r"\.sol\s*\(", r"model\.save\s*\("]
    for pattern in forbidden:
        assert not re.search(pattern, code), pattern
    assert "mphload(modelPath, modelTag)" in code
    assert "modelSha256 =" not in code


def test_identity_is_checked_for_all_values_and_point_reference_is_separate():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "any(abs(values - expected(index)) > tolerance(index))" in source
    assert "median(" not in source
    assert "scalar_table_reference_not_field_node" in source
    assert "'same_source_model_verified', false" in source
    assert "'geometry_material_bc_exported', false, 'training_ready', false" in source
    assert "'computed_from_file_bytes'" in source
    assert "'coord', [0; 0; -1e-5]" in source
    assert "'ext', 0, 'coorderr', 'on', 'matherr', 'on'" in source
    assert "'solnum', selected.inner_solnum" in source
    assert "tolerance = 1e-9 + 1e-6 * abs(reference)" in source
    assert "'point_reference_pressure_consistent', true" in source
    assert source.index("preflight(modelPath") < source.index("mphload(modelPath")
    assert source.index("export.source_model_sha256 = file_sha256") < source.index("mphload(modelPath")
    assert "assert_source_unchanged(modelPath, before);" in source
    assert "'PMUTF1:SourceChanged'" in source
    for phase in ('hash_start', 'hash_done', 'load_start', 'load_done', 'case_done', 'final'):
        assert f"PMUTF1 {phase}" in source
    assert source.index("write_report(outputRoot, export);") < source.index("export.source_model_sha256 = file_sha256")


def test_remote_launcher_is_fixed_scope_serial_and_non_destructive():
    launcher = REPO / "scripts/pmut_f1_export_remote.sh"
    source = launcher.read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith('#'))
    assert "ROOT=/home/lab/zhangmx/pmut_f1_export_20261016_v1" in source
    assert 'readonly EXPECTED_CASES=21' in source
    assert 'readonly MAX_MODEL_BYTES=322122547200' in source
    assert 'readonly MIN_MEMORY_KIB=125829120' in source
    assert 'readonly MIN_DISK_BYTES=21474836480' in source
    assert 'readonly WALL_SECONDS=7200' in source
    assert 'readonly NP=4' in source
    assert 'flock -n 9' in source and 'stop_owned_group' in source
    assert 'grep -q \'Done\' "$SOURCE.status"' in source
    assert '"$SOURCE.lock" "${SOURCE%.mph}.lock"' in source
    assert '-login auto -port 0 -portfile "$PORTFILE" -silent' in source
    assert 'mphstart($port)' in source
    assert 'connect_start' in source and 'connect_done' in source
    assert not re.search(r'\b(?:pkill|killall|rm|rmdir)\b|find\b.*-delete', code)
    assert not re.search(r'\b(?:export\s+)?HOME=', code)
    assert 'source_model_sha256' not in source or 'export_report.json' in source
    bash = Path(r"C:\Program Files\Git\bin\bash.exe") if os.name == 'nt' else Path('/bin/bash')
    if bash.is_file():
        checked = subprocess.run([str(bash), '-n', str(launcher)], capture_output=True, text=True)
        assert checked.returncode == 0, checked.stderr


def _manifest():
    return {
        "schema": "memsharness.pmut_f1_export_manifest/v0",
        "dataset": "dset3", "field_expression": "acpr.p_t",
        "observation_xyz_m": [0, 0, -1e-5],
        "cases": [{"case_id": "x060_n4", "x_scale": 0.6, "N_w_te1": 4,
                   "N_w_te2": 8, "frequency_Hz": 6e6, "outer_solnum": 284,
                   "inner_solnum": 3, "p_point_real_Pa": 1.5, "p_point_imag_Pa": -0.2,
                   "source_table_sha256": "a" * 64, "source_table_row_1based": 1,
                   "mode_identity": "unverified"}],
    }


def _matlab_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@pytest.mark.skipif(not os.environ.get("PMUT_F1_MATLAB"), reason="MATLAB preflight opt-in; no COMSOL is started")
def test_matlab_preflight_guards_and_actual_hashes_without_comsol(tmp_path):
    """真实 MATLAB 解析/执行前置门禁；有效请求在 mphload 替身处强制停止。"""
    fake_model = tmp_path / "small.mph"
    fake_model.write_bytes(b"inert test fixture - not a COMSOL model")
    good = tmp_path / "manifest.json"
    good.write_text(json.dumps(_manifest()), encoding="utf-8")
    invalid = _manifest()
    invalid["cases"][0]["case_id"] = "../escape"
    bad_id = tmp_path / "bad-id.json"
    bad_id.write_text(json.dumps(invalid), encoding="utf-8")
    invalid = _manifest()
    invalid["cases"][0]["outer_solnum"] = 1.5
    bad_index = tmp_path / "bad-index.json"
    bad_index.write_text(json.dumps(invalid), encoding="utf-8")
    existing = tmp_path / "existing"
    existing.mkdir()
    output = tmp_path / "valid-output"
    changed_model = tmp_path / "changed.mph"
    changed_model.write_bytes(fake_model.read_bytes())
    # 最先命中的路径只包含替身；绝不初始化 COMSOL server 或载入真实模型。
    (tmp_path / "mphload.m").write_text(
        "function model = mphload(varargin)\n"
        "global PMUTF1_TEST_MODE PMUTF1_TEST_MODEL_PATH;\n"
        "if isempty(PMUTF1_TEST_MODE); error('PMUTF1Test:LoadIntercepted','No real COMSOL call permitted.'); end\n"
        "PMUTF1_TEST_MODEL_PATH=varargin{1}; model=FakeStoredModel();\nend\n",
        encoding="utf-8",
    )
    (tmp_path / "FakeStoredModel.m").write_text(
        "classdef FakeStoredModel < handle\n"
        "properties; result; dataset; expr; outer; inner; modified=false; end\n"
        "methods\n"
        "function obj=FakeStoredModel(); obj.result=obj; obj.dataset=obj; end\n"
        "function out=numerical(obj); out=obj; end\n"
        "function out=tags(~); out={'dset3'}; end\n"
        "function create(varargin); end\n"
        "function out=get(obj,varargin); out=obj; end\n"
        "function set(obj,key,value); switch key; case 'expr'; obj.expr=value; case 'outersolnum'; obj.outer=value; case 'solnum'; obj.inner=value; end; end\n"
        "function out=getInt(obj,key); if strcmp(key,'outersolnum'); out=obj.outer; else; out=obj.inner; end; end\n"
        "function out=isComplex(~); out=true; end\n"
        "function out=getData(obj)\n"
        "global PMUTF1_TEST_MODE PMUTF1_TEST_MODEL_PATH;\n"
        "out=[0 1e-6 2e-6; 0 0 0; -2e-5 -2e-5 -2e-5; 2 3 4; 6e6 6e6 6e6; .6 .6 .6; 4 4 4; 8 8 8];\n"
        "if strcmp(obj.expr{4},'dom'); out(4,:)=[1 1 1]; if strcmp(PMUTF1_TEST_MODE,'no_dom'); error('Fake:NoDom','dom unavailable'); end; end\n"
        "if strcmp(PMUTF1_TEST_MODE,'mismatch'); out(6,1)=.61; end\n"
        "if strcmp(PMUTF1_TEST_MODE,'dom_mismatch') && strcmp(obj.expr{4},'dom'); out(5,1)=7e6; end\n"
        "if strcmp(PMUTF1_TEST_MODE,'source_changed') && ~obj.modified; f=fopen(PMUTF1_TEST_MODEL_PATH,'a'); fprintf(f,'changed'); fclose(f); obj.modified=true; end\n"
        "end\n"
        "function out=getImagData(obj); out=zeros(8,3); if ~strcmp(obj.expr{4},'dom'); out(4,:)=[3 4 5]; end; end\n"
        "end\nend\n",
        encoding="utf-8",
    )
    (tmp_path / "mphinterp.m").write_text(
        "function pressure=mphinterp(~,expr,varargin)\n"
        "global PMUTF1_TEST_MODE; options=struct(); for k=1:2:numel(varargin); options.(varargin{k})=varargin{k+1}; end\n"
        "assert(strcmp(expr,'acpr.p_t') && isequal(options.coord,[0;0;-1e-5]));\n"
        "assert(strcmp(options.dataset,'dset3') && options.outersolnum==284 && options.solnum==3 && options.ext==0);\n"
        "assert(strcmp(options.complexout,'on') && strcmp(options.coorderr,'on') && strcmp(options.matherr,'on'));\n"
        "assert(~isfield(options,'t')); pressure=1.5-.2i;\n"
        "if strcmp(PMUTF1_TEST_MODE,'point_mismatch'); pressure=pressure+.01; end\n"
        "if strcmp(PMUTF1_TEST_MODE,'point_nonfinite'); pressure=NaN; end\n"
        "if strcmp(PMUTF1_TEST_MODE,'point_vector'); pressure=[pressure pressure]; end\n"
        "end\n",
        encoding="utf-8",
    )
    common = f"{_matlab_quote(fake_model)}, {_matlab_quote(good)}"
    run = tmp_path / "run_exporter_preflight_checks.m"
    run.write_text(
        "function run_exporter_preflight_checks()\n"
        "global PMUTF1_TEST_MODE; PMUTF1_TEST_MODE='';\n"
        f"addpath({_matlab_quote(SCRIPT.parent)}); addpath({_matlab_quote(tmp_path)}, '-begin');\n"
        f"expect(@() pmut_f1_export_stored({_matlab_quote(tmp_path / 'missing.mph')}, {_matlab_quote(good)}, {_matlab_quote(tmp_path / 'missing-out')}), 'PMUTF1:SourceMissing');\n"
        f"expect(@() pmut_f1_export_stored({common}, {_matlab_quote(tmp_path / 'size-out')}, 1), 'PMUTF1:ModelSizeLimit');\n"
        f"expect(@() pmut_f1_export_stored({common}, {_matlab_quote(existing)}), 'PMUTF1:OutputExists');\n"
        f"expect(@() pmut_f1_export_stored({_matlab_quote(fake_model)}, {_matlab_quote(bad_id)}, {_matlab_quote(tmp_path / 'id-out')}), 'PMUTF1:InvalidManifest');\n"
        f"expect(@() pmut_f1_export_stored({_matlab_quote(fake_model)}, {_matlab_quote(bad_index)}, {_matlab_quote(tmp_path / 'index-out')}), 'PMUTF1:InvalidManifest');\n"
        f"lock={_matlab_quote(str(fake_model) + '.lock')}; f=fopen(lock,'w'); fclose(f);\n"
        f"expect(@() pmut_f1_export_stored({common}, {_matlab_quote(tmp_path / 'lock-out')}), 'PMUTF1:SourceLocked'); delete(lock);\n"
        f"expect(@() pmut_f1_export_stored({common}, {_matlab_quote(output)}), 'PMUTF1Test:LoadIntercepted');\n"
        "PMUTF1_TEST_MODE='success';\n"
        f"r=pmut_f1_export_stored({common}, {_matlab_quote(tmp_path / 'complete')}); assert(strcmp(r.status,'complete') && ~r.training_ready && r.source_unchanged);\n"
        f"s=load({_matlab_quote(tmp_path / 'complete/x060_n4.mat')}); assert(isequal(s.p_total_Pa,[2+3i 3+4i 4+5i])); assert(s.dom_available && isfield(s,'dom')); assert(strcmp(s.point_reference.source_type,'scalar_table_reference_not_field_node') && ~s.point_reference.same_source_model_verified); assert(~s.training_ready && s.point_reference_pressure_consistent && s.p_point_stored_solution_Pa==1.5-.2i);\n"
        "PMUTF1_TEST_MODE='mismatch';\n"
        f"expect(@() pmut_f1_export_stored({common}, {_matlab_quote(tmp_path / 'mismatch')}), 'PMUTF1:SolutionIdentityMismatch');\n"
        "PMUTF1_TEST_MODE='dom_mismatch';\n"
        f"expect(@() pmut_f1_export_stored({common}, {_matlab_quote(tmp_path / 'dom-mismatch')}), 'PMUTF1:SolutionIdentityMismatch');\n"
        "PMUTF1_TEST_MODE='point_mismatch';\n"
        f"expect(@() pmut_f1_export_stored({common}, {_matlab_quote(tmp_path / 'point-mismatch')}), 'PMUTF1:PointPressureMismatch');\n"
        "PMUTF1_TEST_MODE='point_nonfinite';\n"
        f"expect(@() pmut_f1_export_stored({common}, {_matlab_quote(tmp_path / 'point-nonfinite')}), 'PMUTF1:InvalidPointValue');\n"
        "PMUTF1_TEST_MODE='point_vector';\n"
        f"expect(@() pmut_f1_export_stored({common}, {_matlab_quote(tmp_path / 'point-vector')}), 'PMUTF1:InvalidPointValue');\n"
        "PMUTF1_TEST_MODE='no_dom';\n"
        f"r=pmut_f1_export_stored({common}, {_matlab_quote(tmp_path / 'no-dom')}); assert(strcmp(r.status,'complete'));\n"
        f"s=load({_matlab_quote(tmp_path / 'no-dom/x060_n4.mat')}); assert(~s.dom_available && ~isfield(s,'dom'));\n"
        "PMUTF1_TEST_MODE='source_changed';\n"
        f"expect(@() pmut_f1_export_stored({_matlab_quote(changed_model)}, {_matlab_quote(good)}, {_matlab_quote(tmp_path / 'source-changed')}), 'PMUTF1:SourceChanged');\n"
        "disp('PMUTF1_PREFLIGHT_CHECKS_OK');\nend\n"
        "function expect(call, expected)\n"
        "try; call(); catch err; assert(strcmp(err.identifier, expected), '%s: %s',err.identifier,err.message); return; end\n"
        "error('PMUTF1Test:ExpectedFailure', 'Expected %s', expected);\nend\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [os.environ["PMUT_F1_MATLAB"], "-batch",
         f"addpath({_matlab_quote(tmp_path)}); run_exporter_preflight_checks"],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PMUTF1_PREFLIGHT_CHECKS_OK" in result.stdout
    for phase in ('hash_start', 'hash_done', 'load_start', 'load_done', 'case_done', 'final'):
        assert f'PMUTF1 {phase}' in result.stdout
    report = json.loads((output / "export_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["error"]["identifier"] == "PMUTF1Test:LoadIntercepted"
    assert report["source_model_sha256"] == hashlib.sha256(fake_model.read_bytes()).hexdigest()
    assert report["manifest_sha256"] == hashlib.sha256(good.read_bytes()).hexdigest()
    assert report["source_unchanged"] is True
    assert report["training_ready"] is False
    assert report["phase"] == "final" and report["failed_phase"] == "load_start"
    assert not list(output.glob("*.mat"))
    changed_report = json.loads((tmp_path / "source-changed/export_report.json").read_text(encoding="utf-8"))
    assert changed_report["status"] == "failed"
    assert changed_report["source_unchanged"] is False
    assert changed_report["training_ready"] is False
