#!/usr/bin/env python3
"""Verify a signed remote-repository snapshot; make no network requests.

Without a production trust anchor and a fresh signed provider snapshot, the
report remains BLOCKED. This diagnostic is non-fatal by default because the
host-side setting cannot be proven from the local checkout alone.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from trading_platform.v21.event_store import EventStore
from trading_platform.v428.repository_governance import RemoteRepositoryGovernanceEvidenceAuthorityV428
from trading_platform.v428.path_safety import (
    PathSafetyErrorV428, ensure_paths_distinct_v428, resolve_repository_path_v428,
    write_audit_text_v428,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", default="V424_REPOSITORY_GOVERNANCE_EVIDENCE_TEMPLATE.json")
    parser.add_argument("--trust", default="config/repository_governance_trust_v424.json")
    parser.add_argument("--workflow", default=".github/workflows/ci.yml")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--report", default=".audit/V428_REPOSITORY_GOVERNANCE.json")
    parser.add_argument("--event-store", default=".audit/V428_REPOSITORY_GOVERNANCE.sqlite3")
    parser.add_argument("--decision-id", default=None)
    parser.add_argument("--now-ms", type=int, default=None)
    parser.add_argument("--require-verified", action="store_true", help="Return nonzero unless signed external evidence is VERIFIED")
    args = parser.parse_args(argv)
    try:
        evidence_path = resolve_repository_path_v428(ROOT, args.evidence, label="EVIDENCE")
        trust_path = resolve_repository_path_v428(ROOT, args.trust, label="TRUST")
        workflow_path = resolve_repository_path_v428(ROOT, args.workflow, label="WORKFLOW")
        report_path = resolve_repository_path_v428(ROOT, args.report, label="REPORT", output_scope=".audit")
        event_path = resolve_repository_path_v428(ROOT, args.event_store, label="EVENT_STORE", output_scope=".audit")
        ensure_paths_distinct_v428(
            outputs={"report": report_path, "event_store": event_path},
            protected_inputs={"evidence": evidence_path, "trust": trust_path, "workflow": workflow_path},
        )
        if report_path == event_path:
            raise PathSafetyErrorV428("OUTPUT_PATH_COLLISION:report:event_store")
    except PathSafetyErrorV428 as exc:
        parser.error(f"PATH_POLICY_REJECTED:{exc}")
    now = args.now_ms if args.now_ms is not None else time.time_ns() // 1_000_000
    report_path.parent.mkdir(parents=True, exist_ok=True)
    event_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    try:
        trust = json.loads(trust_path.read_text(encoding="utf-8"))
    except Exception:
        trust = {"state": "NOT_CONFIGURED"}
    trusted = (
        trust.get("state") == "VERIFIED"
        and bool(trust.get("trust_ceremony_reference"))
        and trust.get("signer_role") == "INDEPENDENT_REPOSITORY_ADMIN_REVIEWER"
        and bool(trust.get("key_id"))
        and bool(trust.get("signer_id"))
        and bool(trust.get("public_key_b64"))
        and isinstance(trust.get("public_key_sha256"), str)
        and len(trust.get("public_key_sha256", "")) == 64
    )
    store = EventStore(str(event_path))
    authority = RemoteRepositoryGovernanceEvidenceAuthorityV428(
        store=store,
        expected_repository=args.repository,
        expected_branch=args.branch,
        trusted_signer_key_id=trust.get("key_id") if trusted else None,
        trusted_signer_public_key_b64=trust.get("public_key_b64") if trusted else None,
        trusted_signer_id=trust.get("signer_id") if trusted else None,
        trusted_signer_public_key_sha256=trust.get("public_key_sha256") if trusted else None,
    )
    attestation = payload.pop("attestation", None) if isinstance(payload, dict) else None
    workflow_text = workflow_path.read_text(encoding="utf-8") if workflow_path.is_file() else ""
    decision_id = args.decision_id or f"V424-REPO-GOV-{now}"
    decision = authority.evaluate(
        decision_id=decision_id,
        payload=payload if isinstance(payload, dict) else {},
        attestation=attestation if isinstance(attestation, dict) else {},
        now_ms=now,
        workflow_text=workflow_text,
    )
    output = {
        "schema_version": "V4.28",
        "evidence_schema_version": "V4.24",
        "decision_id": decision.decision_id,
        "repository": decision.repository,
        "protected_branch": decision.protected_branch,
        "status": decision.status,
        "allowed": decision.allowed,
        "payload_hash": decision.payload_hash,
        "attestation_hash": decision.attestation_hash,
        "blocking_reasons": list(decision.blocking_reasons),
        "reviewer_id": decision.reviewer_id,
        "event_hash": decision.event_hash,
        "duplicate": decision.duplicate,
        "trust_anchor_configured": trusted,
        "hosted_workflow_run": "NOT_VERIFIED_UNLESS_SIGNED_PROVIDER_SNAPSHOT_ACCEPTED",
        "branch_protection": "NOT_VERIFIED_UNLESS_SIGNED_PROVIDER_SNAPSHOT_ACCEPTED",
        "external_evidence": False,
        "production_ready": False,
        "activation_flag": "NOT_SET",
    }
    write_audit_text_v428(ROOT, report_path, json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(f"REPOSITORY_GOVERNANCE={decision.status}")
    for reason in decision.blocking_reasons:
        print(f"BLOCKER={reason}")
    return 2 if args.require_verified and not decision.allowed else 0


if __name__ == "__main__":
    raise SystemExit(main())
