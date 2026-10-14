# PeakGuard — Supplementary Material (DAC 2027 submission)

> **Double-blind**: this supplement carries no authors, affiliations, acknowledgements or repository
> paths. Numbers are identical to those in the body; the body keeps every headline figure and this file
> holds the per-cell, per-variant and historical detail that the six-page limit cannot carry.
> Figures and tables are numbered `S*` and are referenced from the body as "§S…".

## S1. Cross-cell results, per variant (multi-frequency ROM)

Nine cells per family (3 held-out *x* × 3 held-out frequencies). Key-region relative L2 (51 of 1369
frozen probe points); the criterion is 2 % key region / 5 % whole domain.

**S1.1 Stage-2 grid** (13 frequencies; held-out frequencies 11.4, 12.0, 12.6 MHz — *near the peak*).

| family | variant | key max | key median | global max | (first-reported figure) |
|---|---|---:|---:|---:|---:|
| N₁ = 4 | `linear` (registered) | **27.76 %** | 18.90 % | 27.77 % | 27.08 % |
| N₁ = 4 | `cubic` | **18.87 %** | 8.59 % | 18.68 % | 18.69 % |
| N₁ = 4 | `rbf` (thin-plate) | **227.43 %** | 37.69 % | 236.10 % | 37.69 % |
| N₁ = 4 | `linear_normf` | **19.88 %** | 15.57 % | 20.55 % | 18.90 % |
| N₁ = 7 | `linear` (registered) | **32.19 %** | 27.63 % | 31.68 % | 30.87 % |
| N₁ = 7 | `cubic` | **19.59 %** | 11.02 % | 19.59 % | 19.40 % |
| N₁ = 7 | `rbf` (thin-plate) | **356.57 %** | 54.21 % | 362.72 % | 54.21 % |
| N₁ = 7 | `linear_normf` | **32.19 %** | 15.67 % | 31.68 % | 30.87 % |

Reduced-basis sensitivity (nine cells, `linear` interpolation): k = 2 / 4 / 8 / 16 / 48 / 120 gives
key-region maxima 33.2 / **27.8** / 27.6 / 27.6 / 27.6 / **27.6 %** for N₁ = 4 and 33.5 / **32.2** /
31.9 / 31.9 / 31.8 / **31.8 %** for N₁ = 7, while the training reconstruction falls to 0.000 %.
Post-hoc axis decomposition at k = 16: frequency axis 34.8 % versus geometry axis 14.5 % (N₁ = 4);
geometry axis 23.6 % versus frequency axis 11.4 % (N₁ = 7).

**S1.2 Stage-3 grid** (12 training frequencies chosen to cover the resonance flanks: 5.0, 5.95, 7.07,
8.41, 10.0, 11.4, 11.89, 12.0, 12.6, 14.14, 16.82, 20.0 MHz; **held-out frequencies on the flanks**:
6.6, 9.2, 15.5 MHz; 360 additional solves, zero failures, 102 min).

| family | variant | key max | key median | global max | training control | per-mode fit |
|---|---|---:|---:|---:|---:|---:|
| N₁ = 4 | `linear` | 36.51 % | 16.62 % | 40.28 % | 4.39 % | — |
| N₁ = 4 | `cubic` | **26.46 %** | 14.49 % | 30.04 % | 4.39 % | — |
| N₁ = 4 | single-pole resonance | 72.63 % | 20.12 % | 103.47 % | **68.56 %** | **27.22 %** |
| N₁ = 7 | `linear` | 42.46 % | 25.07 % | 42.60 % | 5.35 % | — |
| N₁ = 7 | `cubic` | 44.84 % | 15.51 % | 44.34 % | 5.35 % | — |
| N₁ = 7 | single-pole resonance | 107.43 % | 18.88 % | 148.02 % | **76.13 %** | **23.98 %** |

*The two grids are not equally hard*: stage 2 held out near-peak frequencies, stage 3 holds out flank
frequencies (deliberately), so the two sets of numbers are not a like-for-like comparison; what is
comparable is that no variant approaches 2 % on either grid.

