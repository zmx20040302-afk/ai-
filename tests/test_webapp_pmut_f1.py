"""PMUT 一阶闭环在网页控制台中的只读接入测试。"""

from __future__ import annotations

import importlib.util
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path


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
