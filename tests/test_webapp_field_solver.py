"""网页控制台接入单一复声压场求解器的契约测试。"""

from __future__ import annotations

import importlib.util
import json
import threading
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SERVER = REPO / "scripts/webapp_server.py"
PAGE = REPO / "scripts/webapp_page.html"


def _load_server():
    spec = importlib.util.spec_from_file_location("_webapp_field_test", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def srv():
    return _load_server()


@pytest.fixture(scope="module")
def http(srv):
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()
    server.server_close()


def _get(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def test_field_card_is_self_contained_and_bounded(srv):
    card = srv._field_card()
    assert "error" not in card, card
    assert card["field"] == "p_total_Pa"
    assert card["source_type"] == "ai_solver"
    assert card["model_state"] == "draft" and card["human_approved"] is False
    assert {b["branch"]["N_w_te1"] for b in card["branches"]} == {4, 7}
    assert all(b["applicability"]["x_scale"] == [0.33, 0.93] for b in card["branches"])
    assert all(b["validation"]["s_levels"]["S5"] == "inconclusive"
               for b in card["branches"])


def test_field_predict_summary_and_full_payload(srv):
    summary = srv._field_predict({"x": "0.60", "n1": "4", "n2": "8",
                                  "freq": "20000000"})
    assert "error" not in summary and summary["refused"] is False, summary
    assert summary["source_type"] == "ai_solver"
    assert summary["field_name"] == "p_total_Pa"
    assert summary["n_valid_points"] == 1369
    assert summary["field_rel_l2_error_bound"] == pytest.approx(0.015162415488450123)
    assert summary["s_levels"]["S1"] == "passed"
    assert summary["s_levels"]["S5"] == "inconclusive"
    assert len(summary["preview"]["magnitude_Pa"]) == 48
    assert "field_data" not in summary

    full = srv._field_predict({"x": "0.60", "n1": "7", "n2": "8",
                               "freq": "20000000", "full": "1"})
    data = full["field_data"]
    assert data["n_points"] == 1369
    assert len(data["points_xyz_m"]) == len(data["p_real_Pa"]) == len(data["p_imag_Pa"]) == 1369


def test_field_refusal_returns_support_plan_but_no_field(srv):
    result = srv._field_predict({"x": "0.60", "n1": "5", "n2": "8",
                                 "freq": "20000000", "full": "1"})
    assert result["refused"] is True
    assert result["support_plan"]["execution"] == "serial_only"
    assert result["support_plan"]["n_runs"] == 5
    assert "field_data" not in result and "field_summary" not in result


def test_http_routes_and_page_retains_fixed_20mhz_field_solver(http):
    card = _get(http, "/api/field/model")
    pred = _get(http, "/api/field/predict?x=0.6&n1=4&n2=8&freq=20000000")
    assert card["field"] == "p_total_Pa"
    assert pred["source_type"] == "ai_solver" and pred["n_valid_points"] == 1369
    html = PAGE.read_text(encoding="utf-8")
    for required in ('id="p-field"', "复声压场求解器", "/api/field/predict"):
        assert required in html


def test_legacy_missing_model_no_longer_exposes_raw_file_error(srv):
    result = srv._mc_card()
    if result.get("legacy_unavailable"):
        assert result["redirect"] == "field"
        assert "FileNotFoundError" not in result["error"]
        assert "multichannel_model.json" not in result["error"]
