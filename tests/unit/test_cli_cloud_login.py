"""``docmax cloud login`` / ``check``: one command from nothing to a working connection.

The config directory is faked through `platformdirs.user_config_dir` and the
endpoint is never contacted -- `_probe` is replaced -- so no run of this suite
can read or write a real credential or make a network request.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from docmax.cli import cloud
from docmax.cli.main import app
from docmax.cloud_client.models import Capabilities
from docmax.core.consent import ConsentStore
from docmax.core.errors import CloudAuthError, CloudEngineUnavailableError

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
KEY = "sk-test-1234567890"
ENDPOINT = "https://cloud.example.invalid"


def shown(result: Any) -> str:
    return _ANSI.sub("", result.stdout) + _ANSI.sub("", result.stderr)


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import platformdirs

    from docmax.cli import json_output

    config_dir = tmp_path / "cfg"
    monkeypatch.setattr(platformdirs, "user_config_dir", lambda *_a, **_k: str(config_dir))
    monkeypatch.delenv("DOCMAX_API_KEY", raising=False)
    monkeypatch.delenv("DOCMAX_CLOUD_ENDPOINT", raising=False)
    json_output.set_enabled(False)
    return config_dir


def caps(*tools: str) -> Capabilities:
    return Capabilities(tools=frozenset(tools), max_sync_bytes=1024, api_version="1")


@pytest.fixture
def reachable(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    def probe(endpoint: str, api_key: str) -> Capabilities:
        calls.append((endpoint, api_key))
        return caps("ocr")

    monkeypatch.setattr(cloud, "_probe", probe)
    return calls


def saved(config_dir: Path) -> dict[str, Any]:
    return tomllib.loads((config_dir / "config.toml").read_text(encoding="utf-8"))


def test_login_verifies_then_saves_key_and_endpoint(isolated: Path, reachable: list) -> None:
    result = runner.invoke(
        app, ["cloud", "login", "--api-key", KEY, "--endpoint", ENDPOINT, "--no-consent"]
    )

    assert result.exit_code == 0, shown(result)
    assert reachable == [(ENDPOINT, KEY)]
    assert saved(isolated)["cloud"] == {"api_key": KEY, "endpoint": ENDPOINT}
    assert KEY not in shown(result)


def test_a_rejected_key_saves_nothing(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(endpoint: str, api_key: str) -> Capabilities:
        raise CloudAuthError("nope")

    monkeypatch.setattr(cloud, "_probe", reject)

    result = runner.invoke(app, ["cloud", "login", "--api-key", KEY])

    assert result.exit_code != 0
    assert not (isolated / "config.toml").exists()


def test_an_unreachable_endpoint_saves_nothing_unless_told_to(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(endpoint: str, api_key: str) -> Capabilities:
        raise CloudEngineUnavailableError("down")

    monkeypatch.setattr(cloud, "_probe", down)

    assert runner.invoke(app, ["cloud", "login", "--api-key", KEY]).exit_code != 0
    assert not (isolated / "config.toml").exists()

    result = runner.invoke(app, ["cloud", "login", "--api-key", KEY, "--no-verify"])
    assert result.exit_code == 0, shown(result)
    assert saved(isolated)["cloud"]["api_key"] == KEY


def test_a_plaintext_remote_endpoint_is_refused_before_anything_is_sent(
    isolated: Path, reachable: list
) -> None:
    result = runner.invoke(
        app, ["cloud", "login", "--api-key", KEY, "--endpoint", "http://example.invalid"]
    )

    assert result.exit_code != 0
    assert reachable == []
    assert not (isolated / "config.toml").exists()


def test_consent_flag_records_only_tools_both_sides_offer(isolated: Path, reachable: list) -> None:
    result = runner.invoke(
        app, ["cloud", "login", "--api-key", KEY, "--endpoint", ENDPOINT, "--consent"]
    )

    assert result.exit_code == 0, shown(result)
    granted = ConsentStore(isolated / "consent.json", endpoint=ENDPOINT).granted_tools()
    assert set(granted) <= {"ocr"}


def test_without_a_terminal_consent_is_not_assumed(isolated: Path, reachable: list) -> None:
    result = runner.invoke(app, ["cloud", "login", "--api-key", KEY, "--endpoint", ENDPOINT])

    assert result.exit_code == 0, shown(result)
    assert not ConsentStore(isolated / "consent.json", endpoint=ENDPOINT).granted_tools()


def test_check_without_a_key_points_at_login(isolated: Path) -> None:
    result = runner.invoke(app, ["cloud", "check"])

    assert result.exit_code == 1
    assert "cloud login" in shown(result)


def test_check_reports_the_connection(isolated: Path, reachable: list) -> None:
    runner.invoke(app, ["cloud", "login", "--api-key", KEY, "--no-consent"])

    result = runner.invoke(app, ["cloud", "check"])

    assert result.exit_code == 0, shown(result)
    assert "Connected" in shown(result)
    assert KEY not in shown(result)


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        ("", '\n[cloud]\nendpoint = "https://a.invalid"\n'),
        ('[cloud]\napi_key = "k"\n', '[cloud]\nendpoint = "https://a.invalid"\napi_key = "k"\n'),
        ('[cloud]\nendpoint = "old"\n', '[cloud]\nendpoint = "https://a.invalid"\n'),
    ],
)
def test_setting_an_endpoint_edits_only_that_line(original: str, expected: str) -> None:
    updated, _ = cloud._set_cloud_value(original, "endpoint", "https://a.invalid")

    assert updated == expected


def test_a_key_with_backslashes_survives_replacement() -> None:
    updated, existed = cloud._set_cloud_value('[cloud]\napi_key = "old"\n', "api_key", r"a\1b")

    assert existed
    assert tomllib.loads(updated)["cloud"]["api_key"] == r"a\1b"
