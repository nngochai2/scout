"""Tests for _real_evaluate — LiteLLM-based evidence extraction."""
import json
import types

import litellm
import pytest

import agent.workflow_engine as engine_module
from agent.models import Confidence
from agent.workflow_engine import _real_evaluate


def _fake_tool_completion(confidence="high", root_cause="Token cache race condition"):
    args = json.dumps({
        "confidence": confidence,
        "root_cause": root_cause,
        "evidence": [
            {"source_type": "DOC", "reference": "auth.md:p3", "passage": "Token expires on reset."}
        ],
    })
    fn = types.SimpleNamespace(name="record_findings", arguments=args)
    tool_call = types.SimpleNamespace(function=fn)
    msg = types.SimpleNamespace(tool_calls=[tool_call], content=None)
    choice = types.SimpleNamespace(message=msg)
    usage = types.SimpleNamespace(prompt_tokens=200, completion_tokens=80)
    return types.SimpleNamespace(choices=[choice], usage=usage)


def test_real_evaluate_returns_confidence_and_evidence(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.setattr(litellm, "completion", lambda **kw: _fake_tool_completion())

    result = _real_evaluate("ticket context", "Search docs", "some tool output")

    assert result.confidence == Confidence.HIGH
    assert result.root_cause == "Token cache race condition"
    assert len(result.evidence) == 1
    assert result.evidence[0].reference == "auth.md:p3"
    assert result.input_tokens == 200
    assert result.output_tokens == 80
