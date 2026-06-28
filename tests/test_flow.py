import json
import pytest
from pydantic import ValidationError

from agent.flow import load_flow, save_flow, InvestigationFlow


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_flow(tmp_path, data: dict) -> str:
    p = tmp_path / "flow.json"
    p.write_text(json.dumps(data))
    return str(p)


VALID_FLOW = {
    "entry_node_id": "n1",
    "nodes": [
        {"id": "n1", "type": "tool", "config": {"mcp": "knowledge_graph", "label": "Search docs"}, "edges": [
            {"target_node_id": "n2", "condition": "always"}
        ]},
        {"id": "n2", "type": "conclude", "config": None, "edges": []},
    ],
}


# ---------------------------------------------------------------------------
# Behavior 1: valid flow loads correctly
# ---------------------------------------------------------------------------

def test_valid_flow_loads(tmp_path):
    path = _write_flow(tmp_path, VALID_FLOW)
    flow = load_flow(path)
    assert flow.entry_node_id == "n1"
    assert len(flow.nodes) == 2
    assert flow.nodes[0].id == "n1"
    assert flow.nodes[0].type == "tool"
    assert flow.nodes[0].config.mcp == "knowledge_graph"


# ---------------------------------------------------------------------------
# Behavior 2: round-trip save → load is lossless
# ---------------------------------------------------------------------------

def test_round_trip_save_load(tmp_path):
    path = _write_flow(tmp_path, VALID_FLOW)
    original = load_flow(path)
    out_path = str(tmp_path / "out.json")
    save_flow(original, out_path)
    reloaded = load_flow(out_path)
    assert reloaded.model_dump() == original.model_dump()


# ---------------------------------------------------------------------------
# Behavior 3: flow with no Conclude node is rejected
# ---------------------------------------------------------------------------

def test_no_conclude_node_raises(tmp_path):
    data = {
        "entry_node_id": "n1",
        "nodes": [
            {"id": "n1", "type": "tool", "config": {"mcp": "oracle", "label": "Query DB"}, "edges": [
                {"target_node_id": "n2", "condition": "always"}
            ]},
            {"id": "n2", "type": "branch", "config": None, "edges": []},
        ],
    }
    path = _write_flow(tmp_path, data)
    with pytest.raises((ValidationError, ValueError), match="(?i)conclude"):
        load_flow(path)


# ---------------------------------------------------------------------------
# Behavior 4: reachable non-Conclude node with no edges is rejected
# ---------------------------------------------------------------------------

def test_dead_end_path_raises(tmp_path):
    data = {
        "entry_node_id": "n1",
        "nodes": [
            {"id": "n1", "type": "tool", "config": {"mcp": "oracle", "label": "Query DB"}, "edges": [
                {"target_node_id": "n2", "condition": "always"}
            ]},
            # n2 is a tool node with no edges — dead end before Conclude
            {"id": "n2", "type": "tool", "config": {"mcp": "code_graph", "label": "Search code"}, "edges": []},
            {"id": "n3", "type": "conclude", "config": None, "edges": []},
        ],
    }
    path = _write_flow(tmp_path, data)
    with pytest.raises((ValidationError, ValueError), match="(?i)dead end"):
        load_flow(path)


# ---------------------------------------------------------------------------
# Behavior 5: GET /flow returns 200 + a default flow when file is absent
# ---------------------------------------------------------------------------

def test_get_flow_returns_default_when_no_file(api_client):
    response = api_client.get("/flow")
    assert response.status_code == 200
    body = response.json()
    assert "nodes" in body
    assert "entry_node_id" in body


# ---------------------------------------------------------------------------
# Behavior 6: PUT /flow valid body → 200 and persisted to disk
# ---------------------------------------------------------------------------

def test_put_flow_valid_persists(api_client, tmp_path, monkeypatch):
    import agent.flow as flow_module
    monkeypatch.setattr(flow_module, "DEFAULT_FLOW_PATH", str(tmp_path / "flow.json"))
    response = api_client.put("/flow", json=VALID_FLOW)
    assert response.status_code == 200
    # confirm it was written — a subsequent GET should return the saved flow
    get_resp = api_client.get("/flow")
    assert get_resp.json()["entry_node_id"] == "n1"


# ---------------------------------------------------------------------------
# Behavior 7: PUT /flow with no Conclude node → 422 with descriptive message
# ---------------------------------------------------------------------------

def test_put_flow_invalid_returns_422(api_client):
    no_conclude = {
        "entry_node_id": "n1",
        "nodes": [
            {"id": "n1", "type": "tool", "config": {"mcp": "oracle", "label": "Q"}, "edges": [
                {"target_node_id": "n2", "condition": "always"}
            ]},
            {"id": "n2", "type": "branch", "config": None, "edges": []},
        ],
    }
    response = api_client.put("/flow", json=no_conclude)
    assert response.status_code == 422
    assert "conclude" in response.json()["detail"].lower()
