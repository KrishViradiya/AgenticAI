"""Runs pytest or the tinyledger CLI inside a Python audit-hook sandbox (used by tools.py, not by the model).

    python -I -B sandbox_runner.py <pytest|cli|search> <workspace> <private_tmp> [args ...]

Why: the agent can edit code below src/, and run_tests/run_cli then EXECUTE that code. Code like
`print(open("../secrets/canary.txt").read())` would leak the secret through the tool output, even though
read_file itself refuses that path. So the child process gets an audit hook (PEP 578) that refuses:

  - opening files outside the workspace, the private temp dir and the Python installation (read)
  - opening files for writing outside the workspace and the private temp dir
  - starting processes (subprocess, os.system, os.exec*, os.spawn*, os.startfile)
  - network connections (socket.connect / bind / getaddrinfo)

Limits: an audit hook runs inside the same interpreter, so native code (ctypes, C extensions) could get
around it. It is defence in depth on top of the other controls (minimal environment, no shell, timeouts),
not an OS sandbox.
"""

from __future__ import annotations

import os
import sys

BLOCKED_EVENTS = {
    "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.startfile", "os.fork",
    "os.forkpty", "pty.spawn", "socket.connect", "socket.bind", "socket.getaddrinfo", "socket.sendto",
    "ctypes.dlopen", "_winapi.CreateProcess",
}
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _inside(path: str, roots: list[str]) -> bool:
    for root in roots:
        try:
            if os.path.commonpath([path, root]) == root:
                return True
        except ValueError:  # different drives on Windows
            continue
    return False


def install_sandbox(workspace: str, tmp: str) -> None:
    write_roots = [_norm(workspace), _norm(tmp)]
    python_roots = {sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix}
    python_roots.update(p for p in sys.path if p and os.path.isdir(p))  # stdlib, site-packages (-I: no cwd)
    read_roots = write_roots + sorted({_norm(p) for p in python_roots})
    null_devices = {_norm(os.devnull), os.path.normcase(os.devnull), _norm(r"\\.\nul"), os.path.normcase(r"\\.\nul")}

    def hook(event: str, args: tuple) -> None:
        if event == "open":
            path, mode, flags = args
            if path is None or isinstance(path, int):
                return  # an already open file descriptor
            try:
                real = _norm(os.fsdecode(path))
            except Exception:
                raise PermissionError("sandbox: unreadable path") from None
            if real in null_devices:
                return  # the null device ('nul', '\\.\nul', '/dev/null'), used by pytest's output capturing
            writing = bool(mode and any(c in mode for c in "wax+")) or bool((flags or 0) & WRITE_FLAGS)
            if not _inside(real, write_roots if writing else read_roots):
                action = "writing" if writing else "reading"
                raise PermissionError(f"sandbox: {action} {os.fsdecode(path)!r} is blocked (outside the workspace)")
        elif event in BLOCKED_EVENTS or event.split(".")[0] in {"os.exec", "os.spawn"}:
            raise PermissionError(f"sandbox: {event} is blocked")

    sys.addaudithook(hook)


def main() -> int:
    mode, workspace, tmp, *rest = sys.argv[1:]
    for stream in (sys.stdout, sys.stderr):  # -I ignores PYTHONIOENCODING, so set UTF-8 here (the € sign)
        stream.reconfigure(encoding="utf-8", errors="replace")
    workspace = os.path.realpath(workspace)
    os.chdir(workspace)
    src = os.path.join(workspace, "src")
    install_sandbox(workspace, tmp)
    sys.path.insert(0, src)  # PYTHONPATH=src, without trusting the environment

    if mode == "pytest":
        import pytest

        return int(pytest.main(rest))
    if mode == "cli":
        import runpy

        sys.argv = ["tinyledger", *rest]
        try:
            runpy.run_module("tinyledger", run_name="__main__", alter_sys=True)
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        return 0
    if mode == "search":
        return search()
    raise SystemExit(f"unknown mode {mode!r}")


def search() -> int:
    """Regex search, in a child process so a catastrophic regex like (a+)+$ can be killed by the timeout.

    stdin: {"pattern": ..., "files": [relative paths, already checked by tools.py], "max_results": n, "max_line": n}
    stdout: {"matches": ["path:line: text", ...], "more": bool}
    """
    import json
    import re

    request = json.loads(sys.stdin.read())
    regex = re.compile(request["pattern"])
    matches, more = [], False
    for rel in request["files"]:
        try:
            with open(rel, encoding="utf-8", errors="replace") as f:
                for number, line in enumerate(f, start=1):
                    line = line.rstrip("\r\n")[: request["max_line"]]
                    if regex.search(line):
                        if len(matches) >= request["max_results"]:
                            more = True
                            break
                        matches.append(f"{rel}:{number}: {line.strip()}")
        except OSError:
            continue
        if more:
            break
    sys.stdout.write(json.dumps({"matches": matches, "more": more}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
