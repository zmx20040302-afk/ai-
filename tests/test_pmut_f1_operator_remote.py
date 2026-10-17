"""只做静态/合成proc检查，不运行启动器、SSH或COMSOL。"""
from __future__ import annotations

import pathlib
import re
import sys
from types import SimpleNamespace

import pytest

SCRIPT = pathlib.Path(__file__).parents[1] / "scripts/pmut_f1_operator_remote.sh"
EXPORTER = SCRIPT.with_name("pmut_f1_export_operator.m")


def test_lf_fixed_paths_and_immutable_source_guards():
    data = SCRIPT.read_bytes()
    assert b"\r\n" not in data and data.startswith(b"#!/usr/bin/env bash\n")
    text = data.decode()
    assert "set -Eeuo pipefail" in text and "umask 077" in text
    assert "readonly ROOT=/home/lab/zhangmx/pmut_operator_intake_20261017_v2\n" in text
    assert "pmut_operator_intake_20261016_v1" not in text
    assert '"$(realpath -- "$ROOT")" == "$ROOT"' in text
    assert '"$(stat -c %u -- "$ROOT")" == "$OWNER_UID"' in text
    assert '"$SOURCE.lock" "${SOURCE%.mph}.lock"' in text
    assert '[[ ! -e "$OUTPUT" && ! -L "$OUTPUT" ]]' in text
    assert 'cmp -- "$RUN/source_before.txt" "$RUN/source_after.txt"' in text
    assert not re.search(r"\b(?:rm|pkill|killall|mphsave)\b", text)


def test_retry_keeps_resource_floor_and_fresh_serial_output():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "readonly MIN_MEMORY_KIB=125829120\n" in text  # 120 GiB，不因当前资源不足降门槛。
    assert "readonly STOP_MEMORY_KIB=33554432\n" in text
    assert "readonly MIN_DISK_BYTES=21474836480\n" in text
    assert "readonly MAX_MODEL_BYTES=322122547200\n" in text
    assert "readonly NP=4\n" in text
    assert 'readonly OUTPUT="$ROOT/out_n2_${N2}"' in text
    assert 'readonly RUN="$(mktemp -d "$ROOT/n${N2}.XXXXXX")"' in text
    assert 'exec 9>>"$ROOT/serial.lock"' in text
    assert text.index("flock -n 9") < text.index('readonly RUN="$(mktemp')
    assert text.index("\ncheck_resources\n") < text.index('set_status starting_private_server')
    assert '[[ "$available" -ge "$MIN_MEMORY_KIB" && "$free" -ge "$MIN_DISK_BYTES" ]]' in text


def test_serial_and_task_owned_cleanup_guards():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "flock -n 9" in text
    assert 'pgrep -u "$OWNER_UID"' in text
    assert 'export PMUT_OPERATOR_RUN="$RUN"' in text
    assert "proc.stat().st_uid != int(uid)" in text
    assert "tail[19] != expected" in text
    assert "marker not in (proc/'environ').read_bytes().split(b'\\0')" in text
    assert "tail[0] in ('Z', 'X')" in text
    assert text.count('verify_owned_group "$pid" "$expected"') >= 4
    assert '[[ "$rc" != 0 ]] || rc=76' in text
    assert "cleanup_not_confirmed" in text
    assert 'then matlab_pid=' not in text


def test_timeout_semantics_do_not_claim_hard_two_hours():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "readonly WALL_SECONDS=7200" in text
    assert "not a hard 7200-second cutoff" in text
    assert 'remaining=$((START_EPOCH + WALL_SECONDS - $(date +%s)))' in text
    assert '"${remaining}s"' in text and "--kill-after=15s" in text
    assert 'if [[ "$(date +%s)" -ge "$((START_EPOCH + WALL_SECONDS))" ]]; then exit 124; fi' in text


def test_manifest_and_output_set_matches_current_exporter():
    text = SCRIPT.read_text(encoding="utf-8")
    exporter = EXPORTER.read_text(encoding="utf-8")
    assert "memsharness.pmut_f1_operator_export_manifest/v0" in text and "memsharness.pmut_f1_operator_export_manifest/v0" in exporter
    assert "m['resolve_solution_indices'] is True" in text
    for name in ("model_definition_context.mat", "solution_map_raw.mat", "resolved_index.json"):
        assert name in text and name in exporter
    assert "r['resolved_index_sha256']" in text
    assert "resolution['raw_solution_map']['sha256']" in text
    assert "r['model_definition_context']['sha256']" in text
    assert "{f.name for f in p.glob('*.mat')} == expected" in text
    assert "len(list(p.glob('*.mat')))" not in text


def test_embedded_python_blocks_compile():
    text = SCRIPT.read_text(encoding="utf-8")
    blocks = re.findall(r"<<'PY'\n(.*?)\nPY", text, flags=re.S)
    assert len(blocks) == 3
    for i, block in enumerate(blocks):
        compile(block, "launcher-python-%d" % i, "exec")


class FakeProc:
    def __init__(self, pid, group="100", state="S", uid=7, start="1234", marker=True):
        self.name, self.uid, self.marker = str(pid), uid, marker
        tail = [state, "1", group] + ["0"] * 16 + [start]
        self.content = "%s (name with spaces) %s" % (pid, " ".join(tail))

    def __truediv__(self, key):
        if key == "stat":
            return SimpleNamespace(read_text=lambda: self.content)
        return SimpleNamespace(read_bytes=lambda: b"PMUT_OPERATOR_RUN=/task/run\0" if self.marker else b"")

    def stat(self):
        return SimpleNamespace(st_uid=self.uid)


@pytest.mark.parametrize("processes,expected", [
    ([FakeProc(100), FakeProc(101)], 0),
    ([FakeProc(101)], 0),
    ([FakeProc(100, state="Z", marker=False), FakeProc(101)], 0),
    ([FakeProc(100, state="Z", marker=False)], 3),
    ([FakeProc(100, uid=8)], 1),
    ([FakeProc(101, marker=False)], 1),
    ([FakeProc(100, start="9999")], 1),
    ([FakeProc(101, group="900")], 3),
    ([], 3),
])
def test_proc_identity_check_with_synthetic_records_only(monkeypatch, processes, expected):
    text = SCRIPT.read_text(encoding="utf-8")
    block = re.findall(r"<<'PY'\n(.*?)\nPY", text, flags=re.S)[0]
    monkeypatch.setattr(pathlib, "Path", lambda path: SimpleNamespace(iterdir=lambda: processes))
    monkeypatch.setattr(sys, "argv", ["-", "100", "1234", "7", "/task/run"])
    with pytest.raises(SystemExit) as err:
        exec(compile(block, "synthetic-proc-only", "exec"), {})
    assert err.value.code == expected