**S1.3 The frequency-grid defect in the first analysis run.** The registration stored the held-out
frequencies as `[11.399999999999999, 12, 12.600000000000001]` while the field dictionary is keyed by the
exact values `[11.4, 12.0, 12.6]`; an exact-equality cell filter therefore dropped the two columns
`11.4` and `12.6` and the first-reported figures were computed on `f = 12.0` alone — 3 of 9 cells.
The defect is in the analysis script (not in the data, the model or any measured quantity). It was found
by reproducing the registered `linear` value with an independent implementation and noticing that the
median matched exactly while the maximum did not. Corrected values are in §S1.1; the affected artifacts
are retained unchanged and the corrected computation is archived separately.

**S1.4 Coefficient-shape diagnosis that motivated the re-design.** For N₁ = 4, x = 0.65, mode 0, the
coefficient magnitude peaks at 11.1 MHz (peak-to-trough 9.9) and the unwrapped phase swings 2.8 rad
between 6.3 and 11.1 MHz, while the stage-2 grid contains **no** point in 6.3–11.1 or 12.9–18.0 MHz
(eleven of thirteen points lie inside 11.1–12.9 MHz).

## S2. S3 physics-consistency checks

| check | registered metric | criterion | registered | corrected caliber |
|---|---:|---:|:--:|:--:|
| closed-surface charge conservation | 8.151e-04 | 0.5 % | pass | pass |
| sound-hard weak-form residual (integrated) | 1.996e-04 | 1 % | pass | pass |
| energy loss / radiation separation | 6.177e-02 | 0.5 % | **fail** | **fail** |
| current conservation, circuit vs field flux | 1.112e-01 | 0.5 % | **fail** | **pass** |
| circuit vs terminal ODE charge rate | 6.691e-16 | 0.5 % | pass | pass (structurally non-independent) |
| potential, driven electrode | 3.331e-16 | 1 % | pass | pass |
| potential, grounded electrode | 0.0 | 1 % | pass | pass |
| symmetry about y = 0 | 3.326e-04 | 1 % | pass | pass |
| symmetry about x = 0 | 7.449e-05 | 1 % | pass | pass |

Corrected caliber for the current check: closed-surface flux with the physics normal
`es.nx/ny/nz` over the 28 electrode faces, denominator the sum of the four electrode current
magnitudes. Six frequencies on one carrier give 6.469e-04, 6.483e-04, 6.538e-04, 6.763e-04, 8.625e-04,
1.032e-03; a second carrier gives 8.168e-04. The post-processing normal `nX/nY/nZ` instead gives
≈0.999 on the same surface (2.16 on the first carrier), which is why it must not be used for
closed-surface judges.

## S3. S4 mesh ladder

Nine levels (λ/5 … λ/11 plus two combined levels), 72 ordered pairs, one machine and one batch; frozen
point set with 1369 common finite points and 51 key-region points.
Key-region maximum **0.6753 %** (worst pair: finest acoustic level over the finest combined level) and
whole-domain maximum **1.5504 %** (reference only). Richardson estimates of the remaining
`h → 0` residual under three ratio choices: 1.3446 % (assumed ratio 0.78), 1.4300 % (whole-ladder mean
0.7904), 1.4963 % (most recent step 0.7978). Regression targets reproduce the earlier six-level
(0.013847) and eight-level (0.015152) maxima. Adjacent acoustic-axis differences fall monotonically
(1.2318, 0.9440, 0.7464, 0.5748, 0.4754, 0.3792 %) with successive ratios 0.766–0.827. An older ladder
quoted in an earlier ruling (key region 1.5191 %, whole domain 2.4161 %) belongs to a different level
set and must be reported separately.

## S4. Strict mesh convergence (L1) history

