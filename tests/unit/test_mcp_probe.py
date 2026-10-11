"""The handshake probe: what it reports for a server that works, and for ones that do not.

The failure cases use throwaway Python one-liners as the "server", so they need
no MCP SDK and run in milliseconds. One test starts the real server, because
that is the only way to know the entry `connect` writes can actually answer.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from docmax.cli import mcp_group, mcp_probe

_FAKE_SERVER = """
import json, sys
for line in sys.stdin:
    message = json.loads(line)
    if message.get("method") == "initialize":
        reply = {"serverInfo": {"name": "fake", "version": "9"}}
    elif message.get("method") == "tools/list":
        reply = {"tools": [{"name": "alpha"}, {"name": "beta"}]}
    else:
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": reply}), flush=True)
"""


def _python(code: str) -> dict[str, Any]:
    return {"command": sys.executable, "args": ["-c", code]}


def test_a_well_behaved_server_reports_its_name_and_tools() -> None:
    result = mcp_probe.probe(_python(_FAKE_SERVER), timeout=15)

    assert result.ok
    assert (result.server, result.version) == ("fake", "9")
    assert result.tools == ("alpha", "beta")


def test_a_missing_command_is_reported_not_raised() -> None:
    result = mcp_probe.probe({"command": "definitely-not-a-real-command-xyz", "args": []})

    assert not result.ok
    assert "Could not start" in result.detail


def test_a_server_that_crashes_shows_what_it_printed() -> None:
    code = "import sys; print('ModuleNotFoundError: No module named mcp', file=sys.stderr)"

    result = mcp_probe.probe(_python(code), timeout=15)

    assert not result.ok
    assert "exited before answering" in result.detail
    assert "No module named mcp" in result.detail


def test_a_silent_server_times_out_instead_of_hanging() -> None:
    result = mcp_probe.probe(_python("import time; time.sleep(30)"), timeout=1)

    assert not result.ok
    assert "did not answer" in result.detail


def test_an_entry_without_a_command_is_rejected() -> None:
    assert not mcp_probe.probe({"args": []}).ok


def test_a_real_server_answers_the_handshake(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    entry = mcp_group.local_entry([tmp_path], allow_cloud=False)

    result = mcp_probe.probe(entry, cwd=tmp_path)

    assert result.ok, result.detail
    assert result.server == "docmax"
    assert "merge" in result.tools
