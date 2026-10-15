# V3.45 — Durable Evidence Snapshot Authority

## M18
`No promotion without Evidence Snapshot`.

La promotion non può più usare un semplice `evidence_valid=True` o un riferimento corrente all'evidence. Prima della promotion deve esistere un'autorità durevole `EVIDENCE_SNAPSHOT_AUTHORIZED` nell'EventStore.

L'autorità conserva immutabilmente:
- evidence IDs;
- metrics + metrics hash;
- gates;
- dependencies;
- strategy/model/feature/target/configuration/execution/code versions;
- artifact hashes;
- methodology;
- approvals;
- scope;
- snapshot content hash;
- promotion/bundle/model binding;
- dependency checkpoint e validity window.

La verifica della promotion controlla di nuovo il content hash, il binding al Promotion Bundle, gate/artifact/version/approval/scope e la dependency chain. Una invalidazione successiva al checkpoint rende la snapshot authority stale anche dopo revalidation.

Il controllo è applicato alla promotion contract, alla Champion/Challenger governance e ai percorsi deployment che consumano il Promotion Bundle. Il legacy promotion checker richiede anch'esso una snapshot authority durevole.
