# scrum-planner — OpenClaw Skill

An OpenClaw skill that conducts conversational scrum planning intake and generates full project plans via the **yeaboi MCP server**.

## Prerequisites

- **uv** installed on the OpenClaw instance (the server runs via `uvx`).
- **The yeaboi MCP server registered** in OpenClaw's MCP configuration:
  ```
  command: uvx --from 'yeaboi[mcp]' yeaboi-mcp     (stdio)
  ```
- **Setup wizard** completed for credentials: `uvx yeaboi --setup`
- **Verified** the server starts: `uvx --from 'yeaboi[mcp]' yeaboi-mcp` (Ctrl-C to stop)

## Installation

The skill is bundled with yeaboi. Install it with a single command:

```bash
yeaboi --install-skill
```

This copies SKILL.md, README.md, and the `references/` folder to the OpenClaw skills directory and sandbox workspace.

To install to a custom directory:

```bash
yeaboi --install-skill /path/to/openclaw/skills
```

Alternatively, copy manually:

```bash
# From your local machine
scp -r skills/scrum-planner/ user@lightsail-ip:~/.openclaw/skills/scrum-planner/
```

## How It Works

The skill conducts a 7-question conversational intake, then calls the yeaboi MCP server's `plan_generate` tool with the collected answers — typed tool calls, no temp files, no shell-out, no polling.

### Question-to-Tool Mapping

| Question | Maps to `plan_generate` | Notes |
|----------|------------------------|-------|
| Q1: Project description | `description` | Required |
| Q2: Project type | `answers[2]` | Keywords: "greenfield", "existing codebase", "hybrid" |
| Q3+Q4: Problem/users/done | `answers[3]` + `answers[4]` | Merged into one conversational question |
| Q6: Team size | `team_size` | Integer |
| Q8: Sprint length | `sprint_length_weeks` | Integer (1-4) |
| Q10: Target sprints | `answers[10]` | Text value |
| Q11: Tech stack | `answers[11]` | Include framework, DB, infra names |
| Optional context / roles / constraints | `project_context` | Free-form; keyword-extracted into remaining answers |

The full question contract (all 30 questions, defaults, choice options) is available from the `intake_questions` tool.

### Skill File Structure

```
skills/scrum-planner/
  SKILL.md                          — Core skill (intake, questions, confirmation, MCP generation)
  README.md                         — This file
  references/
    output-and-review.md            — Phase-by-phase review, Canvas output, error handling
  scripts/
    canvas.py, canvas_push.py       — Slack Canvas helpers for the final plan output
```

The SKILL.md is kept small so it doesn't exceed Bedrock's context on every conversation turn. The `references/` files are only loaded when needed (after generation).

### Flow

1. User describes their project (or says "just plan it" for quick mode)
2. Skill extracts what it can, asks follow-up questions with numbered choices
3. Shows confirmation summary with answer sources and defaults
4. On confirmation: calls `plan_generate` (returns the complete plan in one call, ~2-5 minutes)
5. Reads `references/output-and-review.md`, presents results phase-by-phase (features → stories → tasks → sprints) with accept/edit/regenerate
6. After all phases accepted: summary + offer to export as Canvas, Markdown, Notion/Confluence (`plan_publish`), or push to Jira

## Example Conversation

```
User: I need to plan a mobile banking app

Skill: Great! Let me help you plan that out. Is this a greenfield project,
       building on an existing codebase, or a hybrid?

User: Greenfield

Skill: What problem does this solve, who are the end users, and what does
       'done' look like?

User: Our retail customers need mobile check deposit and P2P transfers.
      Done = both features live in app stores with 99.9% uptime.

Skill: How many engineers are working on this?

User: 6

Skill: How long are your sprints? (1, 2, 3, or 4 weeks — default is 2)

User: 2

Skill: What's the tech stack?

User: React Native, Node.js, PostgreSQL, deployed on AWS ECS

Skill: How many sprints are you targeting? (1-2, 3-5, 6-10, 10+, or let
       the agent decide)

User: 6-10

Skill: Anything else? Constraints, integrations, risks, out of scope?

User: Must integrate with Plaid for bank connections. PCI compliance required.
      No crypto features in v1.

Skill: Here's what I've got:

       | Question        | Answer                                          |
       |-----------------|------------------------------------------------|
       | Project         | Mobile banking app                              |
       | Type            | Greenfield                                      |
       | Problem & done  | Retail customers need mobile check deposit...   |
       | Team size       | 6 engineers                                     |
       | Sprint length   | 2 weeks                                         |
       | Tech stack      | React Native, Node.js, PostgreSQL, AWS ECS      |
       | Target sprints  | 6-10 sprints                                    |
       | Extra context   | Plaid integration, PCI compliance, no crypto    |

       Does this look right?

User: Yes

Skill: [runs yeaboi, presents results]

       Generated 5 features, 18 stories, 47 tasks across 8 sprints.
       ...
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| yeaboi tools not available | Register the MCP server: `uvx --from 'yeaboi[mcp]' yeaboi-mcp` in OpenClaw's MCP config |
| Auth/credential errors (`ok: false` + hint) | Run `uvx yeaboi --setup` to reconfigure API keys |
| `llm_mode: "fallback"` skeleton plans | No LLM reachable — configure a provider with `uvx yeaboi --setup` |
| Timeout (>5 min) | Simplify description or reduce target sprints |
| Thin plans | Put specific tech stack and constraints in `answers[11]` / `project_context` |
| Bedrock throttling in Slack | SKILL.md too large — ensure `references/` files are installed (not inlined) |
| Canvas not created | Add `canvases:read` and `canvases:write` scopes to Slack App, reinstall app |

## Related

- [yeaboi README](../../README.md) — full CLI docs and deployment guide
- [SCRUM.md.example](../../SCRUM.md.example) — template for the generated SCRUM.md
- [Lightsail deployment guide](../../README.md#deploy-on-aws-lightsail-openclaw) — full setup instructions
