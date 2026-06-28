"""Tests for GET /flow/status — MCP server reachability endpoint."""
import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

MCP_NAMES = {"knowledge_graph", "code_graph", "oracle", "azure_devops"}


# ---------------------------------------------------------------------------
# Behavior 1: returns 200 with all four MCPs present regardless of offline count
# ---------------------------------------------------------------------------

def test_flow_status_returns_all_four_mcps(monkeypatch):
    # Patch the probe so no real network calls are made
    monkeypatch.setattr("api.main._probe_url", lambda url: False)
    response = client.get("/flow/status")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == MCP_NAMES
    for name in MCP_NAMES:
        assert "url" in body[name]
        assert "reachable" in body[name]


# ---------------------------------------------------------------------------
# Behavior 2: offline server → reachable: false, not a 500
# ---------------------------------------------------------------------------

def test_offline_server_reported_as_not_reachable(monkeypatch):
    monkeypatch.setattr("api.main._probe_url", lambda url: False)
    response = client.get("/flow/status")
    assert response.status_code == 200
    body = response.json()
    for name in MCP_NAMES:
        assert body[name]["reachable"] is False


# ---------------------------------------------------------------------------
# Behavior 3: online server → reachable: true
# ---------------------------------------------------------------------------

def test_online_server_reported_as_reachable(monkeypatch):
    monkeypatch.setattr("api.main._probe_url", lambda url: True)
    response = client.get("/flow/status")
    assert response.status_code == 200
    body = response.json()
    for name in MCP_NAMES:
        assert body[name]["reachable"] is True
