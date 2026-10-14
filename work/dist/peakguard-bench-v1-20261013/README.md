# PeakGuard-Bench v1 — a reliability benchmark for surrogate models of resonant multiphysics design

**What this is.** A frozen, self-contained benchmark for *how a surrogate model of a resonant
multiphysics design task should be evaluated*: label validity, split structure, strong baselines,
abstention, and the failure modes that make a numerically present label physically incomparable.

**What this is not.** It is not a solver, not a device database, and not a claim about any engineering
absolute value. All labels are **simulation** values for a piezoelectric micromachined ultrasonic
transducer (PMUT) parameter sweep; there is no experimental data in the package.

## Contents

| path | what |
|---|---|
| `data/labels_two_batch_v3.csv` | the 2,255-row union label table (two scan batches + one frozen 250-row batch) |
| `data/channels_multichannel.csv` | the eight-channel source table with the native state flags |
| `data/labels_v2_frozen.csv` | the frozen 250-row batch (four channels only) |
| `data/splits_grouped_five_seeds.csv` | the frozen split assignment, five seeds (`side_seed0..4`) |
| `data/excluded_quarantine.json` | the frozen quarantine list used by the ablations |
| `config/thresholds.json` | S0–S5 thresholds, copied unchanged |
| `bench.py` | the evaluation program (vendored, path-sanitised) |
| `pchip_fitter.py` | the registered PCHIP caliber implementation (vendored) |
| `run_benchmark.py` / `check_results.py` | one-command entry point and the expected-value checker |
| `check_solution_identity.py` | the four-step solution-identity check (see below) |
| `data/solution_identity_example.json` | synthetic record for that check, mirroring the measured probe |
| `tasks/` | **six task scripts covering five analyses**: label validity, split structure, T1/T2 classification (with a spacing/leakage addendum), refusal, closed-loop scheduling |
| `tasks/_text.py` | the English rendering table for the frozen free-text strings (see "Language" below) |
| `tasks/ref_ledger.json` | designs-only projection that pins the closed-loop call schedule (carries **no** objective values) |
| `tasks/t7_frozen_protocol.py` | the closed-loop pre-registration's **structural** content as data (the document itself is not distributed) |
| `oracle/points/` | the frozen closed-loop campaign cache, replayed **without any solver** |
| `run_tasks.py` / `check_tasks.py` | task-suite entry point and its deep checker |
| `verify_package.py` | seconds-long integrity check: per-file sha256, expected-file sanity, identity self-test |
| `expected/EXPECTED_OUTPUTS.json` | per-seed per-cell reference medians + anchors |
| `expected/EXPECTED_TASKS.json` | frozen reference for every task output, with the stripping policy recorded |
| `REPRODUCIBILITY.md` | **which reported numbers this package does and does not reproduce, and why** |
| `requirements.txt` | pinned versions (bit-for-bit needs them; see `MANIFEST.json`) |
| `MANIFEST.json` | sha256 of every file, plus a machine-run identity audit |

## Reproduce

```
python -m pip install -r requirements.txt
python run_benchmark.py --check-only   # seconds: is this copy intact?
python run_benchmark.py --check        # baselines + ablations + identity self-test
python run_tasks.py --check            # the task suite, then a deep comparison against expected/
```

**Timings drift with machine load and are not a promise.** Across **3** recorded packaged full-chain runs on the authors' machine the baseline stage took **393-765 s** and the task suite **680-708 s** (full chain **1073-1474 s**, i.e. up to **24.6 minutes**). `m1_m2_m3` dominates the task suite (it refits eight methods for the random-split arm and recomputes the risk-coverage curves); the other five stages together finish in seconds to tens of seconds. That single stage measured **624-676 s** (10.4-11.3 minutes) across these runs, i.e. the same stage varied by 8% purely from concurrent load. So budget **25 minutes** for a full reproduction and do not treat any single figure here as a bound. No caching, subsampling or convergence-limit shortcut was taken to speed this up, because each would change the numbers.

