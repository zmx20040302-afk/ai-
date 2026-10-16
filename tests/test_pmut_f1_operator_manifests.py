"""冻结清单组装只读来源核验和不可覆盖契约。"""
import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('operator_manifests', Path(__file__).parents[1] / 'scripts/pmut_f1_build_operator_manifests.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    table = tmp_path/'Table.mat'
    table.write_bytes(b'fixture: not physical data')
    plan = tmp_path/'plan.json'
    plan.write_text(json.dumps({
        'schema': 'memsharness.pmut_f1_sparse_plan/v0',
        'dataset': 'dset3', 'field_expression': 'acpr.p_t', 'observation_xyz_m': [0, 0, -1e-5],
        'cases': [{'case_id': f'fixture{i}', 'N_w_te2': 5+i % 5,
                   'source_table_path': str(table), 'source_table_sha256': m.sha256(table),
                   'outer_solnum': None, 'inner_solnum': None} for i in range(164)],
    }), encoding='utf-8')
    hints = tmp_path/'source_pending.json'
    hints.write_text(json.dumps({'sources': [
        {'N_w_te2': n2, 'source_model': f'/fixture/n2_{n2}.mph',
         'historical_source_model_sha256': 'a'*64 if n2 < 8 else None} for n2 in range(5, 10)]}), encoding='utf-8')
    report = tmp_path/'accepted.json'
    report.write_text(json.dumps({'status': 'complete', 'source_unchanged': True, 'source_model_sha256': 'b'*64}), encoding='utf-8')
    monkeypatch.setattr(m, 'PLAN_SHA256', m.sha256(plan))
    monkeypatch.setattr(m, 'OLD_REPORT_SHA256', m.sha256(report))
    return plan, hints, report, tmp_path/'new-manifests', table


def test_build_frozen_and_quarantined(inputs):
    plan, hints, report, out, _ = inputs
    result = m.build(plan, hints, report, out)
    assert sum(v['cases'] for v in result['files'].values()) == 164
    n8 = json.loads((out/'manifest_n2_8.json').read_text())
    n9 = json.loads((out/'manifest_n2_9.json').read_text())
    assert n8['expected_source_model_sha256'] == 'b'*64
    assert 'expected_source_model_sha256' not in n9
    assert n9['lineage_quarantine'] is True
    assert n9['resolve_solution_indices'] is True
    assert n9['training_ready'] is False and n9['release_allowed'] is False
    assert all(c['outer_solnum'] is None for c in n9['cases'])


@pytest.mark.parametrize('index', [0, 2, 4])
def test_changed_evidence_refused_before_output(inputs, index):
    inputs[index].write_bytes(b'changed evidence')
    with pytest.raises(ValueError):
        m.build(*inputs[:4])
    assert not inputs[3].exists()


def test_never_overwrite_evidence(inputs):
    m.build(*inputs[:4])
    old = (inputs[3]/'manifest_index.json').read_bytes()
    with pytest.raises(FileExistsError):
        m.build(*inputs[:4])
    assert (inputs[3]/'manifest_index.json').read_bytes() == old
