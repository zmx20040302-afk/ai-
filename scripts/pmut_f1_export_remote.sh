#!/usr/bin/env bash
# Authorized one-shot, stored-solution export. No solve, no MPH save, no cleanup deletion.
# Upload this file, pmut_f1_export_stored.m and manifest21.json to ROOT before running.
# Source MPH and its directory remain read-only. Normal per-user COMSOL auto-login
# configuration is used; never print/copy its content or server.log to a shared log.
set -Eeuo pipefail
umask 077

readonly ROOT=/home/lab/zhangmx/pmut_f1_export_20261016_v1
readonly USER_WORK=/home/lab/zhangmx
readonly SOURCE=/home/lab/projAI4US/autodesign/cell_te2_8_test_scal_0.2-1_0.01_freq5-50_v1.mph
readonly COMSOL=/usr/local/bin/comsol64
readonly MATLAB=/usr/local/bin/matlab
readonly MLI=/opt/software/comsol64/multiphysics/mli
readonly MAX_MODEL_BYTES=322122547200  # Per-run 300 GiB ceiling after resource preflight; default is 8 GiB.
readonly MIN_MEMORY_KIB=125829120    # 120 GiB, evaluated again before server startup.
readonly MIN_DISK_BYTES=21474836480  # 20 GiB free in both output and short-temp filesystems.
readonly WALL_SECONDS=7200
readonly NP=4
readonly EXPECTED_CASES=21

