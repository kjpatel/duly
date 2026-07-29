# duly calibration

The math for the `confidence.method` enum in the [grounded fact contract](../spec/grounded-facts.md) (D5): fit, apply, serialize, and validate the three calibration methods, plus the helper that rewrites a fact's confidence through a fitted calibrator.

| Module | What it provides |
|---|---|
| `temperature.py` | One-parameter logit rescaling, fitted by NLL minimization (golden-section; pure stdlib) |
| `platt.py` | Two-parameter logistic fit on the logit of raw scores (Newton + Armijo, Platt target smoothing, documented convergence criteria) |
| `conformal.py` | Split-conformal **abstention thresholds** with the finite-sample quantile correction `ceil((n+1)(1-alpha))/n` — this is what feeds a rule pack's abstention policy |
| `base.py` | The `Calibrator` protocol (`fit(pairs) -> params`, `apply(score, params) -> score`, `method_name`) and versioned params serialization with mandatory fit provenance |
| `metrics.py` | Validation harness: binned ECE, Brier score, and empirical-vs-promised conformal coverage, on held-out pairs |
| `facts.py` | `recalibrate_fact`: a fitted calibrator + a raw-scored GroundedFact → a new content-addressed fact that supersedes the original |

Everything is deterministic — no wall clock, no randomness. Fit timestamps are caller-supplied; same pairs in, same params out, byte for byte.

## What this deliberately does not claim

**Nothing in this repository is calibrated.** Fitting requires labeled `(raw_score, correct)` pairs, where `correct` was decided by a human — and those labels do not exist yet for any real extractor. They arrive later in M3, when the review queue turns human corrections into exactly these labels. The tests fit on *synthetic* data with known miscalibration; they prove the math converges and the guarantees hold on data that satisfies the assumptions — nothing more. A calibration module that shipped pretending to be fitted would be the confident wrongness this project exists to eliminate, wearing a lab coat.

The conformal guarantee is also narrower than it sounds: it bounds the **marginal** probability of accepting an incorrect fact (≤ alpha, distribution-free, assuming exchangeability). It does **not** bound the error rate *among* accepted facts, and it breaks under drift — new templates, new extractor versions — which is why serialized params carry their sample count, fit date, and dataset reference.

## How it connects

```
extraction adapters (M3)          this package                    kernel policy
raw scores + review labels  ───▶  fit / validate / serialize ───▶ conformal threshold into the
                                  recalibrate_fact           ───▶ pack's abstention policy;
                                                                  recalibrated facts supersede
                                                                  their raw originals in the store
```

Raw scores come in from extraction adapters; fitted, provenance-carrying params artifacts come out; conformal thresholds flow to rule-pack abstention policy (abstention is kernel policy, not fact data — spec D5); recalibrated facts re-enter the store as superseding facts (`duly_store` handles supersession on ingest).
