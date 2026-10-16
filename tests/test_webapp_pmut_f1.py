"""PMUT 一阶闭环在网页控制台中的只读接入测试。"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from memsharness.pmut_f1 import coverage_summary

REPO = Path(__file__).resolve().parents[1]
SERVER = REPO / "scripts/webapp_server.py"
PAGE = REPO / "scripts/webapp_page.html"


def _load_server():
    spec = importlib.util.spec_from_file_location("_webapp_pmut_f1_test", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _get(base: str, path: str):
    try:
        response = urllib.request.urlopen(base + path, timeout=30)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_pmut_f1_functions_are_fail_closed():
    srv = _load_server()
    status = srv._pmut_f1_status()
    assert status["validation_grid"]["n_designs_total"] == 2430
    assert status["validation_grid"]["n_scalar_spectrum_missing"] == 648
    assert status["stored_field_export_submission"]["status"] == "recovered_qc_passed"
    assert status["ready_for_full_loop"] is False
    checked = srv._pmut_f1_check({"x": "0.60", "n1": "4", "n2": "8"})
    assert checked["scalar_spectrum_registered"] is True
    assert checked["first_mode_operator_dataset_ready"] is False
    rejected = srv._pmut_f1_check({"x": "0.60", "n1": "9", "n2": "8"})
    assert "error" in rejected


def test_pmut_f1_http_routes_and_page():
    srv = _load_server()
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = "http://127.0.0.1:%d" % server.server_address[1]
        code, status = _get(base, "/api/pmut/f1/status")
        assert code == 200 and status["observation"]["side"] == "below"
        assert status["stored_field_export_submission"]["n_recovered_cases"] == 21
        assert status["operator_training_status"] == "not_trained"
        code, checked = _get(base, "/api/pmut/f1/check?x=0.6&n1=4&n2=9")
        assert code == 200 and checked["scalar_spectrum_registered"] is False
        code, rejected = _get(base, "/api/pmut/f1/check?x=0.6&n1=9&n2=8")
        assert code == 400 and "error" in rejected
    finally:
        server.shutdown()
        server.server_close()

    html = PAGE.read_text(encoding="utf-8")
    for required in ('id="p-f1"', "/api/pmut/f1/status", "/api/pmut/f1/check", "show('f1')"):
        assert required in html


def _node():
    node = shutil.which("node")
    if not node:
        pytest.skip("未安装 Node，无法实际执行页面渲染测试")
    return node


def _render_status(status):
    """执行页面原函数及转义助手，不只检查 HTML 中有某个字符串。"""
    html = PAGE.read_text(encoding="utf-8")
    renderer = html[html.index("function renderF1Status("):html.index("async function pmutF1Status(")]
    helpers = "\n".join(re.search(r"^const " + name + r"=.*$", html, re.MULTILINE).group(0)
                        for name in ("esc", "pill"))
    script = "const VC={};\n" + helpers + "\n" + renderer + (
        "\nprocess.stdout.write(JSON.stringify(renderF1Status("
        "JSON.parse(require('fs').readFileSync(0,'utf8')))));"
    )
    run = subprocess.run([_node(), "-e", script], input=json.dumps(status, ensure_ascii=False),
                         encoding="utf-8", capture_output=True, timeout=15)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_f1_page_script_compiles_without_running_browser_side_effects():
    script = re.search(r"<script>([\s\S]*?)</script>", PAGE.read_text(encoding="utf-8")).group(1)
    run = subprocess.run([_node(), "-e", "new Function(require('fs').readFileSync(0,'utf8'));"],
                         input=script, encoding="utf-8", capture_output=True, timeout=15)
    assert run.returncode == 0, run.stderr


def test_recovered_qc_page_explains_limited_success_and_remaining_gates():
    status = coverage_summary()
    html = _render_status(status)
    assert "21/21 组复场已回收" in html
    assert "精确观测点复声压一致性验收通过" in html
    assert "审计快照，非远端实时进度" in html
    assert status["stored_field_export_submission"]["qc_report_sha256"] in html
    assert "不等于一阶模态已确认、场预测准确或算子已训练" in html
    assert "域编号仍缺失，需补齐物理输入" in html
    assert "算子预测与最优点搜索尚未就绪" in html
    assert "训练未就绪，工程放行仍为 false" in html
    assert "结果尚待回收验收" not in html


def test_submitted_pending_page_is_not_confused_with_recovered_qc():
    status = coverage_summary()
    status["stored_field_export_submission"].update({
        "status": "submitted_result_pending",
        "status_basis": "submission_record_not_live_remote_polling",
        "recovered_export_qc_passed": False,
        "recovered": False,
    })
    html = _render_status(status)
    assert "结果尚待回收验收" in html
    assert "21/21 组复场已回收" not in html
    assert "工程放行仍为 false" in html


@pytest.mark.parametrize("change", [
    {"status": "future_unknown_status"},
    {"status_basis": "live_remote_poll"},
    {"recovered": False},
    {"recovered_export_qc_passed": False},
    {"recovered_export_qc_passed": "true"},
    {"qc_scope": "first_mode_field_accuracy"},
    {"n_cases": 0, "n_recovered_cases": 0, "n_exact_point_consistency_passed": 0},
    {"n_cases": "21"},
    {"n_recovered_cases": 20},
    {"n_exact_point_consistency_passed": 20},
    {"qc_report_sha256": ""},
    {"export_report_sha256": None},
    {"manifest_sha256": "invalid"},
    {"source_model_sha256": ""},
])
def test_unknown_or_incomplete_export_evidence_is_not_rendered_as_passed(change):
    status = coverage_summary()
    status["stored_field_export_submission"].update(change)
    html = _render_status(status)
    assert "导出状态未知或验收证据不完整" in html
    assert "21/21 组复场已回收" not in html
    assert "工程放行仍为 false" in html


def test_missing_submission_record_is_not_claimed_as_pending_or_completed():
    status = coverage_summary()
    status.pop("stored_field_export_submission")
    html = _render_status(status)
    assert "尚未登记导出结果" in html
    assert "结果尚待回收验收" not in html
    assert "21/21 组复场已回收" not in html
