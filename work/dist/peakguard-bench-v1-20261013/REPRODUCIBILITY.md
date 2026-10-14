# Reproducibility: what this package does and does not reproduce

The paper reports numbers from three sources: the **label corpus and its evaluation** (this package),
the **solver-side physics gates** (COMSOL FE solves), and the **closed-loop design campaigns**. This file
states, for every reported quantity, whether a reader can reproduce it from this package alone. It is
written to be read *before* the numbers, because a benchmark that implies more coverage than it has is
worse than one that names its holes.

## 1. How to run it

```
python -m pip install -r requirements.txt
python run_benchmark.py --check-only   # seconds: is this copy intact?
python run_benchmark.py --check        # baselines + ablations + solution-identity self-test
python run_tasks.py --check            # the task suite, then a deep comparison against expected/
```

**Timings drift with machine load and are not a promise.** Across **3** recorded packaged full-chain runs on the authors' machine the baseline stage took **393-765 s** and the task suite **680-708 s** (full chain **1073-1474 s**, i.e. up to **24.6 minutes**). `m1_m2_m3` dominates the task suite (it refits eight methods for the random-split arm and recomputes the risk-coverage curves); the other five stages together finish in seconds to tens of seconds. That single stage measured **624-676 s** (10.4-11.3 minutes) across these runs, i.e. the same stage varied by 8% purely from concurrent load. So budget **25 minutes** for a full reproduction and do not treat any single figure here as a bound. No caching, subsampling or convergence-limit shortcut was taken to speed this up, because each would change the numbers.

`run_benchmark.py --check-only` does the fast checks only (per-file sha256 against `MANIFEST.json`, the
solution-identity self-test, and the integrity of the expected-value files) without fitting any model.
Use it to confirm you have an intact copy.

The expected values were not typed by hand: `expected/EXPECTED_OUTPUTS.json` is extracted from the frozen
baseline run, and `expected/EXPECTED_TASKS.json` is extracted from the frozen registered task results,
with timing/provenance keys stripped by an explicit, auditable policy recorded inside that file.

**Language, and exactly where the original text still is.** The internal pipeline wrote its free-text
fields (calibers, non-claims, per-cell notes) in Chinese. This package is an English artifact, so those
strings are rendered in English by one explicit table, `tasks/_text.py`, applied identically to the
produced outputs and to the expected values — only those string values change; no number, key name or
structure does. Everything a reviewer reads as **data** — expected values, task outputs, check messages,
the README, this file — is English. The original text remains in exactly four places, all listed here so
the claim is checkable rather than vague:

| where | what | why it is still there |
|---|---|---|
| `tasks/_text.py` | the rendering table itself (769 characters) | a whole-string table must hold the originals; this is what makes the rendering auditable rather than opaque |
| `bench.py`, `pchip_fitter.py` | comments in the vendored evaluation code (2,432 + 1,524 characters) | vendored verbatim from the authors' own implementation so that the numbers stay bit-comparable; the code paths are the frozen ones |
| `tasks/*.py` | comments in the ported task scripts (≈4,500 characters) | the ports were kept as close to the verified originals as possible; only the values a task *writes* were rendered |
| `oracle/points/*.json` | note fields inside the 94 frozen campaign payloads (376 characters) | these are frozen evidence, shipped byte-for-byte; rewriting them would break the cache digests the replay checks |

Nothing in that table names a person, a host or a path.

## 2. Reproduced here, with no solver and no COMSOL

| paper | quantity | command | how it is checked |
|---|---|---|---|
| §5 Data | rows per batch: 1,782 / 223 / 250 | `run_tasks.py --only label_validity` | exact counts |
| §6.1 | bandwidth not closed: **259 of 1,782** (14.5 %) and **69 of 223** (30.9 %) | same | exact counts |
| §6.3 | every per-seed per-cell median of the 8-method table (800 cells) | `run_benchmark.py --check` | relative tolerance 1e-6 |
| §6.3 | persistence median `0.007726751204325416` and 416 defined rows | same | exact anchors |
| §6.3 | all six ablations | same | tolerance 1e-6 |
| §6.3 | "no method beats persistence" in **8 of 20** decidable cells, and **7 of 20** under the size-matched random split | `run_tasks.py --only m1_m2_m3` | exact |
| §4.1, §S11 | the split groups **duplicate clusters** (541 of 2,255 rows = 24 %), 0 % exact-key overlap, and **87 / 91 / 90 %** of held-out rows have a training neighbour one grid step away | same | exact |
| §6.3 | split-realisation sensitivity: **9 of 63** C-batch cells move more than 10 % | same | exact |
| §6.3 | risk–coverage: the pre-registered score `s_i`, 700 cells, no cell reaches 2 % at coverage 0.85 | same | exact |
| §6.3 | cross-batch transfer gaps for the three arms (144 cells) | same | exact |
| §6.3 | T1/T2: peak-identity and bandwidth-closure classification accuracy per batch and seed | `run_tasks.py --only t1_t2` | exact |
| §6.2, §7 | refusal behaviour: accepted/refused counts and false-accept rate at the three registered tolerances | `run_tasks.py --only t5` | exact |
| §6.6 | the four-arm closed-loop table (best at k=5, simple regret), the five random seeds' spread, and the **96 %** out-of-domain proposal replay | `run_tasks.py --only t7_scheduling` | solver-free replay against the frozen oracle cache |

