"""``python -m docmax`` — the same CLI, reachable without a console script.

An MCP client starts the server as a bare subprocess, usually from a GUI app
that inherited neither the shell's ``PATH`` nor a virtualenv's ``Scripts``
directory. A bare ``docmax`` command fails there with nothing to look up; an
absolute interpreter path plus ``-m docmax`` always resolves to the install
that wrote the config. ``docmax mcp connect`` relies on this.
"""

from __future__ import annotations

from docmax.cli.main import app

if __name__ == "__main__":
    app()
