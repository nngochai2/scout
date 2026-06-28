"""Deterministic Workflow Engine — walks an InvestigationFlow node by node.

Replaces the multi-turn tool_use loop in investigate.py.  The engine is pure:
no database access, no Claude calls unless a real evaluate_fn is passed.
Callers (run_batch.py) are responsible for persisting results.
"""
import json
import os
from dataclasses import dataclass, field
from typing import Callable

import litellm

from agent.flow import BranchEdge, InvestigationFlow
from agent.models import (
    Confidence,
    Diagnosis,
    Evidence,
    EvidenceType,
    Ticket,
    TriageResult,
)

MAX_NODE_VISITS = 20

# Callables injected by the caller (or tests)
McpFn = Callable[[str], str]               # ticket_context → tool_result_string
EvaluateFn = Callable[[str, str, str], "EvaluateResult"]  # ctx, node_label, tool_result → result


@dataclass
class EvaluateResult:
    confidence: Confidence
    root_cause: str | None
    evidence: list[Evidence] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class StageRecord:
    """Token usage for a single Tool Node visit — caller persists to DB."""
    ticket_id: str
    stage: str          # node label; stored as-is in stage_counts.stage
    input_tokens: int
    output_tokens: int


class WorkflowEngine:
    def __init__(
        self,
        flow: InvestigationFlow,
        mcp_fns: dict[str, McpFn],
        evaluate_fn: EvaluateFn | None = None,
    ) -> None:
        self._flow = flow
        self._mcp_fns = mcp_fns
        self._evaluate_fn = evaluate_fn if evaluate_fn is not None else _real_evaluate

    def investigate(self, ticket: Ticket, triage: TriageResult) -> tuple[Diagnosis, list[StageRecord]]:
        node_map = {n.id: n for n in self._flow.nodes}
        ticket_context = _format_ticket_context(ticket, triage)

        all_evidence: list[Evidence] = []
        last_root_cause: str | None = None
        last_confidence = Confidence.INSUFFICIENT
        stage_records: list[StageRecord] = []

        current_id = self._flow.entry_node_id
        visits = 0

        while visits < MAX_NODE_VISITS:
            visits += 1
            node = node_map[current_id]

            if node.type == "conclude":
                break

            if node.type == "tool":
                mcp_fn = self._mcp_fns.get(node.config.mcp, _disconnected(node.config.mcp))
                tool_result = mcp_fn(ticket_context)
                eval_result = self._evaluate_fn(ticket_context, node.config.label, tool_result)

                last_confidence = eval_result.confidence
                last_root_cause = eval_result.root_cause
                all_evidence.extend(eval_result.evidence)
                stage_records.append(StageRecord(
                    ticket_id=ticket.id,
                    stage=node.config.label,
                    input_tokens=eval_result.input_tokens,
                    output_tokens=eval_result.output_tokens,
                ))

            next_id = _pick_next(node.edges, last_confidence)
            if next_id is None:
                break
            current_id = next_id

        else:
            # Guard: MAX_NODE_VISITS exceeded
            return Diagnosis(
                ticket_id=ticket.id,
                root_cause=None,
                confidence=Confidence.INSUFFICIENT,
                evidence=[],
                triage_verdict=triage.verdict,
            ), []

        return Diagnosis(
            ticket_id=ticket.id,
            root_cause=last_root_cause,
            confidence=last_confidence,
            evidence=all_evidence,
            triage_verdict=triage.verdict,
        ), stage_records


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pick_next(edges: list[BranchEdge], confidence: Confidence) -> str | None:
    for edge in edges:
        if _matches(edge.condition, confidence):
            return edge.target_node_id
    return None


_CONFIDENCE_ORDER = [Confidence.INSUFFICIENT, Confidence.LOW, Confidence.MEDIUM, Confidence.HIGH]


def _matches(condition: str, confidence: Confidence) -> bool:
    idx = _CONFIDENCE_ORDER.index(confidence)
    if condition == "always":
        return True
    if condition == "gte_high":
        return idx >= _CONFIDENCE_ORDER.index(Confidence.HIGH)
    if condition == "gte_medium":
        return idx >= _CONFIDENCE_ORDER.index(Confidence.MEDIUM)
    if condition == "eq_low":
        return confidence == Confidence.LOW
    if condition == "eq_insufficient":
        return confidence == Confidence.INSUFFICIENT
    return False


def _format_ticket_context(ticket: Ticket, triage: TriageResult) -> str:
    parts = [f"Subject: {ticket.title}"]
    if ticket.description:
        parts.append(f"Description: {ticket.description}")
    parts.append(f"Triage summary: {triage.summary}")
    return "\n\n".join(parts)


def _disconnected(mcp_name: str) -> McpFn:
    return lambda _ctx: f"[MCP '{mcp_name}' not connected — no callable registered]"


_EVALUATE_TOOL = {
    "type": "function",
    "function": {
        "name": "record_findings",
        "description": "Record the root cause, confidence, and supporting evidence found in the tool result.",
        "parameters": {
            "type": "object",
            "properties": {
                "confidence": {"type": "string", "enum": ["high", "medium", "low", "insufficient"]},
                "root_cause": {"type": "string"},
                "evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_type": {"type": "string", "enum": ["DOC", "DB", "CODE", "ADO"]},
                            "reference": {"type": "string"},
                            "passage": {"type": "string"},
                        },
                        "required": ["source_type", "reference", "passage"],
                    },
                },
            },
            "required": ["confidence", "evidence"],
        },
    },
}

_EVALUATE_SYSTEM = """\
You are evaluating a single tool result for a support ticket investigation.
Given the ticket context and the tool output, extract:
- confidence: how confident are you that this result explains the root cause?
- root_cause: a concise one-sentence explanation, or null if insufficient evidence
- evidence: specific passages from the tool result that support the conclusion

Be conservative — only rate HIGH if the tool result directly explains the issue.
"""


def _real_evaluate(ticket_context: str, node_label: str, tool_result: str) -> EvaluateResult:
    """Production Evaluate step: single LiteLLM call to extract structured findings."""
    model = os.getenv("LLM_MODEL", "")
    user_msg = (
        f"## Ticket\n{ticket_context}\n\n"
        f"## Tool: {node_label}\n{tool_result}"
    )
    extra = {}
    base_url = os.getenv("LLM_BASE_URL", "")
    if base_url:
        extra["api_base"] = base_url
        if "/" not in model:
            model = f"openai/{model}"
    response = litellm.completion(
        model=model,
        max_tokens=1024,
        messages=[
            {"role": "system", "content": _EVALUATE_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        tools=[_EVALUATE_TOOL],
        tool_choice={"type": "function", "function": {"name": "record_findings"}},
        **extra,
    )

    usage = response.usage
    input_tokens = usage.prompt_tokens
    output_tokens = usage.completion_tokens

    tool_calls = response.choices[0].message.tool_calls or []
    for call in tool_calls:
        if call.function.name == "record_findings":
            inp = json.loads(call.function.arguments)
            evidence = [
                Evidence(
                    source_type=EvidenceType(e["source_type"]),
                    reference=e["reference"],
                    passage=e["passage"],
                )
                for e in inp.get("evidence", [])
            ]
            return EvaluateResult(
                confidence=Confidence(inp["confidence"]),
                root_cause=inp.get("root_cause"),
                evidence=evidence,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

    return EvaluateResult(
        confidence=Confidence.INSUFFICIENT,
        root_cause=None,
        evidence=[],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
