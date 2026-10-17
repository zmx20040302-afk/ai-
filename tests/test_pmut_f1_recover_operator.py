"""合成元数据 + 模拟 SSH/SCP；绝不连接远端，也不伪造真实 MAT 科学验收。"""
from __future__ import annotations

import base64
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/pmut_f1_recover_operator.py"
SPEC = importlib.util.spec_from_file_location("pmut_f1_recover_operator_under_test", SCRIPT)
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)
RUN = "n5.Ab12Cd"


def test_recovery_is_fixed_to_authorized_v2_root_in_both_policies():
    assert recovery.REMOTE_ROOT == "/home/lab/zhangmx/pmut_operator_intake_20261017_v2"
    assert 'ROOT = pathlib.Path("' + recovery.REMOTE_ROOT + '")' in recovery.REMOTE_PROBE
    assert "pmut_operator_intake_20261016_v1" not in recovery.REMOTE_PROBE


@pytest.mark.parametrize("n2", range(5, 10))
def test_authorized_branch_identity_range_remains_5_through_9(n2):
    recovery.validate_identity(n2, "n%d.Ab12Cd" % n2)


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def bundle():
    out = recovery.REMOTE_ROOT + "/out_n2_5/"
    run = recovery.REMOTE_ROOT + "/" + RUN + "/"
    cases = [{"case_id": "x030_N11_N25", "N_w_te2": 5}, {"case_id": "x060_N12_N25", "N_w_te2": 5}]
    manifest = {"schema": "memsharness.pmut_f1_operator_export_manifest/v0", "resolve_solution_indices": True,
                "dataset": "dset3", "field_expression": "acpr.p_t", "observation_xyz_m": [0, 0, -1e-5], "cases": cases,
                "test_only_note": "synthetic bytes, not physical evidence"}
    files = {run + "manifest.json": encode(manifest)}
    # 故意不用真 MAT，证明回收器不把字节完整性误宣称为科学验收。
    for name in [c["case_id"] + ".mat" for c in cases] + ["model_definition_context.mat", "solution_map_raw.mat"]:
        files[out + name] = b"SYNTHETIC NOT MAT: " + name.encode()
    resolved = {"schema": "memsharness.pmut_f1_resolved_indices/v0", "dataset": "dset3", "source_hash_verified": True,
                "source_model": recovery.source_path(5), "source_model_sha256": "a" * 64, "expected_source_hash_verified": False,
                "manifest_sha256": sha(files[run + "manifest.json"]), "training_ready": False,
                "raw_solution_map": {"file": out + "solution_map_raw.mat", "sha256": sha(files[out + "solution_map_raw.mat"])},
                "cases": [{**case, "parameter_frequency_readback_verified": True, "exact_point_pressure_verified": True} for case in cases]}
    files[out + "resolved_index.json"] = encode(resolved)
    report = {"schema": "memsharness.pmut_f1_operator_export/v0", "status": "complete", "source_unchanged": True,
              "source_before": {"size_bytes": 123456, "mtime_millis": 123}, "source_after": {"size_bytes": 123456, "mtime_millis": 123},
              "source_model": recovery.source_path(5), "source_model_sha256": "a" * 64,
              "manifest_path": run + "manifest.json", "manifest_sha256": sha(files[run + "manifest.json"]),
              "resolved_index_sha256": sha(files[out + "resolved_index.json"]), "source_hash_verification": "computed_from_file_bytes",
              "expected_source_model_sha256": "", "expected_source_hash_verified": False, "dataset": "dset3", "field_expression": "acpr.p_t",
              "requested": len(cases), "completed": len(cases), "training_ready": False, "release_allowed": False,
              "model_definition_context": {"file": out + "model_definition_context.mat", "sha256": sha(files[out + "model_definition_context.mat"])},
              "cases": [{"case_id": c["case_id"], "file": out + c["case_id"] + ".mat", "sha256": sha(files[out + c["case_id"] + ".mat"])} for c in cases]}
    files[out + "export_report.json"] = encode(report)
    probe = {"schema": "memsharness.pmut_f1_recovery_probe/v0", "status": "complete", "exit_code": "0", "metadata": {}, "artifacts": {}}
    for path, data in files.items():
        name = path.rsplit("/", 1)[-1]
        if name.endswith(".json"):
            probe["metadata"][name] = {"remote_path": path, "size_bytes": len(data), "sha256": sha(data), "base64": base64.b64encode(data).decode()}
        else:
            probe["artifacts"][name] = {"remote_path": path, "size_bytes": len(data)}
    return probe, files


