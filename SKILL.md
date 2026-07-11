---
name: chatgpt-codex-collaboration
description: "Use when ChatGPT should do the main coding work and Codex should use low-cost turns for planning, monitoring, and acceptance. Keep the workflow small: define one bounded work item, send it to ChatGPT through the available browser or handoff path, observe the result, and verify the submitted change."
---

# ChatGPT-Codex Collaboration

## Purpose

Use ChatGPT as the primary developer because it is the higher-capability implementation tool. Use Codex as the low-cost controller for only three jobs:

1. **Plan** — understand the request and authoritative spec, then define one bounded work item.
2. **Monitor** — send that work to ChatGPT and observe for a result, commit, or explicit failure.
3. **Accept** — inspect the change, run the required checks, and decide whether it is accepted or needs repair.

Do not turn Codex into a second primary developer. Do not build a second control system for the assistant itself.

## Roles

- **ChatGPT:** understand the implementation request, edit files, run relevant checks, and commit the change.
- **Codex:** read the spec, define the bounded work, monitor the handoff, verify the result, and request repair when evidence fails.
- **User:** decide product behavior that the spec does not define.

ChatGPT's report is a candidate handoff, not acceptance. Codex's acceptance must be based on the repository, diff, commit, and verification results.

## Minimal workflow

1. Read the user's request, repository instructions, and authoritative spec.
2. Define one small work item with its allowed files and acceptance checks.
3. Send that work item to ChatGPT using the available browser or handoff mechanism.
4. Wait for one outcome: a commit, an explicit failure, or a missing decision.
5. Inspect the submitted diff and run the acceptance checks yourself.
6. Accept it, send one focused repair request, or stop and ask the user for the missing decision.

## Boundaries

- One handoff contains one bounded work item.
- A commit is evidence of delivery, not proof of correctness.
- Never claim acceptance from ChatGPT's prose alone.
- Never repeat the same prompt, screenshot, status message, or repair without new evidence.
- Never invent product behavior when the spec is silent.
- Never use a fallback implementation merely to make the workflow appear complete.

The skill ends after acceptance, a clearly evidenced failure, or a required user decision.
