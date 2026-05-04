# Multi-Agent Control Dashboard Rebuild

Date: 2026-05-03
Branch: `feat/multi-agent-control-dashboard`

## Goal

Rebuild the original Hermes Dashboard into a LAN-accessible multi-agent control page while keeping the system performance dashboard and preserving the app's modular FastAPI + vanilla ES module architecture.

## UX design

- Top-level page becomes `Hermes Control`.
- System performance remains visible as a compact operational panel.
- Agent Activity panel shows one widget each for:
  - Hermione
  - Hephaestus
  - Argus
  - Athena
  - Aegis
  - Daedalus
  - Vox
- Agent widgets use profile images from `~/Hermes Profiles` through an allowlisted avatar endpoint.
- Mission Board combines dashboard-created task requests and read-only Hermes kanban tasks.
- Command Console remains available for direct Hermes interaction.

## Backend design

New modules:

- `src/hermes_dashboard/agents.py`
  - Fixed roster, roles, avatar filenames, assignee normalization.

- `src/hermes_dashboard/api/agents.py`
  - `GET /api/agents/roster`
  - `GET /api/agents/status`
  - `GET /api/agents/events`
  - `GET /api/agents/{agent_id}/avatar`

- `src/hermes_dashboard/collectors/agent_activity.py`
  - Read-only projection from `~/.hermes/kanban.db`.
  - Infers active/current task/progress from assignee, status, heartbeat, and current step.

- `src/hermes_dashboard/api/tasks.py`
  - `POST /api/tasks`
  - `PATCH /api/tasks/{task_id}`
  - `GET /api/tasks/board`
  - `GET /api/tasks/events`
  - `POST /api/tasks/archive`

State:

- `~/.hermes/dashboard-state.json` remains dashboard-owned state.
- Dashboard task requests are stored there until Hermione bridges them into real agent work.
- Hermes' own SQLite databases remain read-only from this service.

## Kanban workflow

Columns now reflect the requested assignment flow:

1. Assigned / Awaiting Hermione
2. Queued / Assigned
3. In Progress
4. Done

Rules:

- User-created dashboard tasks start in Assigned / Awaiting Hermione with assignee Hermione.
- Hermes kanban tasks with `triage`, `todo`, or `ready` and no assignee appear in Assigned / Awaiting Hermione.
- Hermes kanban tasks with `triage`, `todo`, or `ready` and an assignee appear in Queued / Assigned.
- `running` and `blocked` appear in In Progress.
- `done` appears in Done for 3 days, then hides from the dashboard view.
- Manual archive watermark behavior still exists, but no direct writes are made to `kanban.db`.

## Security notes

Aegis review result:

- New task APIs do not execute commands and do not mutate Hermes internal SQLite.
- Avatar serving is allowlisted by known agent id and filename.
- Risk remains because the dashboard is LAN-accessible and the pre-existing `/api/chat/send` endpoint is an unauthenticated Hermes control surface.
- Deployment is acceptable only for a trusted LAN/VPN segment.

Hardening added during implementation:

- `PATCH /api/tasks/{id}` uses strict status/handoff enums and string length limits.
- Task creation body/title/priority are bounded.
- Dashboard tasks are stored in dashboard-owned JSON only.

Recommended future hardening:

- Add authentication or reverse proxy protection before broader LAN exposure.
- Add audit JSONL for task creates/patches and chat sends.
- Add request rate limiting/body-size limits.
- Optionally disable chat on unauthenticated LAN deployments.

## Validation

- `python -m pytest -q` => 47 passed.
- `systemctl --user restart hermes-dashboard` successful after the old process timed out during stop and systemd killed it.
- `curl http://127.0.0.1:2002/healthz` => `{"status":"ok"}`.
- LAN check: `http://10.10.27.53:2002/` returns HTTP 200.
- Browser smoke test: page renders system metrics, seven agent cards, mission board task form, and command console with no console errors.
