import json
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def ticket_fixture(tmp_path):
    """Write a mock_tickets.json fixture and return its path."""
    data = [
        {
            "id": "T001",
            "title": "Login fails with SSO",
            "description": "Cannot log in via SSO after password reset.",
            "status": "closed",
            "resolution_notes": "SSO token cache invalidated on reset. Fixed in v2.3.1.",
            "source_system": "mock",
        },
        {
            "id": "T002",
            "title": "Export button not working",
            "description": "The export button does nothing when clicked.",
            "status": "closed",
            "resolution_notes": "Race condition in async export handler. Patched.",
            "source_system": "mock",
        },
        {
            "id": "T003",
            "title": "Slow page load",
            "description": "Pages take a long time.",
            "status": "closed",
            "resolution_notes": None,
            "source_system": "mock",
        },
    ]
    fixture_path = tmp_path / "mock_tickets.json"
    fixture_path.write_text(json.dumps(data))
    return str(fixture_path)


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    """FastAPI TestClient with flow file redirected to tmp_path."""
    import agent.flow as flow_module
    monkeypatch.setattr(flow_module, "DEFAULT_FLOW_PATH", str(tmp_path / "flow.json"))
    from api.main import app
    return TestClient(app)
