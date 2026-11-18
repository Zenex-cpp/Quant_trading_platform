# M21 remediation — source-bound uncertainty and calibration gates

**Status: `TESTED`; not `VERIFIED` or production-ready.**

## Implemented

- The method registry now declares source, definition, bounds, threshold, action, monitoring and production eligibility for the signed-model-declared measure, normalized Bernoulli entropy, ensemble dispersion and the `CONSERVATIVE_LINEAR/1` risk mapping. Entropy and ensemble dispersion remain experimental.
- Signed model predictions carry their artifact hash and uncertainty method/source identity. A source-bound assessment binds the hash, prediction ID, model identity, uncertainty value, calibration state and prediction TTL into a recomputable fingerprint.
- A signed manifest's `calibration_state` is metadata only. Without a separately computed `CalibrationReport`, the runtime assessment is `UNKNOWN` and receives the 0.25 risk-factor cap. A supplied report binds its fingerprint, current/reference source IDs, sample sizes, scores, drift and threshold-based state into the assessment fingerprint; invalid or inconsistent report metadata is rejected.
- Live `RuntimeAuthority` rejects scalar-only uncertainty. It requires the model output evidence component to contain both artifact hash and assessment fingerprint and checks the assessment is valid and fresh.
- The same assessment is carried through execution routing and one-shot capabilities, persisted/replayed in the durable risk-decision ledger, and revalidated at the final dispatch gate. Changed, missing, unbound or expired evidence fails closed.
- `UNKNOWN` and `POOR` calibration cap the uncertainty risk factor at 0.25; `ACCEPTABLE` caps it at 0.50. `CALIBRATED` uses the registered monotone mapping.
- Calibration reports Brier score, ten-bin ECE, per-bin reliability and drift defined as the maximum absolute change in Brier or ECE versus a distinct reference window. Report validation checks sample counts, source separation, metric ranges, the recorded drift and state against declared thresholds. Both windows require separate source IDs and at least 30 samples by default. Missing report/reference/source or insufficient samples returns `UNKNOWN`.
- The V4.29 matrix, fixed runner and CI workflow include M21.
- Current focused M21/model/calibration/M22/M23/durable regression: **90 passed**. The mandatory full V4.29 runner on package 3.61.21 passed with **1,337 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; `.audit/V429_M21_FINAL3_20261112.json` records `READY_FOR_MILESTONE`, `allowed=true`, pipeline PASS, no blockers, M21 included and 161 contract-input hashes.

## Remaining evidence

- No labeled real-market prediction/outcome dataset or independent calibration window is present in the project. Generic thresholds are not calibrated for any venue, instrument, timeframe, regime, latency or execution assumption.
- The report fingerprint protects content integrity within the runtime decision chain; it is not a digital signature and does not authenticate the upstream dataset or the report producer.
- Multiplier ON/OFF ablation, broader sensitivity analysis, and an independent review remain required. No production evidence supports the declared uncertainty values in the model artifacts.
- The model-output evidence component in local fixtures and its verification status are synthetic inputs. A trusted independent signer/trust root and production inference integration remain open.

M21 therefore remains `TESTED`. `external_evidence=false`, `production_ready=false` and `activation_flag=NOT_SET` remain in force.