def change_document(probe, name, change):
    record = probe["metadata"][name]
    value = json.loads(base64.b64decode(record["base64"]))
    change(value)
    data = encode(value)
    record.update(size_bytes=len(data), sha256=sha(data), base64=base64.b64encode(data).decode())


class FakeNetwork:
    def __init__(self, probe, files, *, final_probe=None, corrupt=None, fail=None):
        self.probe, self.files, self.final_probe = probe, files, final_probe
        self.corrupt, self.fail = corrupt, fail
        self.calls, self.probe_count = [], 0

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        assert kwargs.get("shell", False) is False
        assert "StrictHostKeyChecking=yes" in command and "BatchMode=yes" in command
        assert "ClearAllForwardings=yes" in command
        if command[0] == "ssh":
            assert command[-2] == recovery.SSH_HOST
            assert command[-1].startswith("/usr/bin/python3 -c ")
            assert json.loads(kwargs["input"]) == {"n2": 5, "run": RUN}
            self.probe_count += 1
            value = self.final_probe if self.final_probe is not None and self.probe_count > 1 else self.probe
            return SimpleNamespace(returncode=0, stdout=encode(value), stderr=b"")
        assert command[0] == "scp" and command[-3] == "--"
        remote, target = command[-2:]
        assert remote.startswith(recovery.SSH_HOST + ":")
        path = remote.split(":", 1)[1]
        assert not any(char in path for char in "*?[];$`\n\r")
        name = path.rsplit("/", 1)[-1]
        assert not Path(target).exists(), "never overwrite even owned prior output"
        with Path(target).open("xb") as stream:
            stream.write(self.files[path] + (b"tampered" if name == self.corrupt else b""))
        return SimpleNamespace(returncode=1 if name == self.fail else 0, stdout=b"", stderr=b"DO_NOT_ECHO_PRIVATE_LOG")


def test_complete_recovery_original_bytes_and_limited_claims(tmp_path):
    probe, files = bundle()
    network = FakeNetwork(probe, files)
    output = tmp_path / "new"
    receipt = recovery.recover(5, RUN, output, runner=network)
    assert receipt["status"] == "complete" and receipt["n_cases"] == 2
    assert len(receipt["downloaded_files"]) == 7
    assert receipt["training_ready"] is False and receipt["release_allowed"] is False
    assert receipt["source_model_rehashed_locally"] is False
    assert not any(receipt["claims"].values())
    assert receipt["scope"] == "file_integrity_only_not_MAT_scientific_validation"
    assert receipt["remote_metadata_stable_after_download"] is True
    assert network.probe_count == 2
    assert {p.name for p in output.iterdir()} == {p.rsplit("/", 1)[-1] for p in files} | {recovery.RECEIPT_NAME}
    for remote, data in files.items():
        assert (output / remote.rsplit("/", 1)[-1]).read_bytes() == data
    assert all(row["hash_verified"] for row in receipt["downloaded_files"])
    forbidden = ("server.log", "matlab.log", ".mph", ".ssh", "resolved_index_candidates")
    assert not any(any(word in command[-2] for word in forbidden) for command in network.calls if command[0] == "scp")


@pytest.mark.parametrize("n2,run", [(4, RUN), (10, RUN), (True, RUN), (5, "n6.Ab12Cd"), (5, "n5.Ab12C"), (5, "n5.Ab12Cd7"),
                                      (5, "../n5.Ab12Cd"), (5, "n5.Ab12C;"), (5, "n5.Ab12Cd\n"), (5, "n5.你好abcd")])
def test_bad_identity_never_calls_network_or_creates_output(tmp_path, n2, run):
    called = []
    with pytest.raises(recovery.RecoveryError):
        recovery.recover(n2, run, tmp_path / "never", runner=lambda *a, **k: called.append(a))
    assert called == [] and not (tmp_path / "never").exists()


def test_existing_output_is_not_touched(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "user.txt").write_bytes(b"owned by user")
    with pytest.raises(recovery.RecoveryError, match="new directory"):
        recovery.recover(5, RUN, existing, runner=lambda *_: pytest.fail("network called"))
    assert [p.name for p in existing.iterdir()] == ["user.txt"]
    assert (existing / "user.txt").read_bytes() == b"owned by user"


@pytest.mark.parametrize("status,exit_code", [("exporting", None), ("complete", "76"), ("failed_exit_1", "1"), ("complete", 0)])
def test_incomplete_run_downloads_nothing_and_leaves_failed_receipt(tmp_path, status, exit_code):
    probe, files = bundle()
    probe.update(status=status, exit_code=exit_code)
    network = FakeNetwork(probe, files)
    output = tmp_path / "failed"
    with pytest.raises(recovery.RecoveryError, match="not complete"):
        recovery.recover(5, RUN, output, runner=network)
    assert all(call[0] == "ssh" for call in network.calls)
    assert {p.name for p in output.iterdir()} == {recovery.RECEIPT_NAME}
    assert json.loads((output / recovery.RECEIPT_NAME).read_text())["status"] == "failed"


