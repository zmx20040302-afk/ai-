"""算子数据只读导出：静态禁改模型 + 原生 MATLAB 替身，不启动 COMSOL。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/pmut_f1_export_operator.m"


def test_operator_export_is_independent_and_does_not_mutate_physics():
    source = SCRIPT.read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("%"))
    for pattern in (r"\bmphsave\s*\(", r"\.run(?:All)?\s*\(", r"model\.save\s*\(",
                    r"\.param\([^\n]*\.set", r"\.geom\([^\n]*\.set", r"\.mesh\([^\n]*\.set"):
        assert not re.search(pattern, code), pattern
    assert "pmut_f1_export_stored(" not in code
    assert "'smooth', 'none'" in code
    assert "'recover', 'off'" in code
    assert "{'x', 'y', 'z', 'acpr.p_t', 'dom', 'freq', 'x_scale', 'N_w_te1', 'N_w_te2'}" in code
    assert "same_eval_columns_not_nearest_neighbor" in code
    assert "'original_fe_mesh_verified', false" in code
    assert "loaded_model_definition_snapshot_not_per_outer_state" in code
    assert "forced_response_displacement_not_eigenmode" in code
    assert "'physics_inputs_complete', false" in code
    assert "'release_allowed', false" in code
    assert "'training_ready', true" not in code
    assert "mphxmeshinfo(" not in code  # main mesh 不能直接绑定到任意 outer。


def test_index_resolution_and_identity_remain_fail_closed():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "mphsolutioninfo(model, 'dataset', manifest.dataset, 'cellmap', 'on')" in source
    assert "numel(matches) ~= 1" in source
    assert "'PMUTF1:SolutionMapNotUnique'" in source
    assert "resolved_index.json" in source
    assert "any(abs(values - expected(index)) > tolerance(index))" in source
    assert "'ext', 0, 'coorderr', 'on', 'matherr', 'on'" in source
    assert source.index("file_sha256(modelPath)") < source.index("mphload(modelPath")
    assert source.index("'PMUTF1:SourceHashMismatch'") < source.index("mphload(modelPath")
    assert source.index("'solution_map_raw.mat'") < source.index("tags = fieldnames(info)")
    assert "PMUTF1 context_done" in source and "PMUTF1 resolve_start" in source
    assert "assert_source_unchanged(modelPath, before);" in source
    assert "rethrow_identity_error(err)" in source


def _quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _manifest():
    return {
        "schema": "memsharness.pmut_f1_operator_export_manifest/v0",
        "dataset": "dset3", "field_expression": "acpr.p_t",
        "observation_xyz_m": [0, 0, -1e-5], "resolve_solution_indices": True,
        "operator_exports": {
            "displacement": {"expressions": ["u", "v", "w"], "units": ["m"] * 3,
                             "source_note": "Test declarations only; not a real physics audit."},
            "coefficients": [{"name": "density", "expression": "mat1.rho", "unit": "kg/m^3",
                              "semantic_role": "density_probe", "source_note": "Test model declaration."}],
        },
        "cases": [{"case_id": "x060_N14_N28", "x_scale": 0.6, "N_w_te1": 4,
                   "N_w_te2": 8, "frequency_Hz": 6e6, "outer_solnum": None,
                   "inner_solnum": None, "p_point_real_Pa": 1.5, "p_point_imag_Pa": -0.2,
                   "source_table_sha256": "a" * 64, "source_table_row_1based": 1,
                   "mode_identity": "unverified", "training_eligibility": "research_only",
                   "selection": {"splits": {"parameter_holdout": "dev", "branch_holdout": "dev"}}}],
    }


@pytest.mark.skipif(not os.environ.get("PMUT_F1_MATLAB"), reason="Native MATLAB stub tests require PMUT_F1_MATLAB; never COMSOL")
def test_native_matlab_operator_exporter_with_inert_model_and_api_stubs(tmp_path):
    model = tmp_path / "inert.mph"
    model.write_bytes(b"test fixture, not a real COMSOL model")
    good = tmp_path / "manifest.json"
    good.write_text(json.dumps(_manifest()), encoding="utf-8")
    bad = _manifest()
    bad["resolve_solution_indices"] = False
    (tmp_path / "no-resolution.json").write_text(json.dumps(bad), encoding="utf-8")
    bad = _manifest()
    bad["cases"][0]["outer_solnum"] = 285
    (tmp_path / "contradictory-index.json").write_text(json.dumps(bad), encoding="utf-8")
    bad = _manifest()
    bad["operator_exports"]["displacement"]["expressions"][0] = "run('evil')"
    (tmp_path / "bad-expression.json").write_text(json.dumps(bad), encoding="utf-8")
    bare = _manifest()
    bare.pop("operator_exports")
    (tmp_path / "no-probes.json").write_text(json.dumps(bare), encoding="utf-8")
    matching = _manifest()
    matching["expected_source_model_sha256"] = hashlib.sha256(model.read_bytes()).hexdigest().upper()
    (tmp_path / "matched-hash.json").write_text(json.dumps(matching), encoding="utf-8")
    mismatching = _manifest()
    mismatching["expected_source_model_sha256"] = "f" * 64
    (tmp_path / "mismatched-hash.json").write_text(json.dumps(mismatching), encoding="utf-8")
    malformed = _manifest()
    malformed["expected_source_model_sha256"] = "invalid"
    (tmp_path / "invalid-hash.json").write_text(json.dumps(malformed), encoding="utf-8")
    (tmp_path / "mphload.m").write_text(
        "function obj=mphload(path,varargin)\nglobal OP_MODEL_PATH OP_LOAD_COUNT; OP_LOAD_COUNT=OP_LOAD_COUNT+1; OP_MODEL_PATH=path; obj=FakeOperatorModel();\nend\n",
        encoding="utf-8",
    )
    (tmp_path / "mphsolutioninfo.m").write_text(
        "function out=mphsolutioninfo(~,varargin)\n"
        "global OP_MODE; assert(isequal(varargin,{'dataset','dset3','cellmap','on'}));\n"
        "part=struct('dataset','dset3','mapheaders',{{'x_scale','N_w_te1','freq','solnum','outersolnum'}},'map',[.6 4 6e6 3 284]);\n"
        "if strcmp(OP_MODE,'duplicate_map'); part.map=[part.map;part.map]; end\n"
        "if strcmp(OP_MODE,'no_match'); part.map(1,1)=.7; end\n"
        "if strcmp(OP_MODE,'unknown_headers'); part.mapheaders{4}='guessed_inner'; end\n"
        "if strcmp(OP_MODE,'with_n2'); part.mapheaders={'x_scale','N_w_te1','freq','N_w_te2','solnum','outersolnum'}; part.map=[.6 4 6e6 8 3 284]; end\n"
        "out=struct('solutions',{{'sol3'}},'sol3',part);\nend\n", encoding="utf-8",
    )
    (tmp_path / "mphinterp.m").write_text(
        "function p=mphinterp(~,expr,varargin)\n"
        "global OP_MODE; o=struct(); for k=1:2:numel(varargin); o.(varargin{k})=varargin{k+1}; end\n"
        "assert(strcmp(expr,'acpr.p_t') && isequal(o.coord,[0;0;-1e-5]) && o.solnum==3 && o.outersolnum==284 && o.ext==0);\n"
        "assert(strcmp(o.complexout,'on') && ~isfield(o,'t')); p=1.5-.2i; if strcmp(OP_MODE,'point_mismatch'); p=1; end\nend\n",
        encoding="utf-8",
    )
    (tmp_path / "FakeOperatorModel.m").write_text(r"""classdef FakeOperatorModel < handle
