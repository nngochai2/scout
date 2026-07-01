"""Tests for select_tool_call — dynamic MCP tool selection from introspected schemas."""
import json
import types

import litellm
import pytest

from agent.mcp_dispatch import select_tool_call


# ---------------------------------------------------------------------------
# Behavior: no tools exposed -> None, without calling the LLM at all
# ---------------------------------------------------------------------------

def test_select_tool_call_with_no_tools_returns_none_without_llm_call(monkeypatch):
    def _fail(**kw):
        raise AssertionError("litellm.completion should not be called when tools is empty")

    monkeypatch.setattr(litellm, "completion", _fail)

    result = select_tool_call(tools=[], ticket_context="some ticket", model="claude-haiku-4-5-20251001")

    assert result is None


# ---------------------------------------------------------------------------
# Behavior: picks a tool from the given schemas and returns matching arguments
# ---------------------------------------------------------------------------

def _fake_tool_selection_completion(name="search_notes", arguments=None):
    args = json.dumps(arguments if arguments is not None else {"query": "SSO login timeout"})
    fn = types.SimpleNamespace(name=name, arguments=args)
    tool_call = types.SimpleNamespace(function=fn)
    msg = types.SimpleNamespace(tool_calls=[tool_call], content=None)
    choice = types.SimpleNamespace(message=msg)
    usage = types.SimpleNamespace(prompt_tokens=150, completion_tokens=40)
    return types.SimpleNamespace(choices=[choice], usage=usage)


def test_select_tool_call_picks_tool_and_returns_matching_arguments(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.setattr(litellm, "completion", lambda **kw: _fake_tool_selection_completion())

    tools = [
        {
            "name": "search_notes",
            "description": "Full-text search over the knowledge graph.",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
    ]

    result = select_tool_call(tools=tools, ticket_context="Subject: SSO login times out", model="claude-haiku-4-5-20251001")

    assert result == ("search_notes", {"query": "SSO login timeout"})
