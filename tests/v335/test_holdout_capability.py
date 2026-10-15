from __future__ import annotations
from datetime import datetime, timezone
import pytest

from trading_platform.v21.event_store import EventStore
from trading_platform.data.holdout import (
    HoldoutPolicy, HoldoutAccessContext, Workflow, HoldoutVault,
    HoldoutCapabilityInvalid, FinalHoldoutCapability,
)
from trading_platform.evidence.graph import EvidenceDependencyGraph


def context(store):
    return HoldoutAccessContext.build(
        store=store,
        graph=EvidenceDependencyGraph(),
        evidence_index={},
        gate_dependencies={},
        candidates={},
        promotions={},
    )


def test_tuning_cannot_issue_final_holdout_capability():
    s=EventStore(); c=context(s)
    with pytest.raises(PermissionError, match="FINAL_HOLDOUT_TUNING_CAPABILITY_FORBIDDEN"):
        HoldoutPolicy("H1").issue_capability(
            Workflow.TUNING, context=c, capability_id="C1", actor="research", issued_at_ms=1
        )


def test_vault_does_not_expose_raw_rows():
    s=EventStore(); c=context(s); p=HoldoutPolicy("H1")
    vault=HoldoutVault(holdout_id="H1", rows=(1,2,3), context=c, policy=p)
    assert not hasattr(vault, "rows")
    assert vault.holdout_id == "H1"


def test_capability_must_be_durably_issued_before_open():
    s=EventStore(); c=context(s); p=HoldoutPolicy("H1")
    vault=HoldoutVault(holdout_id="H1", rows=(1,2,3), context=c, policy=p)
    cap=FinalHoldoutCapability("C1","H1",Workflow.FINAL_EVALUATION,"validator",0,10000,"bad")
    with pytest.raises(HoldoutCapabilityInvalid, match="NOT_ISSUED"):
        vault.open(capability=cap, actor="validator", now_ms=10)


def test_final_evaluation_gets_single_use_handle():
    s=EventStore(); c=context(s); p=HoldoutPolicy("H1")
    cap=p.issue_capability(Workflow.FINAL_EVALUATION, context=c, capability_id="C1", actor="validator", issued_at_ms=10, ttl_ms=100)
    vault=HoldoutVault(holdout_id="H1", rows=("a","b"), context=c, policy=p)
    h=vault.open(capability=cap, actor="validator", now_ms=20)
    assert h.rows() == ("a","b")
    with pytest.raises(HoldoutCapabilityInvalid, match="ALREADY_USED"):
        vault.open(capability=cap, actor="validator", now_ms=21)


def test_expired_capability_fails_closed():
    s=EventStore(); c=context(s); p=HoldoutPolicy("H1")
    cap=p.issue_capability(Workflow.FINAL_EVALUATION, context=c, capability_id="C2", actor="validator", issued_at_ms=10, ttl_ms=10)
    vault=HoldoutVault(holdout_id="H1", rows=(1,), context=c, policy=p)
    with pytest.raises(HoldoutCapabilityInvalid, match="EXPIRED"):
        vault.open(capability=cap, actor="validator", now_ms=20)


def test_wrong_actor_and_workflow_fail_closed():
    s=EventStore(); c=context(s); p=HoldoutPolicy("H1")
    cap=p.issue_capability(Workflow.FINAL_EVALUATION, context=c, capability_id="C3", actor="validator", issued_at_ms=10, ttl_ms=100)
    vault=HoldoutVault(holdout_id="H1", rows=(1,), context=c, policy=p)
    with pytest.raises(HoldoutCapabilityInvalid, match="ACTOR_MISMATCH"):
        vault.open(capability=cap, actor="research", now_ms=20)
    with pytest.raises(HoldoutCapabilityInvalid, match="WORKFLOW_FORBIDDEN"):
        forged=FinalHoldoutCapability(cap.capability_id,cap.holdout_id,Workflow.TUNING,cap.actor,cap.valid_from_ms,cap.expires_at_ms,cap.nonce_digest)
        vault.open(capability=forged, actor="validator", now_ms=20)
