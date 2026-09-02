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

## Message routing

Messages are persisted as a header plus an inline JSON body reference. Workspace messages are matched by direct mention first and subscription edges second. Receipts record the routing decision.

Matched agents are invoked concurrently with two safeguards:

- `AGENT_INVOKE_MAX_CONCURRENCY` bounds fan-out.
- `AGENT_INVOKE_TIMEOUT_SECONDS` bounds each invocation wait.

Database writes still happen sequentially through one `AsyncSession`. The HTTP request waits for all matched agents; a production deployment should move execution to a durable queue and let the API return a job identifier.

## Trust boundaries

- JWT identifies users; route dependencies enforce RBAC.
- Agent ownership is checked before direct invocation or agent-originated publishing.
- Agent tool calls are constrained by the stored per-agent allow-list.
- `ENVIRONMENT=production` rejects the development JWT secret and wildcard CORS.
- External HTTP tools remain privileged configuration and require network egress policy before production use.

## Simulation boundary

CityLearn and CHESCA are demonstration runtimes behind service interfaces. They are not imported into frontend code. CPU-bound simulation calls use thread offloading where they would otherwise block the FastAPI event loop.

## Known deliberate limitations

- Process-local LangGraph checkpoints
- Text JSON tool protocol for the current LLM gateway
- Request-scoped broker execution rather than a durable worker queue
- Poll/refetch UI updates rather than SSE/WebSocket
- Mock OIDC provider rather than a configured enterprise IdP
- Trust policy CRUD exists, but policy enforcement is not yet wired into every tool/action
