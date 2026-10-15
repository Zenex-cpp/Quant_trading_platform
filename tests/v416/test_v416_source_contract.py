from pathlib import Path


def test_v416_source_contract_forbids_runtime_and_network_mutation_capabilities():
    source = Path("src/trading_platform/v416/operational_readiness_convergence.py").read_text(encoding="utf-8")
    forbidden = ["requests.", "urllib.", "socket.", "subprocess.", "os.system(", "production_ready =", "Testnet", "testnet"]
    assert not any(token in source for token in forbidden)
