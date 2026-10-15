"""V3.75 parity infrastructure."""

from .decision_parity import (
    BacktestDecisionTraceCollector,
    DecisionTrace,
    DecisionTraceRecord,
    LiveDecisionEngine,
    LiveDecisionResult,
    ParityComparison,
    ParityInputError,
    capture_backtest_decision_trace,
    compare_decision_traces,
)

__all__ = [
    "BacktestDecisionTraceCollector",
    "DecisionTrace",
    "DecisionTraceRecord",
    "LiveDecisionEngine",
    "LiveDecisionResult",
    "ParityComparison",
    "ParityInputError",
    "capture_backtest_decision_trace",
    "compare_decision_traces",
]
