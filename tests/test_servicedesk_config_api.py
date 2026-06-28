"""Tests for the service desk config API endpoints."""
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def sd_client(tmp_path, monkeypatch):
    import api.main as main_module
    monkeypatch.setattr(main_module, "_ENV_PATH", str(tmp_path / ".env"))
    import agent.flow as flow_module
    monkeypatch.setattr(flow_module, "DEFAULT_FLOW_PATH", str(tmp_path / "flow.json"))
    from api.main import app
    return TestClient(app)


def test_put_servicedesk_config_updates_os_environ_and_env_file(sd_client, tmp_path, monkeypatch):
    monkeypatch.delenv("SERVICEDESK_PROVIDER", raising=False)
    monkeypatch.delenv("FRESHDESK_DOMAIN", raising=False)
    monkeypatch.delenv("FRESHDESK_API_KEY", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text("")

    resp = sd_client.put("/servicedesk/config", json={
        "provider": "freshdesk",
        "domain": "acme.freshdesk.com",
        "api_key": "fd-test-key",
    })

    assert resp.status_code == 200
    assert os.environ.get("SERVICEDESK_PROVIDER") == "freshdesk"
    assert os.environ.get("FRESHDESK_DOMAIN") == "acme.freshdesk.com"
    assert os.environ.get("FRESHDESK_API_KEY") == "fd-test-key"
    content = env_file.read_text()
    assert "SERVICEDESK_PROVIDER" in content
    assert "acme.freshdesk.com" in content


def test_get_servicedesk_config_does_not_expose_raw_key(sd_client, monkeypatch):
    monkeypatch.setenv("SERVICEDESK_PROVIDER", "freshdesk")
    monkeypatch.setenv("FRESHDESK_DOMAIN", "acme.freshdesk.com")
    monkeypatch.setenv("FRESHDESK_API_KEY", "fd-super-secret")

    resp = sd_client.get("/servicedesk/config")

    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "freshdesk"
    assert data["domain"] == "acme.freshdesk.com"
    assert data["api_key_set"] is True
    assert "fd-super-secret" not in resp.text
