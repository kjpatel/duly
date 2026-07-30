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

**Nothing in this repository is calibrated.** Fitting requires labeled `(raw_score, correct)` pairs, where `correct` was decided by a human — and those labels do not exist yet for any real extractor. The mechanism that produces them shipped in M3: the [review queue](../review/README.md) turns human corrections into exactly these pairs. What is still missing is *volume* — real reviewed traffic from a real extractor — and no amount of machinery substitutes for it. The tests fit on *synthetic* data with known miscalibration; they prove the math converges and the guarantees hold on data that satisfies the assumptions — nothing more. A calibration module that shipped pretending to be fitted would be the confident wrongness this project exists to eliminate, wearing a lab coat.

The conformal guarantee is also narrower than it sounds: it bounds the **marginal** probability of accepting an incorrect fact (≤ alpha, distribution-free, assuming exchangeability). It does **not** bound the error rate *among* accepted facts, and it breaks under drift — new templates, new extractor versions — which is why serialized params carry their sample count, fit date, and dataset reference.

**A boundary detail, if you ever copy a fitted threshold into a pack floor.** The two tests disagree at exactly one point. `ConformalCalibrator.accepts` abstains *at* the threshold — `score > threshold`, strict, because the guarantee's error event is `{s > threshold}` — while the kernel admits a fact *at* its floor: `score >= minConfidence`. So setting `minConfidence` to a fitted threshold does not reproduce the calibrator's behavior for a score landing exactly on it: the calibrator abstains, the kernel binds. The gap is one representable value wide and no pack derives its floor this way today, but a pack that starts to should account for the asymmetry rather than assume the two are the same test.

## How it connects

```
extraction adapters               this package                    kernel policy
raw scores + review labels  ───▶  fit / validate / serialize ───▶ conformal threshold into the
                                  recalibrate_fact           ───▶ pack's abstention policy;
                                                                  recalibrated facts supersede
                                                                  their raw originals in the store
```

Raw scores come in from extraction adapters; fitted, provenance-carrying params artifacts come out; conformal thresholds flow to rule-pack abstention policy (abstention is kernel policy, not fact data — spec D5); recalibrated facts re-enter the store as superseding facts (`duly_store` handles supersession on ingest).
