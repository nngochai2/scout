"""Dynamic MCP tool-call selection.

Replaces guessing a single hardcoded tool name and a generic ``{"query": ...}``
argument shape for every MCP. Instead, the caller introspects the MCP client's
``list_tools()`` (real names + JSON schemas the server actually exposes) and
this module asks the configured LLM to pick one and build arguments that
match its real schema, tailored to the ticket at hand.
"""
import json

import litellm

from agent.llm_config import resolve as resolve_llm

_SYSTEM = """\
You are selecting a tool to investigate a support ticket. You are given a list \
of available tools — each with its name, description, and the JSON schema of \
arguments it accepts — plus the ticket context. Call exactly one tool, with \
arguments that satisfy its schema. Prefer specific search terms or filters \
drawn from the ticket over copying the ticket text verbatim."""


def select_tool_call(tools: list[dict], ticket_context: str, model: str) -> tuple[str, dict] | None:
    """Ask the LLM to pick one of *tools* and build arguments for it.

    Args:
        tools: schemas from SseMcpClient.list_tools() — ``{"name", "description", "inputSchema"}``.
        ticket_context: formatted ticket + triage summary text.
        model: LLM_MODEL value (resolved against LLM_PROVIDER/LLM_BASE_URL internally).

    Returns:
        (tool_name, arguments) chosen by the model, or None if *tools* is
        empty (nothing the server exposes is in the client's allowlist).
    """
    if not tools:
        return None

    function_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["inputSchema"],
            },
        }
        for t in tools
    ]

    resolved_model, extra = resolve_llm(model)
    response = litellm.completion(
        model=resolved_model,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": ticket_context},
        ],
        tools=function_tools,
        tool_choice="required",
        **extra,
    )

    tool_calls = response.choices[0].message.tool_calls or []
    if not tool_calls:
        return None

    call = tool_calls[0]
    return call.function.name, json.loads(call.function.arguments)
