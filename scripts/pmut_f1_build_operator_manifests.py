"""将冻结选样转换为分支导出清单；只复用保存解，不推算解索引。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PLAN_SHA256 = '749efd9c394f59a90da304911dfbd0c80f09fe98dbda1ad7514e5ce67da7b2c3'
OLD_REPORT_SHA256 = 'fe96e7c7e0842f86229ff16d0fd50af1304996b419fd7db4b8e77149c8e62434'


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def build(plan_path: Path, source_path: Path, old_report_path: Path, output: Path):
    if sha256(plan_path) != PLAN_SHA256:
        raise ValueError('Frozen sparse plan SHA differs')
    if sha256(old_report_path) != OLD_REPORT_SHA256:
        raise ValueError('Accepted N2=8 report SHA differs')
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    hints = json.loads(source_path.read_text(encoding='utf-8'))
    old = json.loads(old_report_path.read_text(encoding='utf-8'))
    if old['status'] != 'complete' or old['source_unchanged'] is not True:
        raise ValueError('N2=8 accepted export must be complete and source unchanged')
    if plan['schema'] != 'memsharness.pmut_f1_sparse_plan/v0' or len(plan['cases']) != 164:
        raise ValueError('Unexpected frozen plan schema/count')
    source_map = {s['N_w_te2']: s for s in hints['sources']}
    table_hashes = {}
    for case in plan['cases']:
        path = Path(case['source_table_path'])
        if path not in table_hashes:
            table_hashes[path] = sha256(path)
        if table_hashes[path] != case['source_table_sha256']:
            raise ValueError('Local scalar table no longer matches frozen evidence')
    manifests = {}
    for n2 in range(5, 10):
        cases = [c for c in plan['cases'] if c['N_w_te2'] == n2]
        source = source_map[n2]
        expected_hash = old['source_model_sha256'] if n2 == 8 else source.get('historical_source_model_sha256')
        manifest = {
            'schema': 'memsharness.pmut_f1_operator_export_manifest/v0',
            'dataset': plan['dataset'], 'field_expression': plan['field_expression'],
            'observation_xyz_m': plan['observation_xyz_m'],
            'resolve_solution_indices': True,
            'frozen_plan_sha256': PLAN_SHA256,
            'source_pending_sha256': sha256(source_path),
            'source_model': source['source_model'],
            'source_type': 'simulation',
            'requested_action': 'read_only_saved_solution_export_no_new_solve',
            'lineage_quarantine': n2 == 9,
            'training_ready': False, 'release_allowed': False,
            'frequency_semantics': 'first_observable_pressure_peak_not_verified_first_mode',
            'operator_exports': {
                'displacement': {
                    'expressions': ['u', 'v', 'w'], 'units': ['m', 'm', 'm'],
                    'source_note': 'Observed identifiers in N2=8 family evidence remote_accepted_expressions.txt; optional availability probe on this source, not verified eigenmode or cross-branch physics identity.',
                },
                'coefficients': [],
            },
            'cases': cases,
        }
        if expected_hash:
            manifest['expected_source_model_sha256'] = expected_hash
        manifests[f'manifest_n2_{n2}.json'] = manifest
    # 所有只读验证完成后才创建新输出；已有目录/证据永不覆盖。
    output.mkdir(parents=True, exist_ok=False)
    files = {}
    for name, manifest in manifests.items():
        path = output / name
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
        files[name] = {'sha256': sha256(path), 'cases': len(manifest['cases'])}
    evidence = {'schema': 'memsharness.pmut_operator_manifests/v0',
                'plan_sha256': PLAN_SHA256, 'accepted_n2_8_report_sha256': OLD_REPORT_SHA256,
                'files': files, 'new_solve': False, 'training_ready': False, 'release_allowed': False}
    with (output/'manifest_index.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(evidence, stream, indent=2)
        stream.write('\n')
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--source-pending', type=Path, required=True)
    parser.add_argument('--accepted-n2-8-report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.plan, args.source_pending, args.accepted_n2_8_report, args.output), indent=2))


if __name__ == '__main__':
    main()