@pytest.mark.parametrize("change", [
    lambda r: r.update(status="running"),
    lambda r: r.update(source_unchanged=False),
    lambda r: r["source_after"].update(size_bytes=999),
    lambda r: r.update(source_before={}, source_after={}),
    lambda r: r.update(completed=1),
    lambda r: r.update(completed=True),
    lambda r: r.update(manifest_sha256="b" * 64),
    lambda r: r.update(resolved_index_sha256="b" * 64),
    lambda r: r.update(manifest_path=recovery.REMOTE_ROOT + "/manifest_n2_5.json"),
    lambda r: r.update(source_model=recovery.source_path(6)),
    lambda r: r["cases"].append(r["cases"][0]),
    lambda r: r["cases"][0].update(case_id="../../private"),
    lambda r: r["cases"][0].update(file=recovery.REMOTE_ROOT + "/server.log"),
    lambda r: r["cases"][0].update(sha256="-" * 64),
    lambda r: r["model_definition_context"].update(file="model_definition_context.mat"),
])
def test_invalid_report_stops_before_scp(tmp_path, change):
    probe, files = bundle()
    change_document(probe, "export_report.json", change)
    network = FakeNetwork(probe, files)
    with pytest.raises(recovery.RecoveryError):
        recovery.recover(5, RUN, tmp_path / "failed", runner=network)
    assert len(network.calls) == 1 and network.calls[0][0] == "ssh"


@pytest.mark.parametrize("edit", [
    lambda p: p["metadata"]["manifest.json"].update(base64="!"),
    lambda p: p["metadata"]["manifest.json"].update(size_bytes=0),
    lambda p: p["metadata"]["manifest.json"].update(sha256="b" * 64),
    lambda p: p["metadata"]["manifest.json"].update(remote_path="/private/manifest.json"),
    lambda p: p["artifacts"].update({"private.mat": {"remote_path": "/private.mat", "size_bytes": 1}}),
    lambda p: p["artifacts"].pop("solution_map_raw.mat"),
    lambda p: p["artifacts"]["solution_map_raw.mat"].update(remote_path="/private.mat"),
])
def test_probe_hash_encoding_and_sets_are_checked(edit):
    probe, _ = bundle()
    edit(probe)
    with pytest.raises(recovery.RecoveryError):
        recovery.build_whitelist(probe, 5, RUN)


def test_v1_evidence_cannot_be_downloaded_under_v2_authorization():
    probe, _ = bundle()
    old_root = "/home/lab/zhangmx/pmut_operator_intake_20261016_v1"
    for collection in (probe["metadata"], probe["artifacts"]):
        for entry in collection.values():
            entry["remote_path"] = entry["remote_path"].replace(recovery.REMOTE_ROOT, old_root)
    with pytest.raises(recovery.RecoveryError, match="Unexpected metadata path"):
        recovery.build_whitelist(probe, 5, RUN)


@pytest.mark.parametrize("cid", ["CON", "aux", "com1", "lpt9", "model_definition_context", "solution_map_raw", "x..", "x/y", "x\\y"])
def test_reserved_and_pathlike_case_ids(cid):
    with pytest.raises(recovery.RecoveryError):
        recovery.case_index([{"case_id": cid}], "test")


def test_case_ids_case_insensitive_unique_for_windows():
    with pytest.raises(recovery.RecoveryError, match="duplicate"):
        recovery.case_index([{"case_id": "Test"}, {"case_id": "test"}], "test")


@pytest.mark.parametrize("kind", ["corrupt", "fail"])
def test_transfer_failure_retains_files_no_retry_and_never_echoes_log(tmp_path, kind):
    probe, files = bundle()
    network = FakeNetwork(probe, files, **{kind: "x030_N11_N25.mat"})
    output = tmp_path / "partial"
    with pytest.raises(recovery.RecoveryError):
        recovery.recover(5, RUN, output, runner=network)
    assert (output / "x030_N11_N25.mat").exists()
    receipt_text = (output / recovery.RECEIPT_NAME).read_text()
    assert "DO_NOT_ECHO_PRIVATE_LOG" not in receipt_text
    receipt = json.loads(receipt_text)
    assert receipt["status"] == "failed"
    assert not (output / "x060_N12_N25.mat").exists()
    assert network.probe_count == 1
    if kind == "corrupt":
        assert receipt["downloaded_files"][-1]["hash_verified"] is False
    with pytest.raises(recovery.RecoveryError, match="new directory"):
        recovery.recover(5, RUN, output, runner=lambda *_: pytest.fail("must not retry into partial output"))


