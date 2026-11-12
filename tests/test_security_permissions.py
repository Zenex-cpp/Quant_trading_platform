from __future__ import annotations

import csv
from pathlib import Path

import pytest

from trading_platform.security.permissions import (
    Capability,
    ROLE_CAPABILITIES,
    assert_capability,
    capability_matrix,
)


ROOT = Path(__file__).resolve().parents[1]


def test_permission_matrix_matches_every_runtime_role_capability_pair():
    with (ROOT / "schemas/v5_permission_matrix.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        published = tuple(
            (row["role"], row["capability"], row["decision"])
            for row in csv.DictReader(stream)
        )

    expected = capability_matrix()
    assert published == expected
    assert len(published) == len(Capability) ** 2
    assert len({(role, capability) for role, capability, _ in published}) == len(published)
    assert all(decision in {"ALLOW", "DENY"} for _, _, decision in published)


def test_research_is_limited_to_research_training_and_backtest():
    for capability in (Capability.RESEARCH, Capability.TRAINING, Capability.BACKTEST):
        assert_capability(" research ", capability)

    for capability in Capability:
        if capability not in ROLE_CAPABILITIES[Capability.RESEARCH]:
            with pytest.raises(PermissionError):
                assert_capability("RESEARCH", capability)


@pytest.mark.parametrize("role", ["", "UNKNOWN", "PRODUCTION", None, 7])
def test_unknown_or_invalid_roles_fail_closed(role):
    with pytest.raises(PermissionError, match="ROLE_UNKNOWN_FORBIDDEN"):
        assert_capability(role, Capability.BACKTEST)


@pytest.mark.parametrize("capability", [None, "BACKTEST", object()])
def test_capabilities_must_be_enum_values(capability):
    with pytest.raises(PermissionError, match="CAPABILITY_INVALID_FORBIDDEN"):
        assert_capability("RESEARCH", capability)
