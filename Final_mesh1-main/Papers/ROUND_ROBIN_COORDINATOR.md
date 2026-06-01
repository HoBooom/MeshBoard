# Round-Robin Coordinator Mesh

## Purpose

The previous commitment mesh used CHESCA as a fixed baseline action generator.
This experiment reframes the same CHESCA planning capability as a tool owned by
building agents. At each step, one building is selected as the temporary
coordinator by round-robin order.

The selected coordinator:

1. uses the `CHESCAPlannerTool`;
2. creates the same baseline proposal that CHESCA would have created;
3. hands that proposal to the existing commitment mesh negotiation process.

## Performance Expectation

When no coordinator agents are unavailable, the controller
`chesca_round_robin_commitment_full_mesh` should match
`chesca_commitment_full_mesh`, because the underlying planner and negotiation
logic are intentionally identical. The difference is protocol-level ownership
and logging, not a new optimization rule.

## Why This Helps the Story

This does not make the system purely decentralized, because the temporary
coordinator still observes the full district state. However, it removes the
fixed central-controller interpretation:

- before: one fixed CHESCA controller always proposes the baseline;
- after: a rotating building agent uses CHESCA as a planner tool.

This prepares later robustness tests:

- coordinator dropout: if one coordinator cannot serve, another agent can take
  the coordinator role;
- communication dropout: a silent building can fall back to the baseline while
  the rest of the mesh keeps negotiating.

The current notebook focuses on the no-failure equivalence check.