The recorded strict-caliber check judges `passed = false`: the target quantity differs by up to
**2.235 %** between the coarser pair against a 1 % criterion, while the finer pair is already inside
1 %. The next finer level (×0.5, 342,635 elements, 900,182 degrees of freedom) failed on local memory
(18.55 GB physical, 19.59 GB virtual), and a segregated multi-block route was measured to be infeasible
through the available Java API. A four-level run on a 96-core server did solve the ×0.5 level (peak
54.08 GB physical) and reports a monotone ladder with every adjacent difference inside 1 % for the
finest pair; the pre-registered strict rule nevertheless still fails because the coarsest pair lies
outside the asymptotic range. The finest-pair caliber approved by the human reviewer on 2026-10-10
passes, and both readings are reported. The library's single passing L1 record is a four-element
heat-conduction toy model whose own caveat states that it cannot substitute for a non-linear
multi-physics convergence study.

## S5. Field-level gate detail

Over the frozen snapshot set the field-level gate is 0/7 folds at the key-region 2 % object (maximum
0.858054, model `norm_shape_pchip`), 0/7 at the 3 % engineering object (maximum 0.761833, authoritative
model `raw_linear`) and 2/7 at the global 5 % object (maximum 0.808890). On the engineering object two
models have bit-identical maxima but different fold-pass counts (`raw_linear` 0/7 versus `raw_pchip`
3/7); the authoritative artifact names `raw_linear`, and attributing 3/7 to "the best model" would be a
silent model swap that flatters the result. A group of 405 combinations stays unexpanded.

Local *x*-family models (20 MHz, five held-out continuous values): a shape-preserving local model
("model B") meets all three thresholds — key region 0.69999 % with 1.09097 % whole domain for N₁ = 4,
0.95735 % / 1.13266 % for N₁ = 7, engineering maximum 0.739 % — while a raw-POD variant fails the key
region at 2.126 %. Four caveats travel with that statement: the independence of the two routes is
self-declared rather than enforced; the solver-specification `model_id` field is empty; the local model
class has no save/load API, so "reproduction" means re-running a script rather than loading a frozen
model; and the coverage protocol that yields 0.9259 / 0.9383 was promoted to the official caliber by a
human ruling on 2026-10-10, while the earlier five-point protocol remains recorded as inconclusive.

## S6. Energy-closure probes (zero-solve post-processing)

| candidate cause | measurement | verdict |
|---|---|---|
| port-voltage convention | electrode mean potentials: drive −1.000000 V, ground 0, floating terminal ≤ 7.7 µV; including it changes `P_in` by +0.053 % | refuted |
| current post-expression omits piezoelectric coupling | `∫es.JZ dA ≡ jω·∫es.Dz dA` on all four electrode sets, agreement to all printed digits | refuted |
| acoustic power uses a plane-wave approximation | the model's `Ptot` equals the exact flux `Im(K)/(2ωρ)`, `K = ∫ p·conj(∇p·n) dA`, at all six frequencies | refuted |
| integration surface chosen badly | two disjoint surfaces agree to 1.8 % at 20 MHz but **both exceed** the electrical input (3.996822e-06 W outer hemisphere, 3.924776e-06 W fluid–structure interface, versus 3.734359e-06 W) | refuted |
| the residual is a fixed systematic offset | a second geometry at the same 20 MHz gives +1.60 % (coupling surface) and −0.34 % (outer hemisphere) instead of −4.12 % / −5.82 %; within one geometry 5–15 MHz gives +3.14…+3.97 % and 25–35 MHz −1.52…−0.82 % | refuted |
| sound-hard residual holds only for one test function | extended to φ ∈ {1, x, y}: residuals ≤ 0.045 % (φ = z is degenerate) | passes |
| the residual is unconverged discretisation | solid-side refinement ×1 → ×0.75 → ×0.5: gap −4.852 % → −4.384 % → **−4.121 %** (decrement ratio 0.562 ⇒ extrapolated limit ≈ **−3.8 %**); acoustic-mesh refinement λ/5 → λ/7 at ×0.5 moves it by 0.0011 pp | refuted |

