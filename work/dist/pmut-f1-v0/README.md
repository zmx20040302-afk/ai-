# PMUT-F1-v0 task contract

This package freezes the first implementation slice for the existing-model PMUT path.

- Observation point: model-global `(0, 0, -10 um)` on the lower side.
- Objective: maximize `abs(acpr.p_t)` at each design's verified first mode.
- Design domain: continuous `x_scale in [0.20, 1.00]`; discrete integer branches
  `N_w_te2 in {5,6,7,8,9}` and `1 <= N_w_te1 < N_w_te2`.
- Registered fine scalar coverage: 1,782 designs for `N_w_te2 in {5,6,7,8}`;
  registration is not a live per-file availability check.
- Missing fine scalar branch: 648 `N_w_te2=9` designs on the 0.01 validation grid.
- Existing field solver evidence is limited to `N_w_te2=8`, `N_w_te1 in {4,7}` at
  20 MHz. Later raw-field intake also contains branches `N_w_te1 in {1,2,3,5,6}`.
  Neither is treated as a per-design first-mode operator dataset.
- The target is a mode-routed, geometry-conditioned neural operator. Parameter
  interpolation is forbidden as the target solver; the 20 MHz interpolator is baseline-only.
- A new model may reuse operator weights, but still needs few-shot calibration and an
  independent COMSOL holdout. Unvalidated zero-shot release is forbidden.
- The 2,430-point grid is a candidate pool, not a required COMSOL run list.
  The operator is not trained yet; this package provides the contract and coverage queries.

`contract.json` is intentionally `draft`. It does not promote any AI model and does not
authorize in-place edits of a production `.mph`. Candidate validation must copy the model,
write/read back all three parameters, rebuild geometry, verify named selections, run COMSOL
serially, and wait for the final human release gate.
