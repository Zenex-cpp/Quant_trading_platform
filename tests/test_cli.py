import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

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


def test_source_acceptance_entrypoint_does_not_create_repository_bytecode(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    checkout = tmp_path / "checkout"
    (checkout / "scripts").mkdir(parents=True)
    shutil.copy2(repository / "scripts" / "run_offline_acceptance.py", checkout / "scripts" / "run_offline_acceptance.py")
    shutil.copytree(
        repository / "src" / "trading_platform",
        checkout / "src" / "trading_platform",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    environment = dict(os.environ)
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [sys.executable, str(checkout / "scripts" / "run_offline_acceptance.py")],
        cwd=checkout,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["acceptance"]["acceptance_passed"] is True
    assert report["environment"] == "OFFLINE_SIMULATION"
    assert list(checkout.rglob("__pycache__")) == []