Per-frequency power balance on a second carrier (port power versus coupling-surface and outer-hemisphere
flux, in µW): 5 MHz 10.120 / 9.811 / 9.823; 10 MHz 2.532 / 2.446 / 2.458; 15 MHz 1.571 / 1.511 / 1.527;
20 MHz 2.184 / 2.150 / 2.192; 25 MHz 49.915 / 50.684 / 52.037; 30 MHz 10.370 / 10.472 / 10.850;
35 MHz 8.305 / 8.373 / 8.773. The two carriers' powers agree to ≤0.81 %, and the second carrier's port
and acoustic powers match the ×0.5 solid-side refinement to 1.1e-10 relative.

## S7. Closed-loop design-space exploration, full table

Pool of 1080 candidate designs, five shared initial points, four arms, 105 high-fidelity
single-frequency evaluations, 123 minutes, 2 % failure rate (pre-registered inconclusive threshold 20 %).

| arm | successful calls | best objective (W/V²) | simple regret | best at k = 5 | top-10 % hit rate |
|---|---:|---:|---:|---:|---:|
| random (5 seeds × 5) | 25 | 2.1756e-05 | 18.8 % | 8.409e-06 (median) | 0.0 % |
| greedy | 25 | 2.2807e-05 | 14.9 % | 4.863e-06 | 4.0 % |
| GP + expected improvement | 25 | **2.6786e-05** | **0.00 %** | **2.640e-05** | **24.0 %** |
| GP + EI with applicability gate | 23 | 2.6126e-05 | 2.46 % | 2.510e-05 | 17.4 % |

An independently written script re-derived all of the above from the append-only ledger: 34 checks, 0
mismatches at 1e-12, nine repeated design evaluations bit-identical, and the secondary-surface caliber
agreeing to 1.6–2.1 % across the campaign.

## S8. Label and bandwidth calibers

Closure and quality-factor counts come from the source table's own columns (`bandwidth_closed`,
`q_gate_pass` with interval 2.5–3.5), whose applicability column equals the closed subset exactly — not
from the downstream `peak_closed` flag, which would give different denominators (1,612 and 161 closed
rows respectively). Two independent bandwidth audits must not be merged: fitted versus the batch's own
`from_points` estimate gives median 20.3 %, p90 27.2 %, within-10 % rate 11.0 %, Spearman 0.9888
(n = 91, rank-robust); local extraction versus the exported table gives median 33.5 %, p90 88.1 %,
within-10 % rate 21.9 % (n = 292) with quality-factor correlation 0.2226 (not rank-robust), and the
exported table is retained as the primary caliber.

## S9. Acoustic-side net-flux caliber and per-face orientation

**Criterion.** For a lossless, source-free fluid domain the divergence theorem gives
`∮_{∂Ω} I·n_outward dA = 0`, so the net outward flux over the closed fluid boundary must vanish. This
is circuit-free and is the measurable form of "two enclosing closed surfaces agree": with only one
provably closed boundary in this mesh, the net flux is the only available form of the same statement.

**There is exactly one closed boundary.** Enumerating the boundary of all 65,535 domain subsets
(closure test: every edge of the set belongs to exactly two faces of the set, using measured
`boundary_edges`) yields **one** closed set: `∂(domain 1)`, the acoustic-domain boundary, **17 faces**,
with **32/32** edges shared by exactly two faces. The older probe's `HEMI` (4 faces) and `ASI`
(12 faces) are each **not** closed (4 open edges each, on the same contact ring); they are the two
**complementary halves** of `∂(domain 1)`.

**Orientation is measured, not assumed.** With the measured fluid-domain centroid
`x_c = (0, 0, −37.499999e-06) m` and volume `V = 2.09439355675e-12 m³` (exactly (2/3)π(100 µm)³, so the
fluid is the z < 0 hemisphere), the per-face index `ρ_i = σ_i /(A_i |c_i − x_c|)` with
`σ_i = ∫ n·(x − x_c) dA` gives **+1.1315** (dome) and **+1.0** (ring) — outward — and
**−0.7218 / −0.7589 / −0.8807** for the twelve source-patch faces — inward. The translated divergence
identity `∮ n·(x − x_c) dA = 3V` decides this uniquely:

| orientation hypothesis | residual against 3V |
|---|---:|
| literal (no flip) | 6.61 % |
| flip outer patch | 200.0 % |
| **flip source patch** | **9.34e-08** |

