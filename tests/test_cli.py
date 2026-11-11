import json
import socket

from trading_platform.cli import main


def test_offline_acceptance_command_runs_without_network(monkeypatch, capsys):
    def deny_network(*args, **kwargs):
        raise AssertionError("OFFLINE_ACCEPTANCE_ATTEMPTED_NETWORK_ACCESS")

    monkeypatch.setattr(socket.socket, "connect", deny_network)

    assert main(["offline-acceptance"]) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["environment"] == "OFFLINE_SIMULATION"
    assert report["external_evidence"] is False
    assert report["activation_flag"] == "NOT_SET"
    assert report["acceptance"]["acceptance_passed"] is True
    assert report["acceptance"]["production_ready"] is False
    assert report["stages"][-1]["stage"] == "Gate"
    assert len(report["report_hash"]) == 64
