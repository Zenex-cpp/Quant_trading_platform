#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "src"))
from trading_platform.v391.network_segmentation import NetworkSegmentationPolicyV391

policy = NetworkSegmentationPolicyV391()
payload = policy.review_payload()
payload["evidence_id"] = "V391-NETWORK-SEGMENTATION-001"
payload["scope"] = "APPLICATION_POLICY_CONTRACT"
payload["mutating_network_call"] = False
payload["production_ready"] = False
(root / "V391_NETWORK_SEGMENTATION_EVIDENCE.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(payload, sort_keys=True))
