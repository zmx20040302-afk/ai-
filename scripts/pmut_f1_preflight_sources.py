"""只读盘点既有五个 PMUT 扫描模型，不加载 MPH，不启动求解或导出。"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


# 仅访问已核实的源文件和运行资源；不读登录配置、其他目录或进程命令行。
REMOTE_PROBE = r'''
import json, os, pathlib, subprocess
root = pathlib.Path('/home/lab/projAI4US/autodesign')
records = []
for n2 in range(5, 10):
    path = root / ('cell_te2_%d_test_scal_0.2-1_0.01_freq5-50_v1.mph' % n2)
    item = {'N_w_te2': n2, 'path': str(path), 'exists': path.is_file(), 'is_symlink': path.is_symlink()}
    if item['exists']:
        stat = path.stat()
        item.update(size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns, readable=os.access(path, os.R_OK))
    item['lock_exists'] = any(p.exists() or p.is_symlink() for p in (pathlib.Path(str(path)+'.lock'), path.with_suffix('.lock')))
    status = pathlib.Path(str(path)+'.status')
    item['status_text'] = status.read_text(errors='replace')[:128].strip() if status.is_file() and not status.is_symlink() else None
    item['source_model_sha256'] = None
    item['source_hash_verified_this_preflight'] = False
    records.append(item)
memory = {}
for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
    key, value = line.split(':', 1)
    if key in ('MemAvailable', 'MemTotal'):
        memory[key + '_bytes'] = int(value.strip().split()[0]) * 1024
disk = os.statvfs('/home/lab/zhangmx')
processes = subprocess.run(['ps', '-u', str(os.getuid()), '-o', 'pid=,comm='], capture_output=True, text=True, check=True)
owned = []
for line in processes.stdout.splitlines():
    parts = line.strip().split(maxsplit=1)
    if len(parts) == 2 and any(name in parts[1].lower() for name in ('comsol', 'matlab')):
        owned.append({'pid': int(parts[0]), 'name': parts[1]})
print(json.dumps({'sources': records, 'memory': memory, 'output_disk_free_bytes': disk.f_bavail*disk.f_frsize,
                  'owned_comsol_matlab_process_names': owned, 'resource_values_are_instantaneous': True,
                  'model_loaded': False, 'new_solve': False, 'source_modified': False}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Preflight history is append-only')
    result = subprocess.run(
        ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
         'ubuntu-10-180-7-46', 'python3 -'], input=REMOTE_PROBE,
        text=True, encoding='utf-8', capture_output=True, timeout=45,
    )
    if result.returncode:
        raise RuntimeError('Remote read-only inventory failed; exit=%d' % result.returncode)
    report = json.loads(result.stdout)
    report.update(schema='memsharness.pmut_f1_sources_preflight/v0',
                  observed_at_utc=datetime.now(timezone.utc).isoformat(),
                  scope='read_only_metadata_of_existing_five_saved_scan_models',
                  ssh_alias='ubuntu-10-180-7-46', training_ready=False, release_allowed=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
