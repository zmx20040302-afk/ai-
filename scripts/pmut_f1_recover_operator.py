#!/usr/bin/env python3
"""只读回收已完成的稀疏算子导出；不调用 COMSOL，不续跑，不接受任意远端路径。

只验证传输完整性和报告链；MAT 科学验收另由 pmut_f1_prepare_operator_data.py 完成。
输出目录必须不存在。失败也保留该目录和 receipt，重试必须另选新目录。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone


SSH_HOST = "ubuntu-10-180-7-46"
REMOTE_ROOT = "/home/lab/zhangmx/pmut_operator_intake_20261017_v2"
MAX_METADATA_BYTES = 2 * 1024 * 1024
METADATA_NAMES = ("export_report.json", "resolved_index.json", "manifest.json")
RECEIPT_NAME = "recovery_receipt.json"
SSH_OPTIONS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=yes", "-o", "ClearAllForwardings=yes"]

# 远端仅允许读取固定任务目录下的小元数据；MAT 仅 lstat，不读取模型或日志。
# O_NOFOLLOW + resolve + 前后 fstat 防止符号链接/替换；完整性最终仍由本地 SHA 核验。
REMOTE_PROBE = r'''
import base64, hashlib, json, os, pathlib, re, stat, sys
ROOT = pathlib.Path("/home/lab/zhangmx/pmut_operator_intake_20261017_v2")
MAX = 2 * 1024 * 1024
def directory(p):
    if p.is_symlink() or p.resolve(strict=True) != p or not p.is_dir():
        raise ValueError("unsafe directory")
def read_small(p, limit):
    if p.resolve(strict=True) != p:
        raise ValueError("unsafe metadata path")
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise ValueError("metadata not regular or size outside bound")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        if len(data) != before.st_size or (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("metadata changed during read")
    return data
q = json.load(sys.stdin)
n2, run = q["n2"], q["run"]
if type(n2) is not int or not 5 <= n2 <= 9 or not isinstance(run, str) or not re.fullmatch(r"n%d\.[A-Za-z0-9]{6}" % n2, run):
    raise ValueError("invalid task identity")
directory(ROOT)
run_dir, out = ROOT / run, ROOT / ("out_n2_%d" % n2)
directory(run_dir)
status = read_small(run_dir / "status.txt", 128).decode("ascii").strip()
answer = {"schema": "memsharness.pmut_f1_recovery_probe/v0", "status": status, "exit_code": None, "metadata": {}, "artifacts": {}}
if status == "complete":
    answer["exit_code"] = read_small(run_dir / "exit_code.txt", 32).decode("ascii").strip()
    if answer["exit_code"] == "0":
        directory(out)
        for name in ("export_report.json", "resolved_index.json", "manifest.json"):
            p = (run_dir if name == "manifest.json" else out) / name
            data = read_small(p, MAX)
            answer["metadata"][name] = {"remote_path": str(p), "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "base64": base64.b64encode(data).decode("ascii")}
        report = json.loads(base64.b64decode(answer["metadata"]["export_report.json"]["base64"]))
        cases = report.get("cases")
        if not isinstance(cases, list) or not 1 <= len(cases) <= 64:
            raise ValueError("invalid case list")
        names = ["model_definition_context.mat", "solution_map_raw.mat"]
        for case in cases:
            cid = case.get("case_id")
            if not isinstance(cid, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", cid):
                raise ValueError("unsafe case id")
            names.append(cid + ".mat")
        if len(set(name.lower() for name in names)) != len(names):
            raise ValueError("duplicate or reserved artifact name")
        actual = {p.name for p in out.iterdir() if p.suffix.lower() == ".mat"}
        if actual != set(names):
            raise ValueError("unexpected MAT artifact set")
        for name in names:
            p = out / name
            info = p.lstat()
            if p.resolve(strict=True) != p or not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
                raise ValueError("unsafe or empty artifact")
            answer["artifacts"][name] = {"size_bytes": info.st_size, "remote_path": str(p)}
        if read_small(run_dir / "status.txt", 128).decode("ascii").strip() != "complete" or read_small(run_dir / "exit_code.txt", 32).decode("ascii").strip() != "0":
            raise ValueError("task status changed during probe")
print(json.dumps(answer, separators=(",", ":")))
'''


class RecoveryError(ValueError):
    """拒绝未完成、来源不一致或非白名单的回收请求。"""


def require(condition, message):
    if not condition:
        raise RecoveryError(message)


def digest(value, label):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None, label + " must be lowercase SHA256")
    return value


def integer(value, label, minimum=1):
    require(type(value) in (int, float) and math.isfinite(value) and value == int(value) and value >= minimum, label + " must be an integer")
    return int(value)


def read_json_bytes(data, label):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, label + " contains duplicate JSON keys")
            result[key] = value
        return result
    try:
        result = json.loads(data, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(RecoveryError(label + " contains nonfinite JSON")))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RecoveryError(label + " is not valid JSON") from error
    require(isinstance(result, dict), label + " must be an object")
    return result


def validate_identity(n2, run):
    require(type(n2) is int and 5 <= n2 <= 9, "N2 must be in 5..9")
    require(isinstance(run, str) and re.fullmatch(r"n%d\.[A-Za-z0-9]{6}" % n2, run) is not None, "Run must be nN. followed by exactly six ASCII alphanumerics matching N2")


def source_path(n2):
    return "/home/lab/projAI4US/autodesign/cell_te2_%d_test_scal_0.2-1_0.01_freq5-50_v1.mph" % n2


def case_index(value, label):
    require(isinstance(value, list) and 1 <= len(value) <= 64, label + " must contain 1..64 cases")
    indexed = {}
    for case in value:
        require(isinstance(case, dict), label + " case must be an object")
        cid = case.get("case_id")
        require(isinstance(cid, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", cid) is not None, label + " has unsafe case id")
        require(cid.lower() not in {key.lower() for key in indexed}, label + " has duplicate case id")
        require(cid.lower() not in {"model_definition_context", "solution_map_raw", "con", "prn", "aux", "nul"} and not re.fullmatch(r"(?:com|lpt)[1-9]", cid.lower()), label + " has reserved case id")
        indexed[cid] = case
    return indexed


def build_whitelist(probe, n2, run):
    """从原字节元数据产生固定路径白名单，不把报告路径直接交给 SCP。"""
    validate_identity(n2, run)
    require(probe.get("schema") == "memsharness.pmut_f1_recovery_probe/v0", "Unexpected probe schema")
    require(probe.get("status") == "complete" and probe.get("exit_code") == "0", "Remote task is not complete with exit 0")
    out = PurePosixPath(REMOTE_ROOT) / ("out_n2_%d" % n2)
    run_dir = PurePosixPath(REMOTE_ROOT) / run
    metadata = probe.get("metadata")
    require(isinstance(metadata, dict) and set(metadata) == set(METADATA_NAMES), "Incomplete metadata set")
    documents, entries = {}, []
    for name in METADATA_NAMES:
        item = metadata[name]
        remote_path = str((run_dir if name == "manifest.json" else out) / name)
        require(item.get("remote_path") == remote_path, "Unexpected metadata path")
        encoded = item.get("base64")
        require(isinstance(encoded, str) and len(encoded) <= (MAX_METADATA_BYTES + 2) // 3 * 4, "Metadata exceeds byte bound")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as error:
            raise RecoveryError("Invalid metadata encoding") from error
        require(0 < len(data) <= MAX_METADATA_BYTES and integer(item.get("size_bytes"), "metadata size") == len(data), "Metadata size mismatch")
        expected = digest(item.get("sha256"), name)
        require(hashlib.sha256(data).hexdigest() == expected, "Metadata SHA256 mismatch")
        documents[name] = read_json_bytes(data, name)
        entries.append({"name": name, "remote_path": remote_path, "size_bytes": len(data), "sha256": expected})
    report, resolved, manifest = (documents[name] for name in METADATA_NAMES)
    require(report.get("schema") == "memsharness.pmut_f1_operator_export/v0" and report.get("status") == "complete", "Export report is not complete")
    require(report.get("source_unchanged") is True, "Source change check did not pass")
    before, after = report.get("source_before"), report.get("source_after")
    require(isinstance(before, dict) and isinstance(after, dict) and before == after, "Source stamps differ")
    integer(before.get("size_bytes"), "source size")
    integer(before.get("mtime_millis"), "source mtime", 0)
    require(manifest.get("schema") == "memsharness.pmut_f1_operator_export_manifest/v0" and manifest.get("resolve_solution_indices") is True, "Unexpected export manifest schema or indexing policy")
    require(report.get("manifest_path") == str(run_dir / "manifest.json"), "Report is not tied to this run manifest")
    require(resolved.get("schema") == "memsharness.pmut_f1_resolved_indices/v0" and resolved.get("source_hash_verified") is True, "Resolved index source is unverified")
    require(report.get("source_model") == resolved.get("source_model") == source_path(n2), "Source model identity mismatch")
    model_hash = digest(report.get("source_model_sha256"), "source model")
    require(digest(resolved.get("source_model_sha256"), "resolved source model") == model_hash, "Resolved source hash mismatch")
    manifest_hash = metadata["manifest.json"]["sha256"]
    require(report.get("manifest_sha256") == resolved.get("manifest_sha256") == manifest_hash, "Original manifest hash mismatch")
    require(report.get("resolved_index_sha256") == metadata["resolved_index.json"]["sha256"], "Resolved index hash mismatch")
    require(report.get("dataset") == resolved.get("dataset") == manifest.get("dataset") == "dset3" and report.get("field_expression") == manifest.get("field_expression") == "acpr.p_t", "Export target identity mismatch")
    require(manifest.get("observation_xyz_m") == [0, 0, -1e-5], "Observation identity mismatch")
    expected_source = manifest.get("expected_source_model_sha256")
    if expected_source is not None:
        require(digest(expected_source, "expected source") == model_hash == report.get("expected_source_model_sha256"), "Expected model hash mismatch")
    require(report.get("expected_source_hash_verified") is (expected_source is not None) and resolved.get("expected_source_hash_verified") is (expected_source is not None), "Expected source verification flags mismatch")
    require(report.get("source_hash_verification") == ("computed_and_expected_hash_matched" if expected_source is not None else "computed_from_file_bytes"), "Model byte hash was not computed")
    requested = case_index(manifest.get("cases"), "manifest")
    actual = case_index(report.get("cases"), "report")
    indices = case_index(resolved.get("cases"), "resolved index")
    require(set(requested) == set(actual) == set(indices), "Manifest/report/index case sets differ")
    require(integer(report.get("requested"), "requested") == integer(report.get("completed"), "completed") == len(requested), "Completion counts differ")
    for cid, case in requested.items():
        require(integer(case.get("N_w_te2"), "manifest N2") == n2, "Manifest mixes N2 branches")
        require(integer(indices[cid].get("N_w_te2"), "resolved N2") == n2, "Resolved index mixes N2 branches")
        require(indices[cid].get("parameter_frequency_readback_verified") is True and indices[cid].get("exact_point_pressure_verified") is True, "Final index verification is incomplete")
    artifacts = probe.get("artifacts")
    expected_names = {cid + ".mat" for cid in requested} | {"model_definition_context.mat", "solution_map_raw.mat"}
    require(isinstance(artifacts, dict) and set(artifacts) == expected_names, "Remote MAT file set differs from whitelist")
    records = [(cid + ".mat", actual[cid]) for cid in sorted(actual)]
    records += [("model_definition_context.mat", report.get("model_definition_context", {})), ("solution_map_raw.mat", resolved.get("raw_solution_map", {}))]
    for name, item in records:
        remote_path = str(out / name)
        require(item.get("file") == remote_path and artifacts[name].get("remote_path") == remote_path, "Unexpected artifact path")
        entries.append({"name": name, "remote_path": remote_path, "size_bytes": integer(artifacts[name].get("size_bytes"), "artifact size"), "sha256": digest(item.get("sha256"), name)})
    return entries, {"n_cases": len(requested), "source_model_sha256": model_hash, "manifest_sha256": manifest_hash, "resolved_index_sha256": metadata["resolved_index.json"]["sha256"], "export_report_sha256": metadata["export_report.json"]["sha256"]}


def probe_remote(n2, run, runner):
    command = ["ssh", *SSH_OPTIONS, SSH_HOST, "/usr/bin/python3 -c " + shlex.quote(REMOTE_PROBE)]
    completed = runner(command, input=json.dumps({"n2": n2, "run": run}).encode("ascii"), capture_output=True, timeout=45, check=False)
    # 不把远端 stdout/stderr 异常全文写入证据或终端，防止意外敏感输出。
    require(completed.returncode == 0, "Read-only SSH metadata probe failed (exit %d)" % completed.returncode)
    require(len(completed.stdout) <= 10 * 1024 * 1024, "Probe response exceeds bound")
    return read_json_bytes(completed.stdout, "remote probe")


def file_sha256(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(data)
    return hasher.hexdigest()


def write_new_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def recover(n2, run, output, *, runner=None):
    """runner 可注入模拟 SSH/SCP；正常运行不执行任何远端写操作。"""
    validate_identity(n2, run)
    output = Path(os.path.abspath(output))
    require(not output.exists() and not output.is_symlink(), "Output must be a new directory (no overwrite or resume)")
    require(output.parent.is_dir(), "Output parent must already exist")
    runner = subprocess.run if runner is None else runner
    receipt = {"schema": "memsharness.pmut_f1_operator_recovery/v0", "status": "failed", "started_utc": datetime.now(timezone.utc).isoformat(), "ssh_host": SSH_HOST, "remote_root": REMOTE_ROOT, "n2": n2, "run": run, "output_directory": str(output), "scope": "file_integrity_only_not_MAT_scientific_validation", "training_ready": False, "release_allowed": False, "source_model_rehashed_locally": False, "claims": {"field_prediction_validated": False, "first_mode_identified": False, "cross_model_training_validated": False}, "downloaded_files": []}
    created = False
    try:
        probe = probe_remote(n2, run, runner)
        receipt["observed_status"] = probe.get("status")
        receipt["observed_exit_code"] = probe.get("exit_code")
        whitelist, provenance = build_whitelist(probe, n2, run)
        receipt.update(provenance)
        receipt["whitelist"] = whitelist
        output.mkdir()  # 排他创建；没有通过 preflight 时不下载任何产物。
        created = True
        for entry in whitelist:
            target = output / entry["name"]
            require(not target.exists() and not target.is_symlink(), "Local target unexpectedly exists")
            # 每次一个由固定路径生成的白名单文件；没有递归、shell glob 或任意路径。
            command = ["scp", *SSH_OPTIONS, "--", SSH_HOST + ":" + entry["remote_path"], str(target)]
            completed = runner(command, capture_output=True, timeout=600, check=False)
            require(completed.returncode == 0, "SCP failed for %s (exit %d)" % (entry["name"], completed.returncode))
            require(target.is_file() and not target.is_symlink(), "Downloaded artifact is missing or linked")
            actual_size, actual_hash = target.stat().st_size, file_sha256(target)
            receipt["downloaded_files"].append({**entry, "actual_size_bytes": actual_size, "actual_sha256": actual_hash, "hash_verified": actual_size == entry["size_bytes"] and actual_hash == entry["sha256"]})
            require(actual_size == entry["size_bytes"] and actual_hash == entry["sha256"], "Downloaded artifact hash/size mismatch: " + entry["name"])
        # 不在前后两次小元数据探查之间接受混合产物；失败保留已经下载的全部证据。
        final_entries, final_provenance = build_whitelist(probe_remote(n2, run, runner), n2, run)
        require(final_entries == whitelist and final_provenance == provenance, "Remote metadata/artifact identities changed during recovery")
        require({p.name for p in output.iterdir()} == {entry["name"] for entry in whitelist}, "Unexpected local output file set")
        require(all(not (output / e["name"]).is_symlink() and file_sha256(output / e["name"]) == e["sha256"] for e in whitelist), "Local artifacts changed during recovery")
        receipt["status"] = "complete"
        receipt["remote_metadata_stable_after_download"] = True
    except (RecoveryError, OSError, subprocess.SubprocessError, KeyError, TypeError, AttributeError, KeyboardInterrupt) as error:
        if not created:
            # 已存在目录或并发创建者的目录永不写入；只在本调用拥有的新目录留证。
            if output.exists() or output.is_symlink():
                raise RecoveryError("Output appeared during preflight; no files overwritten") from error
            output.mkdir()
            created = True
        receipt["error_type"] = type(error).__name__
        receipt["error"] = str(error) if isinstance(error, RecoveryError) else "Recovery interrupted or failed; retained partial files for inspection"
        receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
        write_new_json(output / RECEIPT_NAME, receipt)
        raise RecoveryError(receipt["error"] + "; evidence retained in " + str(output)) from error
    receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
    write_new_json(output / RECEIPT_NAME, receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n2", type=int, choices=range(5, 10), required=True)
    parser.add_argument("--run", required=True, help="Exact completed task basename, e.g. n5.ii0H1v")
    parser.add_argument("--output", type=Path, required=True, help="New local directory; failed recovery also reserves this directory")
    args = parser.parse_args(argv)
    try:
        receipt = recover(args.n2, args.run, args.output)
    except RecoveryError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps({"status": receipt["status"], "n_cases": receipt["n_cases"], "files": len(receipt["downloaded_files"]), "receipt": str(args.output.absolute() / RECEIPT_NAME), "training_ready": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
