"""Start the exact command a client will run, and see whether it answers.

``docmax mcp connect`` used to write a config entry and stop. Whether a client
could then actually *start* that entry — the right interpreter, the SDK
installed, a root that exists — was discovered only when the tools failed to
appear, with the failure sitting in a client log the person never opens. This
module closes that gap: it spawns the entry as a subprocess, speaks the first
three messages of the MCP handshake (``initialize``, ``initialized``,
``tools/list``) over its stdio, and reports what came back, or the last lines
the process printed if it never answered.

It speaks raw newline-delimited JSON-RPC instead of importing the SDK. That is
deliberate twice over: ``cli`` may not import ``docmax.mcp`` internals, and a
probe that used the same library as the server could not tell a broken library
from a working one.
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from docmax.core.branding import CLI_NAME

if TYPE_CHECKING:
    from pathlib import Path

#: Offered to the server, which answers with the version it actually speaks.
_PROTOCOL_VERSION = "2025-06-18"
#: Cold start imports the SDK and the registry; a first run on a slow disk is
#: the case this has to survive, not the warm one.
DEFAULT_TIMEOUT = 45.0
_TAIL_LINES = 8


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    server: str | None = None
    version: str | None = None
    tools: tuple[str, ...] = ()
    detail: str = ""

    def as_report(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "server": self.server,
            "version": self.version,
            "tools": len(self.tools),
            "detail": self.detail,
        }


def _message(id_: int | None, method: str, params: dict[str, Any] | None = None) -> bytes:
    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if id_ is not None:
        body["id"] = id_
    if params is not None:
        body["params"] = params
    return (json.dumps(body) + "\n").encode("utf-8")


def probe(
    entry: dict[str, Any], *, cwd: Path | None = None, timeout: float = DEFAULT_TIMEOUT
) -> ProbeResult:
    """Run a stdio ``entry`` through the handshake. Never raises."""
    command = entry.get("command")
    if not isinstance(command, str) or not command:
        return ProbeResult(False, detail="The entry has no command to run.")

    try:
        process = subprocess.Popen(  # noqa: S603 -- the command is the one the client will run
            [command, *map(str, entry.get("args", []))],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd,
        )
    except OSError as exc:
        return ProbeResult(False, detail=f"Could not start {command!r}: {exc}")

    lines: queue.Queue[bytes | None] = queue.Queue()
    tail: deque[str] = deque(maxlen=_TAIL_LINES)

    def pump() -> None:
        assert process.stdout is not None
        for raw in process.stdout:
            lines.put(raw)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    deadline = time.monotonic() + timeout
    closed = False

    def reply_to(id_: int) -> dict[str, Any] | None:
        """The response carrying ``id_``, skipping notifications and noise."""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                raw = lines.get(timeout=remaining)
            except queue.Empty:
                return None
            if raw is None:
                nonlocal closed
                closed = True
                return None
            text = raw.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                body = json.loads(text)
            except json.JSONDecodeError:
                tail.append(text)
                continue
            if isinstance(body, dict) and body.get("id") == id_:
                return body

    def failure(what: str) -> ProbeResult:
        output = "\n".join(tail)
        return ProbeResult(False, detail=what + (f"\n{output}" if output else ""))

    try:
        assert process.stdin is not None
        process.stdin.write(
            _message(
                1,
                "initialize",
                {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": f"{CLI_NAME}-mcp-check", "version": "1"},
                },
            )
        )
        process.stdin.flush()
        init = reply_to(1)
        if init is None:
            return failure(
                "The server exited before answering."
                if closed or process.poll() is not None
                else f"The server did not answer within {timeout:.0f}s."
            )
        if "error" in init:
            return failure(f"The server rejected the handshake: {init['error']}")
        info = (init.get("result") or {}).get("serverInfo") or {}

        process.stdin.write(_message(None, "notifications/initialized"))
        process.stdin.write(_message(2, "tools/list", {}))
        process.stdin.flush()
        listed = reply_to(2)
        if listed is None or "error" in listed:
            return failure("The server started but would not list its tools.")
        tools = tuple(
            str(tool.get("name")) for tool in (listed.get("result") or {}).get("tools", [])
        )
        return ProbeResult(
            True,
            server=info.get("name"),
            version=info.get("version"),
            tools=tools,
        )
    except OSError as exc:
        return failure(f"The server closed its input early: {exc}")
    finally:
        try:
            if process.stdin:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


__all__ = ["DEFAULT_TIMEOUT", "ProbeResult", "probe"]
