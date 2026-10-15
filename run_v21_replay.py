#!/usr/bin/env python3
from __future__ import annotations
import argparse
from trading_platform.v21.event_store import EventStore
from trading_platform.v21.replay import DeterministicReplayer

p=argparse.ArgumentParser(description='V2.1 deterministic replay verifier')
p.add_argument('--db', required=True)
args=p.parse_args()
store=EventStore(args.db)
result=DeterministicReplayer().replay(store)
print({'events_replayed': result.event_count, 'event_sequence': result.checkpoint.event_sequence, 'state_hash': result.checkpoint.state_hash})