**Two tempting identities have no discriminating power here** and must not be used: `∮ n dA = 0`
(because `|∫_outer n dA| / |∫_source n dA| = 0.99999716` — the dome's πR² minus the ring's π(R²−r_in²)
equals the ASI disk's πr_in², so flipping either patch zeroes it) and the untranslated `F = x` form
(because `∫_source n·x dA = 0` exactly). Only the translated form works.

**Measured net outward flux / outer flux**, at eight independent points (four solution tags carry two
independent solutions: `sol1 ≡ sol2 ≡ sol3` are bit-identical):

| f (MHz) | 5 | 10 | 15 | 20 | 25 | 30 | 35 | (2nd geometry) 20 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| net / outer | 0.0769 % | 0.4660 % | 1.0722 % | 1.7499 % | 2.4127 % | 3.4035 % | 4.4913 % | 1.7286 % |

**It converges with the acoustic mesh.** Three same-machine levels differing **only** in `ftet1` — λ/5 (342,886 elements), λ/7 (424,591) and λ/9 (592,560; `ftri1` and the solid scale held fixed; all three re-solved from the same source model, hash-verified before each run) — give at 20 MHz **1.770575 % → 0.953987 % → 0.563150 %**. A three-point log-log fit `resid = C·h^p` gives **p = 1.9428, C = 1.2804e+08 (h in m), R² = 0.9987350**; the local exponents are 1.8379 (λ/5→λ/7) and 2.0974 (λ/7→λ/9), and the two-point ratio **0.5388** is consistent with the **0.5102** expected from second order but is superseded by the fit. **λ/9 is still above the 0.5 % criterion**, so the criterion is not met at this design point with 592,560 elements.

Required reduction in `h` to reach 0.5 %, from the fixed `p = 2` fit (`(resid(f)/0.5 %)^(1/2)`):

| f (MHz) | 15 | 20 | 25 | 30 | 35 |
|---:|---:|---:|---:|---:|---:|
| resid | 1.072166 % | 1.770575 % | 2.412732 % | 3.403465 % | 4.491323 % |
| **h reduction** | **1.4644×** | **1.8818×** | **2.1967×** | **2.6090×** | **2.9971×** |

**A fourth level was measured.** λ/11 (862,410 elements; same design point, same caliber, `ftet1` the only change) gives **0.38624819841137986 %** under the 16-face caliber and **0.36529723432485256 %** under the 17-face caliber — **both inside 0.5 %**, so the 20 MHz point meets the criterion at this resolution. The three-point fit above is unchanged (bit-identical); adding this level gives a four-point fit **p = 1.9441755672118854, C = 130201241.90139253, R² = 0.9991358812484448**, and the local exponent from λ/9 to λ/11 is **1.8790302127548892**.

⚠️ **The `p = 2` column above is optimistic.** At λ/11 the fixed-`p = 2` fit predicts **0.370543 %** while the measurement is **0.386248 %**, i.e. **4.07 % higher** (and 0.1357 % below the three-point fitted curve, whose prediction is 0.386772 %). Because the measured exponent is slightly below 2, the four reductions in the table should be read as **lower bounds**; with `p = 1.9428` the same targets need somewhat smaller `h`.

⚠️ **Only the 20 MHz row shares the fit's caliber and mesh.** The other four residuals are the *17-face* caliber on the **same carrier but a different mesh**: they come from an older solution of that model file whose degrees of freedom are **359,711**, whereas the carrier's current mesh solves to **900,431**. Re-measuring the band on the current mesh (same carrier, `ftet1` = λ/5, 17-face caliber, orientation re-derived per face) gives **0.0567 % (5 MHz), 0.4075 % (10), 0.9750 % (15), 1.7286 % (20), 2.5965 % (25), 3.6645 % (30), 4.9503 % (35)**. The 20 MHz entry is verified from both directions: at the 16-face caliber **1.770575 %** against the independently recorded 1.770575 % (relative difference **3.9e-10**), and at the 17-face caliber 1.7286 %, matching the carrier's current-mesh solution. A single model file can therefore contain solutions computed on **different meshes**, so solutions must be compared by degrees of freedom, not by file name. Nor is the 16-face caliber used for the fit identical to the 17-face criterion of the main text (the ring face was not integrated at λ/5 and λ/7); the λ/9 value under the 17-face caliber is **0.539029 %**.

**The band was then closed.** Choosing, per frequency, the mesh the same rule requires (`n = ceil(1.10·n_req(f))`) gives the 17-face residuals below; the 5 and 10 MHz points enter at λ/9 from the calibration above.

| f (MHz) | 5 | 10 | 15 | 20 | 25 | 30 | 35 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| criterion mesh | λ/9 | λ/9 | λ/11 | λ/11 | λ/13 | λ/16 | λ/18 |
| 17-face resid | **0.0346 %** | **0.1368 %** | **0.2065 %** | **0.3653 %** | **0.3775 %** | **0.3537 %** | **0.3826 %** |

All seven are inside the inherited τ = 0.5 %. Three constraints travel with this. (i) **The upper-band margin follows from the rule, not from a comfortable measurement**: the 1.10 factor on `n` targets ≈ τ/1.21 ≈ 0.413 %, and the measured 0.354–0.383 % sit exactly there, so the margin is about 1.3×; against a 0.3 % criterion most of the upper band would fail. (ii) **Two operational deviations and two infrastructure aborts** are declared and travel with the numbers: the pre-registered memory gate was overridden to `-np` = 8 on the basis of measured memory scaling, the single-mesh plan was replaced by per-frequency meshes, and the finest attempt (λ/19, DOF 5.13e6) failed twice — once aborted for slowness, once after the direct solver went out-of-core and returned no usable reading. **There is no λ/19 measurement at 35 MHz**; its criterion mesh is λ/18. (iii) **This is a single-axis (`ftet1`) statement** — the refinement selection set is the fluid domain only, and `ftri1` and the solid side are untouched — so it is neither whole-model mesh convergence nor a Richardson error bound. Cross-frequency residuals must not be compared with one another, since each frequency uses its own mesh; the criterion is per-frequency.

**No dissipation path exists in the model settings.** `alpha1 = alpha2 = alpha3 = 0`;
`Im(∫ c dV) = Im(∫ ρ dV) = Im(∫ k dV) = 0` (measured mean c = 1481.44 m/s, ρ = 998.202 kg/m³); no
PML/absorbing layer/thermoviscous feature in the fluid domain; no impedance or absorbing boundary on
any of the 17 fluid faces; zero hits for loss keywords across all 26 features and 4 interfaces; the
only couplings are `asb1` (which sits exactly on the twelve source faces) and `pze1`; the fluid material
carries no attenuation property.

**What this does and does not settle.** The residual is a discretisation error of the acoustic mesh —
so closing the item requires **mesh refinement**, not a model change. It does **not** settle whether any
solver-level equivalent loss exists, the scan having covered model settings only; and the
frequency-scaling exponent alone cannot separate the two, which is why the mesh pair above is used
instead. Under the inherited 0.5 % criterion the item **fails** at 15–35 MHz.

## S10. Field-level ROM: representation families and the obstruction

**What was tried.** Eight representation families, all on the same frozen 1,373-point set, the same
held-out design (3 unseen x × 3 unseen f, thresholds 2 % key region / 5 % global) and with every
selection made on training cells only: (1) global POD coefficients with linear/cubic/rbf interpolation;
(2) key-region-weighted POD; (3) multi-pole vector fitting; (4) phase-explicit resonance fitting;
(5) a small MLP on POD coefficients; (6) implicit coordinate networks (two versions); (7) a physics
basis of outgoing spherical waves `h_l^(2)(kr)·Y_lm` with interpolated modal amplitudes; (8) factorised
models `p(x,f) ≈ Φ(r;f)·α(x,f)` at x-rank 1…12.

**Medians improve; maxima do not.**

| representation | key region, median | key region, max |
|---|---:|---:|
| global POD, cubic (12 x-nodes) | 13.4 % | 26.5 % |
| global POD, cubic (32 x-nodes) | **0.94 %** | 15.6 % |
| factorised, x-rank 3 (32 x-nodes) | **1.05 %** | 17.7 % |
| physics basis + amplitude interpolation | 4.98 % | 24.3 % |
| implicit coordinate network | 5.8 % | 76.4 % |

(second family: 14.1 % → 1.13 % for POD, max 18.3 %.)

**The maximum is always the same cell.** For every representation and every x-rank, the worst held-out
cell is `x = 0.63, f = 9.2 MHz`; the next two are `x = 0.93, f = 6.6` (7.5 %) and `x = 0.93, f = 9.2`
(5.3 %), and all six remaining cells are ≤ 5.3 %. Raising the factorised x-rank from 1 to 12 moves the
median from 11.8 % to 1.1 % but the maximum only from 20.2 % to 17.7 %. The maximum is likewise
insensitive to x-sampling density (12 → 32 nodes) and to the representation itself.

**The obstruction is not the data.** The held-out fields at `x = 0.63` and `x = 0.93` were re-solved on
the remote node and compared with the recorded ones: `K` relative differences are 0.0 (two cases) and
≤ 5.5e-11, `p_max` relative differences are 0.0, and the aligned field differs by 1e-13…2e-11 in the key
region — floating-point round-off. The validation data is correct to machine precision.

**It is not a spacing threshold either.** A leave-one-out scan over the 32 training x-nodes (holding out
one x, keeping all 21 training frequencies) finds **no** monotone rule in the distance to the nearest
remaining node: at the same 0.023 spacing the error ranges from **1.12 %** (`x = 0.863`) to **35.70 %**
(`x = 0.200`), and the worst case overall is `x = 0.269` at **60.0 %** for the second family. The hard
regions are the low-x band (≤ 0.29) and `x ≈ 0.46 / 0.59 / 0.65`; the smooth band is 0.73–0.91.

**Consequence for a declared domain.** Because no spacing threshold exists, a certified domain cannot be
stated as "x within δ". An explicit interval list, pre-registered with the rule "only adjacent measured
nodes, never extrapolated", leaves a cross-family, cross-rank common band of a single narrow interval,
**x ∈ [0.78, 0.886]**. In the frequency direction the same rule yields an **empty** set: the training
frequency grid contains gaps of 1.34/1.59 MHz (7.07→8.41→10) and 2.68 MHz (14.14→16.82) across which a
whole frequency plane cannot be reconstructed to 2 %. (The lowest frequency, 5 MHz, is a grid boundary,
so its leave-one-out value of ≈1400 % is an extrapolation artefact and is not read as an interpolation
error.) The three held-out frequencies (6.6, 9.2, 15.5 MHz) all sit in **small** gaps, which is why they
are reconstructible while the large-gap nodes are not.

**What was not done.** No domain-densification campaign was run (an estimate based on the measured
smoothness scale puts a full-domain 2 % maximum at roughly 300–400 x-nodes, ≈20–60 h, and this is an
extrapolation, not a measurement), and no operator-learning architecture was trained.


## S11. What the split actually groups, and how much the verdict moves

The registered split artifact groups **duplicate clusters**, not geometry families: near-duplicate rows
(541 of 2,255, 24 %; exact-key, rounded-key and last-place-unit duplicates) are kept on one side. Because
every (geometry cell, continuous-coordinate) combination occurs exactly once in the corpus, contamination
through exactly repeated design points is structurally zero — the *strict* leakage measure is 0 % for
**every** batch and both split rules. What is *not* removed is leakage along the continuous axis: a
held-out row can have a training neighbour one grid step away. Measured, relative to each batch's own grid
step (0.1 in the two coarser batches, 0.01 in batch C):

| batch | x grid step | exact-key overlap | adjacent-step train neighbour, registered / random |
|---|---:|---:|---:|
| A | 0.100 | 0 % | 87.3 % / 83.1 % |
| C | 0.010 | 0 % | 91.1 % / 92.2 % |
| V2 | 0.100 | 0 % | 89.7 % / 89.0 % |

**Counterfactual split.** We rebuilt the split as a uniform random assignment per batch and per seed,
holding the per-batch training/holdout sizes, the code, the hyper-parameters, the metric and the row set
fixed, so that *only which rows are held out* changes. The two arms are geometrically equivalent (the
adjacent-step fraction differs by at most 4 points, above), and the per-cell comparison is:

| batch | cells | random improves >10 % | random worsens >10 % | median ratio | across-seed s.d., registered / random |
|---|---:|---:|---:|---:|---:|
| A | 63 | 14 | 6 | 0.979 | 0.0038 / 0.0042 |
| C | 63 | 5 | 4 | 0.992 | 0.0010 / 0.0010 |
| V2 | 31 | 10 | 7 | 0.963 | 0.0169 / 0.0192 |

The movement is two-sided and the across-seed spread is the same size in both arms, so the differences are
**split-realization noise, not an effect of the grouping rule**. This matters for how the negative
persistence result is read: it is *not* an artefact of having chosen a grouped split, because the
size-matched random split reproduces it — 8 of the 20 decidable channel×batch cells admit no method that
beats persistence under the registered split and 7 of 20 under the random one (three channels in each of A
and C, two in V2, under the registered split). Conversely, no result in this paper may be read as
"x-adjacency leakage was excluded": it was not, and the batch-C fraction above is the honest measure of what
the split does and does not remove. The full per-cell table, the split-reproduction check (all fifteen
per-batch/per-seed sizes reproduce the registered artifact exactly) and the random assignment's fixed
generator recipe are recorded in the internal evidence companion.


## S12. Benchmark task specification

The benchmark is seven tasks over the frozen corpus of §4.1 and the split of §S11. Each task names its
inputs, its primary metric, its refusal rule and where its evidence appears. Every metric is reported per
batch and per channel; nothing is pooled and no weighted total is computed.

| # | task | inputs | primary metric | refusal rule | evidence |
|---|---|---|---|---|---|
| T1 | first-peak identity | (x, N1, N2) | accuracy over the four peak states, per state | abstain when the state is right-censored or truncated | §6.1 |
| T2 | bandwidth closure | (x, N1, N2) | accuracy of `bandwidth_closed`, with the caliber named | abstain when the extraction caliber is undefined | §6.1, §6.2 |
| T3 | conditional regression on the two formal targets | (x, N1, N2) | median relative error with the count of defined rows, plus `lift_paired` against persistence | abstain outside the measured grid | §6.3 |
| T4 | split comparison | (x, N1, N2) with the frozen assignment | per-cell median-error ratio between two split rules, reported with the adjacent-step leakage fraction | not applicable (both arms are evaluated) | §S11 |
| T5 | refusal behaviour | a proposal set | accepted and refused counts with reasons, and the false-accept rate at three tolerances | refuse when the applicability test fails | §6.2, §6.6 |
| T6 | cross-batch transfer | train batch → test batch | median relative error, its difference from the within-batch reference, and the acceptance fraction | refuse outside the training batch's measured range | §S11 |
| T7 | closed-loop scheduling | a budget of oracle calls | simple regret at k = 5 calls, and the fraction of un-gated proposals outside the supported domain | refuse un-gated proposals | §6.6 |

**What the released package covers.** The package of §6.3 ships the corpus, the frozen split, the
thresholds and a reference implementation that reproduces the regression and ablation parts of T3 and the
refusal counting of T5 by one command; T4 is reproduced by the counterfactual split described in §S11,
whose generator recipe is fixed and recorded; the full per-arm table behind T7 is in §S7. Nothing in the
package asserts an engineering absolute value, and no threshold in it was adjusted after any run.

**What is deliberately not claimed.** That these seven tasks exhaust the failure modes of surrogate
modelling for resonant design; that the corpus is representative of PMUT design, of RF filters or of
analog circuits at large; or that any task's metric is comparable across batches. The generality claim is
about the *questions*, not about the numbers: they recur wherever a resonant design space is swept with a
full-wave solver.