def test_remote_changes_after_download_fail_closed(tmp_path):
    probe, files = bundle()
    changed = copy.deepcopy(probe)
    change_document(changed, "export_report.json", lambda r: r.update(extra_note="changed during download"))
    network = FakeNetwork(probe, files, final_probe=changed)
    output = tmp_path / "changed"
    with pytest.raises(recovery.RecoveryError, match="changed during recovery"):
        recovery.recover(5, RUN, output, runner=network)
    assert len(list(output.glob("*.mat"))) == 4
    assert json.loads((output / recovery.RECEIPT_NAME).read_text())["status"] == "failed"


def test_timeout_keeps_failure_evidence_without_command_output(tmp_path):
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 45, output=b"DO_NOT_ECHO_PRIVATE_LOG")
    output = tmp_path / "timeout"
    with pytest.raises(recovery.RecoveryError):
        recovery.recover(5, RUN, output, runner=timeout)
    receipt = (output / recovery.RECEIPT_NAME).read_text()
    assert "TimeoutExpired" in receipt and "DO_NOT_ECHO" not in receipt


@pytest.mark.parametrize("payload", [b'{"a":1,"a":2}', b'{"a":NaN}', b'[]', b'not json'])
def test_ambiguous_or_nonstandard_json_rejected(payload):
    with pytest.raises(recovery.RecoveryError):
        recovery.read_json_bytes(payload, "test")


def test_append_only_receipt_writer(tmp_path):
    path = tmp_path / "receipt.json"
    recovery.write_new_json(path, {"a": 1})
    with pytest.raises(FileExistsError):
        recovery.write_new_json(path, {"a": 2})
    assert json.loads(path.read_text()) == {"a": 1}


def execute_synthetic_probe(tmp_path, monkeypatch, *, status="complete", extra_mat=False):
    """在临时本地目录执行探查体，不调用 ssh/scp；模拟远端有限文件布局。"""
    probe, files = bundle()
    root = tmp_path / "mock_remote"
    (root / RUN).mkdir(parents=True)
    (root / "out_n2_5").mkdir()
    for path, data in files.items():
        target = root / path.removeprefix(recovery.REMOTE_ROOT + "/")
        target.write_bytes(data)
    (root / RUN / "status.txt").write_text(status)
    (root / RUN / "exit_code.txt").write_text("0")
    # 非白名单日志/模型仅作为毒饵，不会读入或回传。
    (root / RUN / "server.log").write_text("PRIVATE_SERVER_LOG_DO_NOT_READ")
    (root / "out_n2_5" / "model.mph").write_text("PRIVATE_MODEL_DO_NOT_READ")
    if extra_mat:
        (root / "out_n2_5" / "unexpected.mat").write_bytes(b"unexpected")
    code = recovery.REMOTE_PROBE.replace('ROOT = pathlib.Path("' + recovery.REMOTE_ROOT + '")', "ROOT = pathlib.Path(" + repr(str(root.resolve())) + ")")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"n2": 5, "run": RUN})))
    # O_NOFOLLOW 是 Linux 接口，本地 Windows 合成测试依赖 resolve 防线。
    monkeypatch.setattr(os, "O_NOFOLLOW", getattr(os, "O_NOFOLLOW", 0), raising=False)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(compile(code, "synthetic-remote-probe", "exec"), {})
    return json.loads(output.getvalue())


def test_remote_probe_reads_only_small_metadata_and_stats_mat(tmp_path, monkeypatch):
    probe = execute_synthetic_probe(tmp_path, monkeypatch)
    assert probe["status"] == "complete" and probe["exit_code"] == "0"
    assert set(probe["metadata"]) == set(recovery.METADATA_NAMES)
    assert len(probe["artifacts"]) == 4
    assert "PRIVATE_" not in json.dumps(probe)


def test_remote_probe_pending_does_not_read_artifacts(tmp_path, monkeypatch):
    probe = execute_synthetic_probe(tmp_path, monkeypatch, status="hash_start", extra_mat=True)
    assert probe["metadata"] == {} and probe["artifacts"] == {} and probe["exit_code"] is None


def test_remote_probe_extra_mat_rejected(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="MAT artifact set"):
        execute_synthetic_probe(tmp_path, monkeypatch, extra_mat=True)
