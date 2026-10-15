# V0.5 — Research / Model Lab

## Purpose
V0.5 creates a reproducible research pipeline around the V0.4 model contracts.

## Mandatory boundaries
- TRAIN → VALIDATION → OOS → FINAL_HOLDOUT remain temporally separated.
- FINAL_HOLDOUT cannot be consumed by tuning APIs.
- Every experiment belongs to a research family and is recorded before evaluation.
- Experiment fingerprints bind dataset, feature, target, model, split, seed, code and configuration.
- Adversarial evaluation is mandatory before candidate acceptance.
- Robustness is measured as degradation under named scenarios.
- RL remains EXPERIMENTAL ONLY.

## Deliberate exclusions
No promotion, live execution, portfolio optimization, or autonomous retraining is introduced here.