die() { printf 'PMUTF1 launcher_refused %s\n' "$*" >&2; exit 2; }
[[ $# -eq 0 ]] || die 'this fixed-manifest launcher accepts no arguments'
[[ -d "$ROOT" && ! -L "$ROOT" ]] || die 'authorized root must be a real existing directory'
[[ "$(realpath -- "$ROOT")" == "$ROOT" ]] || die 'authorized root resolves elsewhere'
readonly SELF="$(realpath -- "${BASH_SOURCE[0]}")"
[[ "$SELF" == "$ROOT/pmut_f1_export_remote.sh" ]] || die 'launcher must run from its authorized root'
readonly OWNER_UID="$(id -u)"
[[ "$(stat -c %u -- "$ROOT")" == "$OWNER_UID" ]] || die 'authorized root must be owned by the current user'
for command in flock setsid timeout sha256sum stat df awk pgrep ps realpath mktemp /usr/bin/python3; do
    command -v "$command" >/dev/null || die "required tool unavailable: $command"
done
[[ -x "$COMSOL" && -x "$MATLAB" && -d "$MLI" ]] || die 'required COMSOL64/MATLAB/LiveLink installation is missing'

# Advisory lock is deliberately retained. No other instance can share this export root.
exec 9>>"$ROOT/export.lock"
flock -n 9 || die 'another export launcher holds this root lock'
readonly RUN="$(mktemp -d "$ROOT/r.XXXXXX")"
readonly OUTPUT="$ROOT/out21"
readonly MANIFEST="$ROOT/manifest21.json"
readonly EXPORTER="$ROOT/pmut_f1_export_stored.m"
readonly START_EPOCH="$(date +%s)"
server_pid=''
server_start=''
matlab_pid=''
matlab_start=''
short_tmp=''

set_status() { printf '%s\n' "$1" >"$RUN/status.txt"; }
process_start() { awk '{print $22}' "/proc/$1/stat" 2>/dev/null || true; }
stop_owned_group() {
    local pid="$1" expected_start="$2" current_start pgid current_uid
    [[ -n "$pid" && -n "$expected_start" && -r "/proc/$pid/stat" ]] || return 0
    current_start="$(process_start "$pid")"
    pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ' || true)"
    current_uid="$(stat -c %u -- "/proc/$pid" 2>/dev/null || true)"
    # The PID must still be the exact process/group leader this launcher created.
    [[ "$current_start" == "$expected_start" && "$pgid" == "$pid" && "$current_uid" == "$OWNER_UID" ]] || return 0
    kill -TERM -- "-$pid" 2>/dev/null || true
    for attempt in {1..15}; do
        kill -0 -- "-$pid" 2>/dev/null || break
        sleep 1
    done
    if kill -0 -- "-$pid" 2>/dev/null; then
        kill -KILL -- "-$pid" 2>/dev/null || true
    fi
    wait "$pid" 2>/dev/null || true
}
cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM
    stop_owned_group "$matlab_pid" "$matlab_start"
    stop_owned_group "$server_pid" "$server_start"
    printf '%s\n' "$exit_code" >"$RUN/exit_code.txt"
    if [[ "$exit_code" -eq 0 ]]; then
        set_status complete
    else
        set_status "failed_exit_$exit_code"
    fi
    printf 'PMUTF1 launcher_final exit=%s run=%s\n' "$exit_code" "$RUN"
    # All artifacts and short temporary directories are retained for audit/recovery.
    exit "$exit_code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
set_status preflight

[[ -s "$SOURCE" && -f "$SOURCE.status" ]] || die 'source MPH or completion-status file is missing'
grep -q 'Done' "$SOURCE.status" || die 'source MPH is not marked Done'
for lock in "$SOURCE.lock" "${SOURCE%.mph}.lock"; do
    [[ ! -e "$lock" && ! -L "$lock" ]] || die 'source MPH is locked'
done
source_size="$(stat -c %s -- "$SOURCE")"
[[ "$source_size" -gt 0 && "$source_size" -le "$MAX_MODEL_BYTES" ]] || die 'source exceeds 300 GiB size gate'
[[ ! -e "$OUTPUT" && ! -L "$OUTPUT" ]] || die 'out21 already exists; refusing to overwrite or resume it'
[[ -f "$MANIFEST" && ! -L "$MANIFEST" && -f "$EXPORTER" && ! -L "$EXPORTER" ]] || die 'fixed input manifest/exporter missing or symlinked'

# Freeze small input files in this unique run; never copy the large source MPH.
cp -- "$MANIFEST" "$RUN/manifest21.json"
cp -- "$EXPORTER" "$RUN/pmut_f1_export_stored.m"
/usr/bin/python3 - "$RUN/manifest21.json" "$EXPECTED_CASES" <<'PY'
import json, pathlib, re, sys
m = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
assert m['schema'] == 'memsharness.pmut_f1_export_manifest/v0'
assert m['dataset'] == 'dset3' and m['field_expression'] == 'acpr.p_t'
assert m['observation_xyz_m'] == [0, 0, -1e-5]
assert isinstance(m['cases'], list) and len(m['cases']) == int(sys.argv[2])
ids = [c['case_id'] for c in m['cases']]
assert all(isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', v) for v in ids)
assert len({v.lower() for v in ids}) == len(ids)
assert all(c['N_w_te2'] == 8 and c['mode_identity'] == 'unverified' for c in m['cases'])
print('PMUTF1 manifest_preflight cases=21 dataset=dset3')
PY

check_resources() {
    local available_kib root_free user_free
    available_kib="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
    root_free="$(df -B1 --output=avail "$ROOT" | tail -n 1 | tr -d ' ')"
    user_free="$(df -B1 --output=avail "$USER_WORK" | tail -n 1 | tr -d ' ')"
    printf '%s\t%s\t%s\t%s\n' "$(date -Is)" "$available_kib" "$root_free" "$user_free" >>"$RUN/resource_checks.tsv"
    [[ "$available_kib" -ge "$MIN_MEMORY_KIB" ]] || die 'less than 120 GiB MemAvailable'
    [[ "$root_free" -ge "$MIN_DISK_BYTES" && "$user_free" -ge "$MIN_DISK_BYTES" ]] || die 'less than 20 GiB free disk space'
}
check_resources
# Refuse concurrent COMSOL work owned by this account; other users are never signalled.
if pgrep -u "$OWNER_UID" -f '(comsolmphserver|com\.comsol|/comsol64|/multiphysics/.*/comsol)' >"$RUN/own_comsol_pids_before.txt"; then
    die 'this account already has a COMSOL process; serial execution required'
fi

# Short paths are essential: a previous long TMPDIR exceeded Linux IPC socket limits.
short_tmp="$(mktemp -d "$USER_WORK/p1t.XXXXXX")"
[[ "$(realpath -- "$short_tmp")" == "$USER_WORK"/p1t.* ]] || die 'short temporary path is outside scope'
mkdir -- "$short_tmp/c" "$short_tmp/m" "$short_tmp/f"
printf '%s\n' "$short_tmp" >"$RUN/temporary_directory.txt"
export TMPDIR="$short_tmp/m"
export TMP="$TMPDIR"
export TEMP="$TMPDIR"
export MATLAB_PREFDIR="$short_tmp/f"
cd -- "$RUN"
sha256sum -- "$SELF" "$RUN/pmut_f1_export_stored.m" "$RUN/manifest21.json" >"$RUN/input_sha256.txt"
stat -c 'size_bytes=%s mtime=%y source=%n' -- "$SOURCE" >"$RUN/source_stat_before.txt"
printf 'np=%s\nwall_seconds=%s\nmax_model_bytes=%s\ncomsol=%s\nmatlab=%s\n' \
    "$NP" "$WALL_SECONDS" "$MAX_MODEL_BYTES" "$(readlink -f "$COMSOL")" "$(readlink -f "$MATLAB")" >"$RUN/execution_config.txt"
printf 'Auto-login uses this user standard COMSOL configuration. server.log is private; do not display its contents.\n' >>"$RUN/execution_config.txt"
printf 'Source SHA256 is computed from actual bytes by the exporter before mphload; see out21/export_report.json.\n' >>"$RUN/execution_config.txt"
check_resources

set_status starting_private_server
readonly PORTFILE="$RUN/port"
# These options were checked with remote COMSOL 6.4 mphserver -help. No verified
# loopback-bind option exists there: do not invent one or edit shared server.xml.
# Auto authentication is retained; inspect listening address separately without
# exposing the private server log or per-user login configuration.
setsid timeout --signal=TERM --kill-after=15s "${WALL_SECONDS}s" \
    "$COMSOL" -np "$NP" -tmpdir "$short_tmp/c" mphserver \
    -login auto -port 0 -portfile "$PORTFILE" -silent >"$RUN/server.log" 2>&1 &
server_pid=$!
server_start="$(process_start "$server_pid")"
printf '%s\n' "$server_pid" >"$RUN/server_launcher_pid.txt"
for attempt in {1..120}; do
    [[ -s "$PORTFILE" ]] && break
    kill -0 "$server_pid" 2>/dev/null || die 'private server exited before publishing its port'
    sleep 1
done
[[ -s "$PORTFILE" ]] || die 'private server did not publish a port within 120 seconds'
port="$(tr -d '[:space:]' <"$PORTFILE")"
[[ "$port" =~ ^[0-9]+$ && "$port" -ge 1 && "$port" -le 65535 ]] || die 'private server returned an invalid port'
printf 'PMUTF1 server_started port=%s np=%s run=%s\n' "$port" "$NP" "$RUN"
remaining=$((START_EPOCH + WALL_SECONDS - $(date +%s)))
[[ "$remaining" -gt 0 ]] || die 'wall-clock budget exhausted before MATLAB startup'
set_status connecting_and_exporting
# MATLAB first connects to our fresh server and prints connect_done. Connection
# failure raises before the exporter, so no source load follows a failed connection.
batch="fprintf('PMUTF1 connect_start\\n'); addpath('$MLI'); mphstart($port); fprintf('PMUTF1 connect_done matlab=%s comsol=%s\\n',version,char(com.comsol.model.util.ModelUtil.getComsolVersion())); addpath('$RUN'); report=pmut_f1_export_stored('$SOURCE','$RUN/manifest21.json','$OUTPUT',$MAX_MODEL_BYTES); assert(strcmp(report.status,'complete') && report.completed==$EXPECTED_CASES && report.requested==$EXPECTED_CASES && ~report.training_ready);"
setsid timeout --signal=TERM --kill-after=15s "${remaining}s" \
    "$MATLAB" -batch "$batch" >"$RUN/matlab.log" 2>&1 &
matlab_pid=$!
matlab_start="$(process_start "$matlab_pid")"
printf '%s\n' "$matlab_pid" >"$RUN/matlab_launcher_pid.txt"
if wait "$matlab_pid"; then
    matlab_pid=''
else
    result=$?
    printf 'PMUTF1 matlab_failed exit=%s private_log=%s\n' "$result" "$RUN/matlab.log" >&2
    exit "$result"
fi

set_status validating_outputs
/usr/bin/python3 - "$OUTPUT" "$EXPECTED_CASES" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
report = json.loads((root / 'export_report.json').read_text(encoding='utf-8'))
assert report['status'] == 'complete' and report['source_unchanged'] is True
assert report['training_ready'] is False and report['completed'] == report['requested'] == int(sys.argv[2])
assert len(report['cases']) == int(sys.argv[2])
assert len(list(root.glob('*.mat'))) == int(sys.argv[2])
assert all(c['point_reference_pressure_consistent'] is True for c in report['cases'])
print('PMUTF1 outputs_verified cases=21 training_ready=false')
PY
stat -c 'size_bytes=%s mtime=%y source=%n' -- "$SOURCE" >"$RUN/source_stat_after.txt"
cmp -- "$RUN/source_stat_before.txt" "$RUN/source_stat_after.txt" || die 'source stat changed after export'
printf 'PMUTF1 launcher_complete output=%s run=%s\n' "$OUTPUT" "$RUN"
