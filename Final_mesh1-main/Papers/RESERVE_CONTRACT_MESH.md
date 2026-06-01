# Reserve-Contract Mesh Experiment

## Motivation

The first CHESCA mesh experiment improved the aggregate Public and Private
Cost, mainly by improving grid-related metrics. One private schema became
worse, and its degradation was associated with resilience. The earlier mesh
could request additional battery discharge even when the official CHESCA
controller had selected an action to protect its outage reserve.

This is a protocol mismatch: communication may undo a decision that belongs to
the baseline controller's resilience policy.

## Design Hypothesis

The new controller, `chesca_reserve_contract_mesh`, treats reserve as a
peer-advertised feasibility constraint:

1. Official CHESCA calculates the outside-option action exactly as before.
2. Each normal-operation building calculates the next-step reserve already
   prescribed by CHESCA:

   `min_soc_per_hour[(hour + 1) % 24]`

3. A building may advertise extra discharge only from predicted SOC above
   that official reserve.
4. Extra charging flexibility remains available, because it does not consume
   the protected reserve.
5. Peers choose among feasible offers with the same district peak, ramping,
   price, and carbon communication signal. No post-hoc resilience penalty is
   introduced.

The change is therefore structural, not a private-schema-specific parameter
tune: the mesh may coordinate flexibility, but it may not spend the baseline
controller's declared emergency reserve.

## Evaluation

Run `RUN_CHESCA_RESERVE_CONTRACT_MESH_COLAB.ipynb`. It evaluates:

- `chesca_official`: unmodified downloaded CHESCA source.
- `chesca_mesh`: the earlier unrestricted peer negotiation.
- `chesca_reserve_contract_mesh`: the new constrained negotiation.

All result tags are new (`reserve_contract_comparison_v1` and
`paper_public_private_reserve_contract_v1`), so earlier outputs are preserved.

In addition to the official Public Cost and Private Cost, inspect the
per-schema `grid_cost` and `resilience_cost` changes. Those two columns are
diagnostic: they explain whether reserve-preserving communication solved the
identified tradeoff, while Public/Private Cost remains the main score.

Because previous private-schema outcomes have already been inspected during
development, improvements on those same schemas should be reported as
development evidence rather than as a new unseen-test claim.
