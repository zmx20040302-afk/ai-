#!/usr/bin/env bash
# Read-only intake of existing saved solutions. One N2 branch at a time.
# Each output directory is exclusive: a failed run is never silently retried.
set -Eeuo pipefail
umask 077
readonly ROOT=/home/lab/zhangmx/pmut_operator_intake_20261017_v2
readonly USER_WORK=/home/lab/zhangmx
readonly COMSOL=/usr/local/bin/comsol64
readonly MATLAB=/usr/local/bin/matlab
readonly MLI=/opt/software/comsol64/multiphysics/mli
readonly MAX_MODEL_BYTES=322122547200
readonly MIN_MEMORY_KIB=125829120
readonly STOP_MEMORY_KIB=33554432
readonly MIN_DISK_BYTES=21474836480
readonly WALL_SECONDS=7200
# 7200 seconds is the work budget; TERM cleanup waits up to 15 seconds per
# owned group, plus short identity/exit checks (not a hard 7200-second cutoff).
readonly NP=4
die() { printf 'PMUTOP refused %s\n' "$*" >&2; exit 2; }
[[ $# -eq 1 && "$1" =~ ^[5-9]$ ]] || die 'one explicit N2 in 5..9 is required'
readonly N2="$1"
[[ -d "$ROOT" && ! -L "$ROOT" && "$(realpath -- "$ROOT")" == "$ROOT" ]] || die 'unsafe task root'
readonly OWNER_UID="$(id -u)"
[[ "$(stat -c %u -- "$ROOT")" == "$OWNER_UID" ]] || die 'task root ownership differs'
readonly SELF="$(realpath -- "${BASH_SOURCE[0]}")"
[[ "$SELF" == "$ROOT/pmut_f1_operator_remote.sh" ]] || die 'launcher outside fixed task root'
readonly SOURCE="/home/lab/projAI4US/autodesign/cell_te2_${N2}_test_scal_0.2-1_0.01_freq5-50_v1.mph"
readonly MANIFEST="$ROOT/manifest_n2_${N2}.json"
readonly EXPORTER="$ROOT/pmut_f1_export_operator.m"
readonly OUTPUT="$ROOT/out_n2_${N2}"
exec 9>>"$ROOT/serial.lock"
flock -n 9 || die 'another branch holds the serial intake lock'
readonly RUN="$(mktemp -d "$ROOT/n${N2}.XXXXXX")"
readonly START_EPOCH="$(date +%s)"
export PMUT_OPERATOR_RUN="$RUN"
server_pid=''; server_start=''; matlab_pid=''; matlab_start=''
process_start() { awk '{print $22}' "/proc/$1/stat" 2>/dev/null || true; }
set_status() { printf '%s\n' "$1" >"$RUN/status.txt"; }
verify_owned_group() {
    local pid="$1" expected="$2"
    # The setsid/timeout leader may already have exited. Check every remaining
    # group member's UID and unique task marker; never kill by account/name.
    /usr/bin/python3 - "$pid" "$expected" "$OWNER_UID" "$RUN" <<'PY'
import pathlib, sys
group, expected, uid, run = sys.argv[1:]
marker = ('PMUT_OPERATOR_RUN=' + run).encode()
found = False
for proc in pathlib.Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    try:
        tail = (proc/'stat').read_text().rsplit(')', 1)[1].split()
        if tail[2] != group:
            continue
        # Zombies have empty environ and cannot be signalled into exiting.
        # Ignore them without losing ownership checks on live descendants.
        if tail[0] in ('Z', 'X'):
            continue
        if proc.stat().st_uid != int(uid):
            raise SystemExit(1)
        if proc.name == group and tail[19] != expected:
            raise SystemExit(1)
        if marker not in (proc/'environ').read_bytes().split(b'\0'):
            raise SystemExit(1)
        found = True
    except FileNotFoundError:
        continue
    except PermissionError:
        raise SystemExit(1)
raise SystemExit(0 if found else 3)
PY
}
stop_owned_group() {
    local pid="$1" expected="$2" check_rc
    [[ -n "$pid" ]] || return 0
    if verify_owned_group "$pid" "$expected"; then :; else
        check_rc=$?
        [[ "$check_rc" == 3 ]] && { wait "$pid" 2>/dev/null || true; return 0; }
        printf 'PMUTOP cleanup_refused_identity pgid=%s\n' "$pid" >&2
        return 1
    fi
    kill -TERM -- "-$pid" 2>/dev/null || true
    for attempt in {1..15}; do
        if verify_owned_group "$pid" "$expected"; then :; else
            check_rc=$?
            [[ "$check_rc" == 3 ]] && { wait "$pid" 2>/dev/null || true; return 0; }
            printf 'PMUTOP cleanup_refused_identity pgid=%s\n' "$pid" >&2
            return 1
        fi
        sleep 1
    done
    # Recheck immediately before escalation: never trust a stale group scan.
    if verify_owned_group "$pid" "$expected"; then
        kill -KILL -- "-$pid" 2>/dev/null || true
        sleep 0.1
    else
        check_rc=$?
        [[ "$check_rc" == 3 ]] && { wait "$pid" 2>/dev/null || true; return 0; }
        printf 'PMUTOP cleanup_refused_identity pgid=%s\n' "$pid" >&2
        return 1
    fi
    wait "$pid" 2>/dev/null || true
    if verify_owned_group "$pid" "$expected"; then
        printf 'PMUTOP cleanup_still_alive pgid=%s\n' "$pid" >&2
        return 1
    else
        check_rc=$?
        [[ "$check_rc" == 3 ]] || return 1
    fi
}
cleanup() {
    local rc=$? cleanup_failed=0
    trap - EXIT INT TERM
    stop_owned_group "$matlab_pid" "$matlab_start" || cleanup_failed=1
    stop_owned_group "$server_pid" "$server_start" || cleanup_failed=1
    if [[ "$cleanup_failed" == 1 ]]; then
        printf 'PMUTOP cleanup_not_confirmed\n' >&2
        [[ "$rc" != 0 ]] || rc=76
    fi
    printf '%s\n' "$rc" >"$RUN/exit_code.txt"
    if [[ "$rc" == 0 ]]; then set_status complete; else set_status "failed_exit_$rc"; fi
    printf 'PMUTOP launcher_final n2=%s exit=%s run=%s\n' "$N2" "$rc" "$RUN"
    # Retain all evidence, logs and task-owned temporary directories.
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
set_status preflight
[[ -s "$SOURCE" && ! -L "$SOURCE" && -f "$SOURCE.status" ]] || die 'missing or linked source'
grep -q 'Done' "$SOURCE.status" || die 'source is not marked Done'
for lock in "$SOURCE.lock" "${SOURCE%.mph}.lock"; do
    [[ ! -e "$lock" && ! -L "$lock" ]] || die 'source is locked'
done
[[ "$(stat -c %s -- "$SOURCE")" -le "$MAX_MODEL_BYTES" ]] || die 'source exceeds 300 GiB ceiling'
[[ ! -e "$OUTPUT" && ! -L "$OUTPUT" ]] || die 'output exists; no automatic rerun'
[[ -f "$MANIFEST" && ! -L "$MANIFEST" && -f "$EXPORTER" && ! -L "$EXPORTER" ]] || die 'missing fixed inputs'
cp -- "$MANIFEST" "$RUN/manifest.json"
cp -- "$EXPORTER" "$RUN/pmut_f1_export_operator.m"
/usr/bin/python3 - "$RUN/manifest.json" "$N2" <<'PY'
import json, pathlib, re, sys
m = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert m['schema'] == 'memsharness.pmut_f1_operator_export_manifest/v0'
assert m['resolve_solution_indices'] is True and m['field_expression'] == 'acpr.p_t'
assert m['observation_xyz_m'] == [0,0,-1e-5]
assert re.fullmatch('[A-Za-z][A-Za-z0-9_]*', m['dataset'])
assert 1 <= len(m['cases']) <= 64
assert all(c['N_w_te2'] == int(sys.argv[2]) for c in m['cases'])
ids = [c['case_id'] for c in m['cases']]
assert len(set(v.lower() for v in ids)) == len(ids)
assert all(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,79}', v) for v in ids)
print('PMUTOP manifest_valid n2=%s cases=%d' % (sys.argv[2], len(ids)))
PY
check_resources() {
    local available free
    available="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
    free="$(df -B1 --output=avail "$ROOT" | tail -n 1 | tr -d ' ')"
    printf '%s\t%s\t%s\n' "$(date -Is)" "$available" "$free" >>"$RUN/resources.tsv"
    [[ "$available" -ge "$MIN_MEMORY_KIB" && "$free" -ge "$MIN_DISK_BYTES" ]] || die 'insufficient resource headroom'
}
check_resources
if pgrep -u "$OWNER_UID" -f '(comsolmphserver|com\.comsol|/comsol64|/multiphysics/.*/comsol)' >"$RUN/own_comsol_before.txt"; then
    die 'another COMSOL instance owned by this account; serial only'
fi
if pgrep -u "$OWNER_UID" -x MATLAB >"$RUN/own_matlab_before.txt"; then die 'MATLAB already active for this account'; fi
short_tmp="$(mktemp -d "$USER_WORK/pot.XXXXXX")"
[[ "$(realpath -- "$short_tmp")" == "$USER_WORK"/pot.* ]] || die 'unsafe task temporary path'
mkdir -- "$short_tmp/c" "$short_tmp/m" "$short_tmp/f"
export TMPDIR="$short_tmp/m" TMP="$short_tmp/m" TEMP="$short_tmp/m" MATLAB_PREFDIR="$short_tmp/f"
printf '%s\n' "$short_tmp" >"$RUN/temporary_directory.txt"
sha256sum -- "$SELF" "$RUN/pmut_f1_export_operator.m" "$RUN/manifest.json" >"$RUN/input_sha256.txt"
stat -c 'size=%s mtime=%y source=%n' -- "$SOURCE" >"$RUN/source_before.txt"
cd -- "$RUN"
set_status starting_private_server
readonly PORTFILE="$RUN/port"
setsid timeout --signal=TERM --kill-after=15s "${WALL_SECONDS}s" \
    "$COMSOL" -np "$NP" -tmpdir "$short_tmp/c" mphserver \
    -login auto -port 0 -portfile "$PORTFILE" -silent >"$RUN/server.log" 2>&1 &
server_pid=$!; server_start="$(process_start "$server_pid")"
for attempt in {1..120}; do
    [[ -s "$PORTFILE" ]] && break
    kill -0 "$server_pid" 2>/dev/null || die 'private server stopped before publishing port'
    sleep 1
done
[[ -s "$PORTFILE" ]] || die 'private server startup timed out'
port="$(tr -d '[:space:]' <"$PORTFILE")"
[[ "$port" =~ ^[0-9]+$ && "$port" -ge 1 && "$port" -le 65535 ]] || die 'invalid private server port'
check_resources
remaining=$((START_EPOCH + WALL_SECONDS - $(date +%s)))
[[ "$remaining" -gt 0 ]] || die 'wall clock limit reached'
set_status exporting
batch="addpath('$MLI'); mphstart($port); addpath('$RUN'); r=pmut_f1_export_operator('$SOURCE','$RUN/manifest.json','$OUTPUT',$MAX_MODEL_BYTES); assert(strcmp(r.status,'complete') && r.completed==r.requested && ~r.training_ready);"
setsid timeout --signal=TERM --kill-after=15s "${remaining}s" \
    "$MATLAB" -batch "$batch" >"$RUN/matlab.log" 2>&1 &
matlab_pid=$!; matlab_start="$(process_start "$matlab_pid")"
printf 'PMUTOP launched n2=%s np=%s run=%s output=%s\n' "$N2" "$NP" "$RUN" "$OUTPUT"
while kill -0 "$matlab_pid" 2>/dev/null; do
    if [[ "$(date +%s)" -ge "$((START_EPOCH + WALL_SECONDS))" ]]; then exit 124; fi
    available="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
    printf '%s\t%s\n' "$(date -Is)" "$available" >>"$RUN/memory_watch.tsv"
    if [[ "$available" -lt "$STOP_MEMORY_KIB" ]]; then
        printf 'PMUTOP resource_stop available_kib=%s\n' "$available" >&2
        exit 75
    fi
    sleep 10
done
if wait "$matlab_pid"; then :; else rc=$?; exit "$rc"; fi
/usr/bin/python3 - "$OUTPUT" <<'PY'
import hashlib, json, pathlib, sys
p = pathlib.Path(sys.argv[1]); r = json.loads((p/'export_report.json').read_text())
assert r['status']=='complete' and r['source_unchanged'] is True
assert r['requested']==r['completed']==len(r['cases'])
assert r['training_ready'] is False
assert all(c['point_reference_pressure_consistent'] is True for c in r['cases'])
expected = {c['case_id'] + '.mat' for c in r['cases']}
expected.add('model_definition_context.mat')
expected.add('solution_map_raw.mat')
assert {f.name for f in p.glob('*.mat')} == expected
for c in r['cases']:
    f = p / (c['case_id'] + '.mat')
    assert not f.is_symlink() and hashlib.sha256(f.read_bytes()).hexdigest() == c['sha256']
context = p / 'model_definition_context.mat'
assert not context.is_symlink()
assert hashlib.sha256(context.read_bytes()).hexdigest() == r['model_definition_context']['sha256']
index = p / 'resolved_index.json'
assert not index.is_symlink()
assert hashlib.sha256(index.read_bytes()).hexdigest() == r['resolved_index_sha256']
resolution = json.loads(index.read_text())
assert resolution['source_model_sha256'] == r['source_model_sha256']
assert resolution['manifest_sha256'] == r['manifest_sha256']
assert all(c['parameter_frequency_readback_verified'] is True and c['exact_point_pressure_verified'] is True for c in resolution['cases'])
raw_map = p / 'solution_map_raw.mat'
assert not raw_map.is_symlink()
assert hashlib.sha256(raw_map.read_bytes()).hexdigest() == resolution['raw_solution_map']['sha256']
print('PMUTOP outputs_complete cases=%d' % r['completed'])
PY
stat -c 'size=%s mtime=%y source=%n' -- "$SOURCE" >"$RUN/source_after.txt"
cmp -- "$RUN/source_before.txt" "$RUN/source_after.txt" || die 'source stat changed'