**Language.** The internal pipeline wrote its free-text fields (calibers, non-claims, per-cell notes) in
Chinese. This package is an English artifact, so those strings are rendered in English by one explicit
table, `tasks/_text.py`, applied identically to the produced outputs and to the expected values — only
those string values change; no number, key name or structure does. Everything a reviewer reads as data
is English. The original text survives in exactly four places — the rendering table itself, comments in
the two vendored evaluation files, comments in the ported task scripts, and note fields inside the 94
frozen oracle payloads (which are shipped byte-for-byte as evidence) — and section 1 of
`REPRODUCIBILITY.md` names each one, with its size, so the claim can be checked rather than trusted.

Outputs land in `results/` (`baselines_by_seed.json`, `baseline_table.md`, and — unless
`--skip-ablations` — `ablations.json`, `ablations.md`). `--check` compares every per-seed per-cell
median against `expected/EXPECTED_OUTPUTS.json` with relative tolerance `1e-6`, prints `PASS`/`FAIL`,
and then runs `check_solution_identity.py` as a self-test on the bundled record.

`run_tasks.py` **needs** `results/baselines_by_seed.json` and fails closed if it is absent rather than
skipping stages. Its comparison is a **deep** one — structure, key names and values — so a changed
caliber or a dropped channel fails it, not just a changed number. Read `REPRODUCIBILITY.md` before
quoting any of the paper's numbers from this package.

## Solution identity, and why a numeric label can be incomparable

A single model file can hold several **solutions**. Re-evaluating post-processing on a stored solution
is unsafe once the model was re-meshed or its geometry edited after that solution was stored: selection
sets and entity numbers can go stale. In the measured case behind this benchmark, a probe evaluated from
a hard-coded face list differed by a factor **6.667** between two solutions of one file that shared an
**identical geometry** (fluid-domain volume equal to ten digits), an **identical parameter read-back**,
and a **single mesh object**. With geometry, mesh object and parameters identical, the only consistent
explanation is that the same entity numbers addressed different physical faces on the two stored meshes.

Before any number is compared across stored solutions or across files, all four of these must hold:

1. **Tag** — every compared solution is named, and the names are unique.
2. **Stored mesh** — every solution carries a digest of the mesh *it stored*, not of the model's current
   mesh.
3. **Parameters** — every compared solution reads back identical parameters at the design point.
4. **Invariant** — a geometry-only integral (such as the fluid-domain volume) agrees within tolerance.

Passing the four steps is **not** sufficient by itself. A quantity that depends on entity numbering may
be compared across solutions only if all of them share **one** stored-mesh digest, or if the selection
was **re-resolved on each solution's own mesh** by a geometric predicate. Copying entity indices between
solutions is never admissible — `check_solution_identity.py` refuses it and reports the observed spread,
so the refusal can be audited rather than trusted. It prints both the relative spread (relative to the
smallest compared value: 5.667 for the electrode area) and the corresponding ratio hi/lo (**6.667**, the
factor quoted above); the two are the same fact stated differently. Where re-resolution is impossible,
the quantity must be **re-solved** rather than re-used.

```
python check_solution_identity.py                 # self-test on the bundled record
python check_solution_identity.py RECORDS.json    # your own record
```

The bundled record is **synthetic and labelled as such**: its quantities mirror the measured probe, its
stored-mesh digests are synthetic labels (the file does not expose one), and its `expected_decision`
makes the script a self-test. Exit code 0 means the checker reproduced that recorded decision; it never
means the physics is right. This rule is bookkeeping, not physics: the discarded readings are not
claimed to be wrong, only non-comparable.

## The tasks

The benchmark is evaluated in two halves. `run_benchmark.py` covers the **regression** half — eight
strong baselines under a frozen duplicate-aware split with five seeds, plus six ablations, plus the
OOD abstention that is part of the ablation set. `run_tasks.py` covers the **analysis** half, which is
where the paper's negative and diagnostic results live:

