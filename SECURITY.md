# Security policy

DocMax opens untrusted documents and can run as a tool for AI agents, so security reports are taken seriously.

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately instead:

- Use GitHub's [private vulnerability reporting](https://github.com/megabyte44/docmax/security/advisories/new), or
- email the maintainer at punithmedaramitta@gmail.com.

Include the DocMax version (`docmax --version`), your OS, and steps or a sample file that reproduces the problem.

You can expect an acknowledgement within a few days and a fix or mitigation plan once the issue is confirmed.
Reporters are credited in the release notes unless they ask otherwise.

## Scope

Of particular interest:

- Escaping the `--root` confinement of `docmax mcp` (path traversal, symlinks).
- Overwriting or deleting files without `--force`, or writing outside the chosen output path.
- Sending data to a cloud endpoint without recorded consent, or while `offline = true`.
- Crashes or code execution from a crafted PDF or image.

Vulnerabilities in third-party dependencies (PyMuPDF, pypdf and others) should go to those projects, though
please tell us if DocMax needs a version bump.

## Supported versions

Fixes land on the latest release.