properties; result; dataset; expr; outer; inner; modified=false; end
methods
function obj=FakeOperatorModel(); obj.result=obj; obj.dataset=obj; end
function out=numerical(obj); out=obj; end
function out=tags(~); out={'dset3'}; end
function create(varargin); end
function out=get(obj,varargin); out=obj; end
function set(obj,key,value)
switch key; case 'expr'; obj.expr=value; case 'outersolnum'; obj.outer=value; case 'solnum'; obj.inner=value; end
end
function out=getInt(obj,key); global OP_MODE; out=obj.outer; if strcmp(OP_MODE,'bad_index'); out=out+1; end; end
function out=isComplex(~); out=true; end
function out=getData(obj)
global OP_MODE OP_MODEL_PATH;
out=zeros(numel(obj.expr),4);
for k=1:numel(obj.expr)
switch obj.expr{k}
case 'x'; out(k,:)=[0 1e-6 0 0];
case 'y'; out(k,:)=[0 0 1e-6 0];
case 'z'; out(k,:)=[-2e-5 -2e-5 -2e-5 -1e-5];
case 'acpr.p_t'; out(k,:)=[2 3 4 5];
case 'dom'; out(k,:)=[1 1 2 2]; if strcmp(OP_MODE,'no_dom'); out(k,:)=NaN; end
case 'freq'; out(k,:)=6e6;
case 'x_scale'; out(k,:)=.6;
case 'N_w_te1'; out(k,:)=4;
case 'N_w_te2'; out(k,:)=8; if strcmp(OP_MODE,'bad_n2') || (strcmp(OP_MODE,'optional_mismatch') && numel(obj.expr)>9); out(k,1)=9; end
case {'u','v','w'}; out(k,:)=[1 2 3 4]*1e-9; if strcmp(OP_MODE,'no_optional'); error('Fake:UndefinedVariable','Absent optional field'); end
case 'mat1.rho'; out(k,:)=[1000 1000 2000 2000];
otherwise; error('Fake:UnexpectedExpression','Unexpected expression');
end
end
if strcmp(OP_MODE,'source_changed') && ~obj.modified; f=fopen(OP_MODEL_PATH,'a'); fprintf(f,'changed'); fclose(f); obj.modified=true; end
end
function out=getImagData(obj); out=zeros(numel(obj.expr),4); for k=1:numel(obj.expr); if strcmp(obj.expr{k},'acpr.p_t'); out(k,:)=1; end; end; end
function out=getCoordinates(~); global OP_MODE; out=[0 1e-6 0 0;0 0 1e-6 0;-2e-5 -2e-5 -2e-5 -1e-5]; if strcmp(OP_MODE,'bad_mesh'); out(1,1)=1; end; end
function out=getElements(~); out=[0;1;2;3]; end
function out=getVertexElements(~); out=[0 0 0 0]; end
end
end
""", encoding="utf-8")
    def call(name, manifest=good, size=""):
        return f"pmut_f1_export_operator({_quote(model)},{_quote(manifest)},{_quote(tmp_path / name)}{size})"
    script = [
        "function run_operator_checks()", "global OP_MODE OP_LOAD_COUNT; OP_MODE='success'; OP_LOAD_COUNT=0;",
        f"addpath({_quote(SCRIPT.parent)}); addpath({_quote(tmp_path)},'-begin');",
        f"expect(@() {call('size', size=',1')},'PMUTF1:ModelSizeLimit');",
        f"expect(@() {call('no-resolution', tmp_path / 'no-resolution.json')},'PMUTF1:InvalidManifest');",
        f"expect(@() {call('bad-expression', tmp_path / 'bad-expression.json')},'PMUTF1:InvalidManifest');",
        f"expect(@() {call('invalid-hash', tmp_path / 'invalid-hash.json')},'PMUTF1:InvalidManifest');",
        f"expect(@() {call('mismatched-hash', tmp_path / 'mismatched-hash.json')},'PMUTF1:SourceHashMismatch'); assert(OP_LOAD_COUNT==0);",
        f"expect(@() {call('conflict', tmp_path / 'contradictory-index.json')},'PMUTF1:IndexReadbackMismatch');",
        f"r={call('success')}; assert(strcmp(r.status,'complete') && r.source_unchanged && ~r.training_ready && ~r.release_allowed);",
        f"s=load({_quote(tmp_path / 'success/x060_N14_N28.mat')});",
        "assert(isequal(s.p_total_Pa,[2+1i 3+1i 4+1i 5+1i]) && s.dom_available && isequal(s.dom,[1 1 2 2]));",
        "assert(s.evaluation_mesh.available && ~s.evaluation_mesh.original_fe_mesh_verified);",
        "assert(s.displacement.available && strcmp(s.displacement.role,'forced_response_displacement_not_eigenmode'));",
        "assert(s.coefficient_fields{1}.available && ~s.coefficient_fields{1}.material_or_bc_binding_verified);",
        "assert(~s.physics_inputs_complete && ~s.training_ready && ~s.release_allowed && ~s.definition_context_outer_binding_verified);",
        "assert(s.outer_solnum==284 && s.inner_solnum==3 && s.point_reference_pressure_consistent);",
        "assert(strcmp(s.case_manifest.selection.splits.parameter_holdout,'dev'));",
        f"r={call('matched-hash', tmp_path / 'matched-hash.json')}; assert(r.expected_source_hash_verified && strcmp(r.source_hash_verification,'computed_and_expected_hash_matched'));",
        f"r={call('no-probes', tmp_path / 'no-probes.json')}; s=load({_quote(tmp_path / 'no-probes/x060_N14_N28.mat')}); assert(~s.displacement.available && isempty(s.coefficient_fields));",
    ]
    for mode, expected in (("duplicate_map", "SolutionMapNotUnique"), ("no_match", "SolutionMapNotUnique"),
                           ("unknown_headers", "InvalidSolutionMap"), ("bad_n2", "SolutionIdentityMismatch"),
                           ("bad_index", "IndexReadbackMismatch"), ("optional_mismatch", "SolutionIdentityMismatch"),
                           ("point_mismatch", "PointPressureMismatch")):
        script += [f"OP_MODE='{mode}'; expect(@() {call(mode)},'PMUTF1:{expected}');"]
    for mode, assertion in (("no_dom", "~s.dom_available && ~isfield(s,'dom')"),
                             ("no_optional", "~s.displacement.available && s.coefficient_fields{1}.available"),
                             ("bad_mesh", "~s.evaluation_mesh.available"),
                             ("with_n2", "s.solution_identity_verified")):
        script += [f"OP_MODE='{mode}'; r={call(mode)}; assert(strcmp(r.status,'complete'));",
                   f"s=load({_quote(tmp_path / mode / 'x060_N14_N28.mat')}); assert({assertion}); assert(~s.training_ready);"]
    script += ["OP_MODE='source_changed';", f"expect(@() {call('changed')},'PMUTF1:SourceChanged');",
               "disp('OPERATOR_STUB_CHECKS_OK'); end", "function expect(call,id)",
               "try; call(); catch err; assert(strcmp(err.identifier,id),'%s: %s',err.identifier,err.message); return; end",
               "error('Test:ExpectedFailure','Expected %s',id); end"]
    (tmp_path / "run_operator_checks.m").write_text("\n".join(script), encoding="utf-8")
    run = subprocess.run([os.environ["PMUT_F1_MATLAB"], "-batch", f"addpath({_quote(tmp_path)}); run_operator_checks"],
                         cwd=tmp_path, capture_output=True, encoding="utf-8", errors="replace", timeout=180,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert run.returncode == 0, run.stdout + run.stderr
    assert "OPERATOR_STUB_CHECKS_OK" in run.stdout
    report = json.loads((tmp_path / "success/export_report.json").read_text())
    assert report["status"] == "complete" and report["completed"] == report["requested"] == 1
    assert report["source_hash_verification"] == "computed_from_file_bytes"
    assert report["expected_source_hash_verified"] is False
    assert report["manifest_sha256"] == hashlib.sha256(good.read_bytes()).hexdigest()
    resolved = json.loads((tmp_path / "success/resolved_index.json").read_text())
    assert resolved["cases"][0]["matched_values"] == [0.6, 4, 6e6, 3, 284]
    assert resolved["cases"][0]["N_w_te2_in_map"] is False
    assert resolved["source_hash_verified"] is True
    assert resolved["cases"][0]["parameter_frequency_readback_verified"] is True
    assert resolved["cases"][0]["exact_point_pressure_verified"] is True
    assert resolved["cases"][0]["N_w_te2"] == 8
    candidate = json.loads((tmp_path / "success/resolved_index_candidates.json").read_text())
    assert candidate["cases"][0]["parameter_frequency_readback_verified"] is False
    assert not (tmp_path / "bad_n2/resolved_index.json").exists()
    assert (tmp_path / "unknown_headers/solution_map_raw.mat").is_file()
    assert (tmp_path / "duplicate_map/solution_map_raw.mat").is_file()
    assert not (tmp_path / "mismatched-hash/solution_map_raw.mat").exists()
    mismatch_report = json.loads((tmp_path / "mismatched-hash/export_report.json").read_text())
    assert mismatch_report["error"]["identifier"] == "PMUTF1:SourceHashMismatch"
    assert mismatch_report["failed_phase"] == "hash_start"
    assert mismatch_report["expected_source_hash_verified"] is False
    assert resolved["raw_solution_map"]["sha256"] == hashlib.sha256((tmp_path / "success/solution_map_raw.mat").read_bytes()).hexdigest()
    failed = json.loads((tmp_path / "changed/export_report.json").read_text())
    assert failed["status"] == "failed" and failed["source_unchanged"] is False
