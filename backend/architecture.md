# MeshBoard Backend Architecture

## Responsibility boundaries

| Layer | Responsibility | Must not do |
|---|---|---|
| `api/v1` | HTTP validation, authentication, authorization, transaction boundary | implement simulation or LLM algorithms |
| `services` | Agent execution, routing, simulation and integration logic | trust unvalidated caller identity |
| `models` | Persistence schema and relationships | contain request-specific behavior |
| `schemas` | Public request/response contracts | expose ORM internals |
| `core` | Settings, JWT, RBAC and shared security policy | depend on feature routes |

## Agent invocation

1. The API verifies the caller and agent ownership/access.
2. `invoke_agent` builds the system prompt from the stored agent card.
3. A compiled LangGraph is reused by `(client, model, allowed tools)`.
4. `agent_node` returns a text JSON action because the configured gateway does not reliably preserve native tool calls.
5. `mcp_tool_node` checks the agent's allow-list again before resolving a tool from the global registry.
6. The graph stops on a final answer, error or the maximum tool iteration count.

The allow-list check is an enforcement boundary, not only a prompt instruction. Tool arguments are validated by the LangChain tool schema during `invoke`.

## Checkpoint scope

`MemorySaver` supports interrupt/resume only while the API process is alive. The response reports `durable=false` so clients cannot mistake it for restart-safe execution. Production persistence should replace it with a database-backed LangGraph checkpointer and define retention and ownership rules for thread IDs.

## Message routing and execution trace

Messages are persisted as a header plus an inline JSON body reference. Workspace messages are matched in this order: direct mention, explicit agent ID/role selectors, then subscription edges. Receipts record the routing decision. A workspace-level conversation is created automatically when a generic message does not already belong to a goal conversation.

Every routed request writes a schema `2.0` root interaction and child handoff/reasoning/tool nodes. `execution_tree_id`, `tree_depth` and PostgreSQL `ltree` paths provide stable hierarchy queries. The read adapter normalizes historical schema `1.x` interactions into the current response without rewriting source records.

Matched agents are invoked concurrently with two safeguards:

- `AGENT_INVOKE_MAX_CONCURRENCY` bounds fan-out.
- `AGENT_INVOKE_TIMEOUT_SECONDS` bounds each invocation wait.

Database writes still happen sequentially through one `AsyncSession`. The HTTP request waits for all matched agents; a production deployment should move execution to a durable queue and let the API return a job identifier.

## Trust boundaries

- JWT identifies users; route dependencies enforce RBAC.
- Agent ownership is checked before direct invocation or agent-originated publishing.
- Agent tool calls are constrained by the stored per-agent allow-list.
- Only validated `ACTIVE` policies can be linked. Runtime enforcement handles blocked terms, input size, required certifications, tool allow/deny sets and optional PII masking.
- Marketplace responses expose only non-expired passed certifications as trust badges.
- Policy violations can emit a signed security webhook; production mode requires HTTPS.
- `ENVIRONMENT=production` rejects the development JWT secret and wildcard CORS.
- External HTTP tools remain privileged configuration and require network egress policy before production use.

## Sandbox and simulation boundary

Sandbox workspaces have a dedicated `SANDBOX` state and persist only the input event, deterministic routing decisions and routed IDs in `sandbox_runs`. A database check requires `production_write_count = 0`; sandbox execution never calls tools or writes operational message/interaction rows.

CityLearn and CHESCA are demonstration runtimes behind service interfaces. They are not imported into frontend code. CPU-bound simulation calls use thread offloading where they would otherwise block the FastAPI event loop.

## Operations and retention

- Lifecycle changes signal process-local cooperative cancellation before persisting `SUSPENDED`/`ACTIVE` state.
- Model token totals and parallel-group wall/serial durations are aggregated on demand; optional rates supply estimated USD cost.
- Completed, failed and cancelled interactions older than a selected retention period move transactionally to `interaction_archive`.
- A PostgreSQL trigger rejects archive UPDATE and DELETE operations after migration.

## Known deliberate limitations

- Process-local LangGraph checkpoints
- Text JSON tool protocol for the current LLM gateway
- Request-scoped broker execution rather than a durable worker queue
- Poll/refetch UI updates rather than SSE/WebSocket
- No enterprise IdP (OIDC) integration; authentication is the built-in JWT/RBAC only
- Pause/Kill is cooperative at the API wait boundary; an already-running synchronous provider request may finish in its worker thread and its result is discarded
- Analytics use request-time aggregation rather than a materialized view
