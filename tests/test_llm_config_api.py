"""Tests for the LLM config API endpoints."""
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def llm_client(tmp_path, monkeypatch):
    import api.main as main_module
    monkeypatch.setattr(main_module, "_ENV_PATH", str(tmp_path / ".env"))
    import agent.flow as flow_module
    monkeypatch.setattr(flow_module, "DEFAULT_FLOW_PATH", str(tmp_path / "flow.json"))
    from api.main import app
    return TestClient(app)


def test_put_llm_config_updates_os_environ_and_env_file(llm_client, tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text("")

    resp = llm_client.put("/llm/config", json={
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key": "sk-test-key",
    })

    assert resp.status_code == 200
    assert os.environ.get("LLM_PROVIDER") == "openai"
    assert os.environ.get("LLM_MODEL") == "gpt-4o-mini"
    assert os.environ.get("OPENAI_API_KEY") == "sk-test-key"
    content = env_file.read_text()
    assert "LLM_PROVIDER" in content
    assert "openai" in content


def test_get_llm_config_does_not_expose_raw_key(llm_client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret")

    resp = llm_client.get("/llm/config")

    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "openai"
    assert data["model"] == "gpt-4o-mini"
    assert data["api_key_set"] is True
    assert "sk-super-secret" not in resp.text