| task | script | what it produces | paper |
|---|---|---|---|
| label validity | `tasks/label_validity.py` | rows per batch; how many two-sided −3 dB bandwidths are undefined because the crossing leaves the scan window; per-channel defined counts | §5, §6.1 |
| split structure and sensitivity | `tasks/m1_m2_m3.py` | what the split actually groups (duplicate clusters vs spacing), the x-adjacency leakage fraction, how much the verdict moves across split realisations, a risk–coverage curve under a pre-registered score, and cross-batch transfer gaps | §4.1, §6.3 |
| peak identity and closure classification | `tasks/t1_t2.py` (+ `tasks/t1_t2_spacing.py`, the spacing/leakage addendum) | balanced accuracy for predicting the label's own state flags, per batch and seed, under the frozen split | §6.3 |
| refusal behaviour | `tasks/t5.py` | accepted/refused counts and the false-accept rate at three registered tolerances | §6.2, §7 |
| closed-loop scheduling | `tasks/t7_scheduling.py` | four acquisition arms under a fixed budget, best-at-k and simple regret, and the out-of-domain proposal replay — **replayed from `oracle/points/` with zero solves** | §6.6 |

1. **Label validity** — a two-sided −3 dB bandwidth is undefined when the crossing leaves the scan
   window: 259 of 1,782 rows (14.5 %) in one batch and 69 of 223 (30.9 %) in the other are not closed.
2. **Resonance-semantic labelling** — the first peak can drift to or across the scan boundary; flags
   distinguish "peaked", "closed", "usable" and "quarantined".
3. **Eight baselines** — persistence (copy the nearest available neighbour), PCHIP, linear, kernel
   ridge, quadratic ridge, Gaussian process, gradient boosting, MLP, each with five seeds.
4. **Six ablations** — peak semantics, refusal, quarantine, log transform, extrapolation limit,
   active sampling.
5. **OOD abstention** — proposals outside the measured (x, N1, N2) grid are refused rather than
   extrapolated.

### The solver-free oracle, and what it does not mean

`tasks/t7_scheduling.py` does **not** call a solver. The closed-loop campaign's own result cache is
shipped under `oracle/points/` and replayed as a lookup oracle; the task reports `n_solves: 0` and the
number of cache hits. If a design the campaign would have requested is not in the cache, the task
**refuses** — it does not extrapolate, substitute a surrogate, or silently drop the arm. So what is
reproduced here is the **analysis** of a past campaign, never a fresh solve, and the cache bounds
exactly which arms are replayable.

## Known facts a user must not mis-read

* **The split is duplicate-aware, not spacing-disjoint.** Its grouping variable is duplicate clusters
  (541 of 2,255 rows, 24 %). Exactly repeated design points cannot straddle the split (each geometry
  cell and continuous coordinate occurs once: 0 % exact-key overlap in every batch). But at the
  finer batch's grid step (0.01), **91 %** of held-out rows have a *training* neighbour one step away
  (87 % and 90 % in the two coarser batches, step 0.1). Interpolation leakage is therefore **not**
  removed, and no result may be quoted as if it were.
* **The verdict is split-realisation sensitive.** Replacing the split with a size-matched uniform
  random one is geometrically equivalent (adjacent-step fraction within 4 points) yet moves the median
  error of 9 of 63 cells of the finer batch by more than 10 %, in both directions. The negative
  "no method beats persistence" result reproduces under both rules (8 of 20 vs 7 of 20 decidable
  channel×batch cells), so it is not an artefact of the split rule — but individual cell numbers
  should not be read as stable.
* **`None` is never a pass** and no threshold in `config/thresholds.json` was adjusted after the fact.
* **Persistence is a hard baseline**: on the two formal targets nothing beats it.

## Provenance and licence

Every file's sha256 is in `MANIFEST.json`, together with the hashes of the upstream run artifacts the
package was cut from, and the sha256 of each vendored task script. `NOTE_on_license.md` records that the
licence choice is deliberately left to the authors.

`REPRODUCIBILITY.md` is the honest map of coverage: it lists, row by row, which of the paper's reported
numbers this package reproduces and which it cannot (the solver-side physics gates and the
multi-frequency reduced-order model), with the reason for each. Read it before quoting a number from
here.
