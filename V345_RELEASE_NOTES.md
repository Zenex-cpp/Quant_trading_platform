# V3.45 Release Notes

## M18 — No promotion without Evidence Snapshot

V3.45 introduce una `EvidenceSnapshotAuthorityLedger` durevole. La promotion non può attraversare il control plane con il solo booleano `evidence_valid` o con un riferimento corrente all'evidence.

Ogni snapshot autorizzata conserva immutabilmente evidence, metrics, gates, dependencies, versions, hashes, methodology, approvals, scope, content hash, promotion/bundle/model binding e dependency checkpoint. Prima di ogni promotion la snapshot viene verificata contro il Promotion Bundle e contro la dependency invalidation chain.

Una snapshot diventa inutilizzabile quando una dipendenza materiale viene invalidata dopo il checkpoint di emissione, anche se l'incidente viene successivamente revalidato. Serve una nuova snapshot.

Il vincolo è applicato sia alla promotion contract sia ai percorsi Champion/Challenger e deployment; anche il legacy promotion checker non può più concedere promotion senza una snapshot authority durevole.

No external exchange/Testnet network calls or production credentials are used by this release.

`production_ready = FALSE`
