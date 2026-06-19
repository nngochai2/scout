# Mock Ticket Generation Prompt

Use this prompt with the NAA MCPs (Knowledge Graph + Code Graph + Azure DevOps) to generate
grounded mock tickets that reflect real system behaviour in the codebase.

---

## Prompt

You are generating realistic support ticket fixtures for the Scout triage agent.
Use the tools available to you to ground each ticket in real system behaviour.

**Steps:**

1. Call `search_notes` on the Knowledge Graph MCP with queries like "known issues",
   "bug", "incident", "performance", "error" to find documented system problems.

2. Call the Code Graph MCP to find classes and methods mentioned in those notes
   (e.g. search for the class name to get its full qualified name and relationships).

3. Call the Azure DevOps MCP to find related work items (bugs, incidents) for the
   same components.

4. For each grounded issue found, produce a JSON ticket in this shape:

```json
{
  "id": "MOCK-NNN",
  "title": "<concise one-line summary of the user-visible symptom>",
  "description": "<2-4 sentences: what the user observed, when it started, any stack trace hints>",
  "status": "closed",
  "resolution_notes": "<what was actually wrong and how it was fixed — null if unknown>",
  "source_system": "mock"
}
```

**Coverage requirements** — the fixture must include at least one ticket of each type:

| Type | What makes it this type |
|---|---|
| INVESTIGATE | Clear symptom, specific component, `resolution_notes` filled in with real root cause |
| INVESTIGATE | Clear symptom, known component, `resolution_notes` null (agent must discover root cause) |
| CLARIFY | Vague description — agent cannot determine component or impact |
| INSUFFICIENT_SIGNAL | Extremely sparse — no component, no reproduction steps, no error |
| OUT_OF_SCOPE | Feature request or non-technical complaint |

Aim for 7–10 tickets total.

Output: a single JSON array, no prose.
