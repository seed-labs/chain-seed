"""Exercise build diagnostics and lifecycle cleanup without Docker."""

from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import Mock, patch

from chainseed.testing.blockchain import BlockchainTestRunner


def runner_at(directory):
    runner = BlockchainTestRunner.__new__(BlockchainTestRunner)
    runner.artifact_dir = Path(directory)
    return runner


def test_build_timeout_preserves_partial_output():
    with tempfile.TemporaryDirectory() as directory:
        runner = runner_at(directory)
        result = runner.run_command(
            "build", [sys.executable, "-u", "-c",
                      "import time; print('downloading packages'); time.sleep(10)"],
            cwd=Path(directory), timeout=0.2,
        )
        assert result.returncode == 124
        log = Path(directory, "logs/build.log").read_text()
        assert "downloading packages" in log
        assert "TIMEOUT:" in log
        assert "EXIT: 124" in log


def test_build_failure_preserves_stderr_and_exit_code():
    with tempfile.TemporaryDirectory() as directory:
        result = runner_at(directory).run_command(
            "build", [sys.executable, "-c",
                      "import sys; print('download failed', file=sys.stderr); sys.exit(7)"],
            cwd=Path(directory), timeout=5,
        )
        assert result.returncode == 7
        assert "download failed" in Path(directory, "logs/build.log").read_text()


def test_timeout_without_artifacts_returns_failure():
    runner = runner_at("/tmp")
    runner.artifact_dir = None
    result = runner.run_command(
        "probe", [sys.executable, "-u", "-c",
                  "import time; print('partial output'); time.sleep(10)"],
        cwd=Path("/tmp"), timeout=0.2,
    )
    assert result.returncode == 124
    assert "partial output" in result.stdout


def test_all_stops_after_build_timeout_and_cleans_up():
    runner = runner_at("/tmp")
    for name in ("clean", "compile", "up", "probe", "test", "down"):
        setattr(runner, name, Mock(return_value=0))
    runner.build = Mock(return_value=124)
    assert runner.all() == 124
    runner.down.assert_called_once()
    runner.up.assert_not_called()


def test_down_saves_diagnostics_before_removing_containers():
    from seedemu.testing.base import TestRunner

    with tempfile.TemporaryDirectory() as directory:
        runner = runner_at(directory)
        compose = Path(directory, "docker-compose.yml")
        compose.touch()
        runner.compose_file = Mock(return_value=compose)
        calls = []
        runner.run_command = Mock(side_effect=lambda name, *args, **kwargs: calls.append(name))
        with patch.object(TestRunner, "down", side_effect=lambda: calls.append("down") or 0):
            assert runner.down() == 0
        assert calls == ["runtime-ps", "runtime-logs", "down"]


def test_diagnostic_failure_does_not_prevent_cleanup():
    from seedemu.testing.base import TestRunner

    with tempfile.TemporaryDirectory() as directory:
        runner = runner_at(directory)
        compose = Path(directory, "docker-compose.yml")
        compose.touch()
        runner.compose_file = Mock(return_value=compose)
        runner.run_command = Mock(side_effect=OSError("Docker unavailable"))
        with patch.object(TestRunner, "down", return_value=0) as cleanup:
            assert runner.down() == 0
        cleanup.assert_called_once()


def test_lighthouse_probes_do_not_match_their_own_shell():
    import yaml

    examples = Path(__file__).resolve().parents[1] / "examples"
    checked = 0
    for manifest in examples.glob("*/*/example.yaml"):
        for probe in yaml.safe_load(manifest.read_text()).get("probes", []):
            command = probe.get("command", "")
            if "pgrep -af" not in command or "ighthouse" not in command:
                continue
            pattern = command.split("'", 2)[1]
            assert re.search(pattern, "lighthouse --debug-level info bn --http") or re.search(
                pattern, "lighthouse --debug-level info vc --http"
            )
            assert not re.search(pattern, "sh -lc " + command), manifest
            checked += 1
    assert checked == 12
