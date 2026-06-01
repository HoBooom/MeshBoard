# Commitment Mesh Experiment

## Purpose

The unrestricted CHESCA mesh improved Public and Private Cost, but it had no
memory of additional battery discharge. The reserve-contract variant was too
conservative: it protected CHESCA's reserve, but it also removed most grid
relief. Commitment mesh keeps the original communication cadence and adds
memory instead of hard blocking flexibility.

## Protocol

At every negotiation step, each peer still broadcasts offers around its
official CHESCA battery action. The communication payload is extended with:

- outstanding recovery debt created by previous extra discharge;
- recent mesh-induced battery throughput;
- projected debt after choosing each offer.

Only mesh deviations from official CHESCA actions are recorded. CHESCA's own
battery trajectory is not counted as debt.

## Ablations

The Colab notebook exposes four commitment controllers:

- `chesca_commitment_ledger_mesh`: records discharge debt and makes further
  relief slightly less attractive for peers already carrying debt.
- `chesca_commitment_recovery_mesh`: adds local recovery priority, so agents
  with debt prefer extra charging when the shared district signal is low.
- `chesca_commitment_budget_mesh`: adds a soft rolling throughput friction
  without debt/recovery.
- `chesca_commitment_full_mesh`: combines ledger, local recovery, and soft
  throughput budget.

The important distinction is that recovery is not a new peer-to-peer trade.
Peers continue to listen to mesh-wide stress signals, but each building repays
its own debt locally when charging is cheap for the district.

## Interpretation

This experiment should be read as an ablation suite, not a single final model.
The expected diagnostic columns are:

- `challenge_cost`, `grid_cost`, `resilience_cost`;
- `extra_discharge_soc_total`, `extra_charge_soc_total`;
- `debt_created_soc_total`, `debt_repaid_soc_total`;
- `mean_total_debt_soc`, `max_peer_debt_soc`;
- `recovery_action_steps`, `relief_action_steps`.

If `ledger` helps but `recovery` hurts, repayment timing is wrong. If `budget`
helps public/private stability but reduces grid gains too much, the budget
friction is over-regularizing. If `full` improves less than the old mesh, the
unrestricted mesh remains the main model and commitment becomes a documented
negative ablation.
