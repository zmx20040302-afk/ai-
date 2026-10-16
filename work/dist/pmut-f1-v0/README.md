# PMUT-F1-v0 task contract

This package freezes the first implementation slice for the existing-model PMUT path.

- Observation point: model-global `(0, 0, -10 um)` on the lower side.
- Objective: maximize `abs(acpr.p_t)` at each design's verified first mode.
- Design domain: continuous `x_scale in [0.20, 1.00]`; discrete integer branches
  `N_w_te2 in {5,6,7,8,9}` and `1 <= N_w_te1 < N_w_te2`.
- Registered fine scalar coverage: 1,782 designs for `N_w_te2 in {5,6,7,8}`;
  registration is not a live per-file availability check.
- Additional raw scalar branch: 648 `N_w_te2=9` designs already exist on the 0.01
  grid. They are separate from legacy C labels: model lineage and numerical-setting
  alignment remain unresolved, so they are not silently merged into training.
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

## Read-only data preparation

Run `scripts/pmut_f1_prepare_data.py --data-root <actual-data-repo> --output <new-run-dir>`
to parse and hash the five explicitly selected raw MAT tables, cross-check the 1,782 C
labels, and create first-observable-pressure-peak export candidates. No data interpolation,
COMSOL solve or model training is performed. Output directories cannot be overwritten.

The 21-case development pilot uses x={0.30,0.60,0.90}, N1={1,...,7}, N2=8.
It is not an independent blind test. Historical holdout roles are retained and must not
be claimed as unseen after using those samples for model development.

`scripts/pmut_f1_export_stored.m` consumes that manifest on a machine with the matching
saved MPH and LiveLink. It rejects oversized/locked sources and existing output folders,
checks parameter/frequency identity, and requires exact-coordinate complex-pressure
readback consistency. It does not execute geometry, mesh or study/solver builds or save MPH.
COMSOL's finite-element evaluation at the exact point is not parameter-space interpolation.
An exported field still lacks verified mode identity and complete geometry/material/BC
inputs; it is not a released neural operator dataset.

The authorized 21-case remote export has been submitted separately. Its contract
entry is a submission record, not live polling or proof of a completed export.
The remote launcher uses a private run directory, an independent 4-thread instance,
resource preflight and a two-hour timeout. It must never be rerun automatically.
After recovery, run `scripts/pmut_f1_validate_export.py --manifest <pilot.json>
--export-dir <recovered-out21> --output <new-qc.json>` to verify the exact file set,
hashes, metadata and independently evaluated point pressure. QC output must be outside
the recovered directory and must not already exist. Passing QC does not establish
first-mode identity, field prediction accuracy, or neural-operator readiness.