`solution identity` (§S13 of the supplement): `check_solution_identity.py` is a self-test on a synthetic
record; it is included because the rule it encodes decided which of our own readings were comparable.

**What the closed-loop replay is, exactly.** `tasks/t7_scheduling.py` ships the campaign's own result
cache under `oracle/points/` (94 evaluated designs, 0.25 MB — **not** the 101 MB model) and replays the
registered schedule through a **lookup oracle**: 165 calls, 165 cache hits, 94 distinct designs (the
campaign revisits designs), **`n_solves: 0`**. Two things are worth stating because they bound the claim:
the call schedule cannot be derived from the pre-registration alone (its `calls_per_seed` cannot express
that only some arms ran a full 25-call trace), so it is pinned by `tasks/ref_ledger.json`, a
designs-only projection that carries **no objective values** and whose absence makes the script refuse
rather than guess; and a missing cache entry makes the replay **refuse**, which was verified by deleting
a required point in a scratch copy and observing `replayable: false` / `missing_designs: [[0.45, 6, 9]]`.
What is reproduced is therefore the **analysis** of a past campaign — never a fresh solve, and the cache
bounds exactly which arms are replayable.

## 3. Declared here, but NOT reproducible from this package

| paper | quantity | why it is not here |
|---|---|---|
| §6.4 | S3 physics-consistency gates (7 passes / 2 failures, corrected to 8 / 1) | requires solving the 3-D piezoelectric–acoustic FE model and reading its fields; the model file is not distributed |
| §6.4 | S0 monopole limit consistency (9.0380e-04 at 0.25 MHz, 1.5230e-02 at 20 MHz) | the protocol is zero-solve, but it integrates fields from a stored solution of that same model |
| §6.4 | S1/S2/S5 local model and coverage protocol (0.69999 %, 0.95735 %, coverage 0.9259/0.9383) | requires held-out FE solutions |
| §6.4 | S4 mesh ladder and the twelve re-analysis values (0.6753 %, 1.5504 %, 1.3446/1.4300/1.4963 %) | a solver campaign over nine mesh levels |
| §6.5 | energy-closure residual (0.035–0.383 % across 5–35 MHz; the retired caliber at 6.177 %) | zero-solve post-processing, but on stored field solutions that are not distributed |
| §6.6 | multi-frequency ROM results (27.76 % / 32.19 %, k=120 plateau, the frequency-axis redesign at 26.46 %) | needs the frequency-domain field snapshots and the ROM fitting code, which are not part of this package |

The closed-loop campaign is the one solver-side experiment that **is** replayable here, because the
campaign's own result cache is shipped (see `oracle/`). It is replayed as a **lookup oracle**: the task
performs **zero solves**, and refuses rather than extrapolates when a requested design is not cached.

## 4. How to read the word "reproduce"

* **Exact** means the produced value equals the frozen reference within relative tolerance 1e-6, and the
  comparison is a **deep** one: structure, key names and values. A changed caliber, a dropped channel or
  an added field fails it — it is not a numeric-only check.
* Bit-for-bit agreement additionally requires the library versions pinned in `requirements.txt`; a
  different BLAS build can move the last bits, which is why the checker uses a tolerance and why the
  versions are recorded in `MANIFEST.json`.
* Nothing here is an experimental measurement, and nothing here licenses an engineering absolute value.

**Fields that are deliberately not compared, and why.** The expected file records every stripped key with
its reason (`removed_keys`, plus `strip_policy.per_output`). Three kinds are stripped globally: wall-clock
timings and timestamps; the upstream input inventory (`inputs`), whose path keys are rewritten to
package-relative form and whose digests therefore change; and the `prereg` block, which names a document
that is not distributed and so cannot be checked inside the package. One kind is stripped per output: for
the T7 replay, the registered artifact's own `kind` (the replay is a different artifact, and reporting the
registered name as its type would misdescribe it) and the three keys describing the **solve** extension
(`new_calls_in_extension`, `ledger_new_sha256`, `ledger_old_sha256`) — a solver-free replay makes no new
solves and reads no ledger. Every one of those keys is listed with its reason; none of them is a result.
Extra keys the ports add (for example `frozen_assertions_checked`) are reported as informational and do
not fail the comparison, since they are additions rather than divergences.

## 5. Limits of this package's own verification (stated, not hidden)

* Only the **authors' environment** has run the full pipeline. As of this release **no third party has
  run it**; the reproduction claim is a claim about the artifact, not about an independent run.
* The solution-identity checker's bundled record is **synthetic** and labelled as such.
* The package does not attempt to reproduce the paper's prose, only its numbers.
* The task suite depends on the baseline registry produced by `run_benchmark.py`; it fails closed if that
  file is absent rather than skipping stages.
* `m1_m2_m3` runs in **8.7–10.4 minutes** across four measured runs, so it **can exceed** a ten-minute
  budget on a loaded host; see section 1.
* The frozen pre-registrations are **not** distributed. Each task records the identity (file name and
  sha256) of the pre-registration it came from, but a reader cannot re-verify that digest from the
  package alone, and the package says so rather than implying otherwise.
