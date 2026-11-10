import os
import subprocess
import sys

import pytest

from backend import serve


def test_container_refuses_to_start_without_a_long_service_key(monkeypatch):
    monkeypatch.setenv("FLOWSTATE_API_KEY", "too-short")
    with pytest.raises(SystemExit, match="at least 32 characters"):
        serve.main()


def test_container_only_initializes_its_designated_volume(monkeypatch, tmp_path):
    monkeypatch.setenv("FLOWSTATE_API_KEY", "a" * 48)
    monkeypatch.setenv("FLOWSTATE_DATA", str(tmp_path / "unexpected-volume"))
    with pytest.raises(SystemExit, match="mounted at /data"):
        serve.main()
    assert not (tmp_path / "unexpected-volume").exists()


def test_production_config_cannot_bypass_service_authentication(tmp_path):
    environment = {
        **os.environ,
        "FLOWSTATE_DATA": str(tmp_path),
        "FLOWSTATE_REQUIRE_API_KEY": "1",
        "FLOWSTATE_API_KEY": "",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import backend.config"],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "FLOWSTATE_API_KEY must contain at least 32 characters" in result.stderr
