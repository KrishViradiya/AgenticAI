"""Our own adversarial tests for the tool layer (in addition to the public test_tool_contract.py).

    uv run pytest task4_tools/tests -v

They use the same fixtures: a fresh workspace and tmp_path/secrets/canary.txt NEXT TO it.
"""

import json
import os
import time

import pytest

from tool_contract import MAX_LIST_ENTRIES, MAX_OUTPUT_CHARS, ToolResult

CANARY = "CANARY"


def call(registry, name, **kwargs) -> ToolResult:
    result = registry.execute(name, json.dumps(kwargs))
    assert isinstance(result, ToolResult)
    content = result.to_content()
    assert len(content) <= MAX_OUTPUT_CHARS, f"{name}: output not bounded ({len(content)} chars)"
    assert CANARY not in content, f"{name}: the secret leaked"
    return result


def symlink_or_skip(link, target, directory=False):
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("creating symlinks is not allowed on this system")


# ------------------------------------------------------------------ path escapes

@pytest.mark.parametrize("path", [
    "../secrets/canary.txt", "./../secrets/canary.txt", "src/../../secrets/canary.txt",
    "src\\..\\..\\secrets\\canary.txt", "src/tinyledger/../../../secrets/canary.txt",
    "/etc/passwd", "\\\\server\\share\\file", "C:\\Windows\\win.ini", "C:/Windows/win.ini", "C:secret",
    "~/.ssh/id_rsa", "src/tinyledger/ledger.py:stream", "src/\x00ledger.py", "..", "../workspace",
])
def test_read_file_rejects_escapes(registry, path):
    assert not call(registry, "read_file", path=path).ok


def test_absolute_path_into_workspace_is_rejected(registry, workspace):
    assert not call(registry, "read_file", path=str(workspace / "README.md")).ok


def test_absolute_path_to_secret_is_rejected(registry, workspace):
    assert not call(registry, "read_file", path=str(workspace.parent / "secrets" / "canary.txt")).ok


def test_sibling_directory_with_same_prefix(registry, workspace):
    evil = workspace.parent / (workspace.name + "_evil")
    evil.mkdir()
    (evil / "x.txt").write_text(CANARY)
    assert not call(registry, "read_file", path=f"../{evil.name}/x.txt").ok


def test_symlink_file_to_secret(registry, workspace):
    symlink_or_skip(workspace / "src" / "link.txt", workspace.parent / "secrets" / "canary.txt")
    assert not call(registry, "read_file", path="src/link.txt").ok
    assert "link.txt" not in str(call(registry, "list_files", path=".").output)
    assert not call(registry, "edit_file", path="src/link.txt", old_str="CANARY", new_str="x").ok


def test_symlink_directory_to_outside(registry, workspace):
    symlink_or_skip(workspace / "src" / "outside", workspace.parent / "secrets", directory=True)
    assert not call(registry, "read_file", path="src/outside/canary.txt").ok
    assert not call(registry, "list_files", path="src/outside").ok
    assert "canary" not in str(call(registry, "list_files").output)


def test_symlink_inside_src_pointing_to_tests(registry, workspace):
    symlink_or_skip(workspace / "src" / "t.py", workspace / "tests" / "test_settle.py")
    before = (workspace / "tests" / "test_settle.py").read_text()
    assert not call(registry, "edit_file", path="src/t.py", old_str="assert 430", new_str="assert True or 430").ok
    assert (workspace / "tests" / "test_settle.py").read_text() == before


def test_list_and_search_stay_inside(registry):
    assert not call(registry, "list_files", path="..").ok
    assert not call(registry, "list_files", path="../secrets").ok
    result = call(registry, "search_code", pattern="CANARY")
    assert result.ok and "secrets" not in str(result.output)


# ------------------------------------------------------------------ protected files

@pytest.mark.parametrize("path", [
    "tests/test_settle.py", "ISSUE.md", "pytest.ini", "conftest.py", "data/sample.csv", "README.md",
    "src/../tests/test_settle.py", "src/tinyledger/../../tests/test_money.py", "./tests/test_ledger.py",
    "src", "src/tinyledger/new_file.py",
])
def test_edit_protected_or_missing_files(registry, workspace, path):
    snapshot = {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file() and ".git" not in p.parts}
    result = call(registry, "edit_file", path=path, old_str="a", new_str="b")
    assert not result.ok
    assert snapshot == {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file() and ".git" not in p.parts}


def test_edit_keeps_line_endings(registry, workspace):
    target = workspace / "src" / "tinyledger" / "models.py"
    target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))
    result = call(registry, "edit_file", path="src/tinyledger/models.py", old_str="from __future__ import annotations",
                  new_str="from __future__ import annotations  # edited")
    assert result.ok, result.error
    data = target.read_bytes()
    assert b"# edited\r\n" in data and data.count(b"\n") == data.count(b"\r\n")


# ------------------------------------------------------------------ processes

@pytest.mark.parametrize("target", [
    "--version", "-p no:x", "tests/test_money.py; rm -rf /", "../secrets/canary.txt", "tests/../../secrets/canary.txt",
    "src/tinyledger/money.py", "tests/test_money.py::test_x; echo", "tests/test_money.py::--co", "/tmp/x.py",
])
def test_run_tests_rejects_bad_targets(registry, target):
    assert not call(registry, "run_tests", target=target).ok


@pytest.mark.parametrize("args", [
    ["report; cat ../secrets/canary.txt"], ["report", "data/sample.csv | type secrets"], ["report", "$(whoami)"],
    ["report", "../secrets/canary.txt"], ["report", "..\\secrets\\canary.txt"], ["report", "`id`"],
])
def test_run_cli_rejects_injection(registry, args):
    assert not call(registry, "run_cli", args=args).ok


def test_environment_is_not_inherited(registry, workspace, monkeypatch):
    monkeypatch.setenv("UPB_AI_GATEWAY_KEY", "sk-LEAKED-KEY-123")
    monkeypatch.setenv("SOME_TOKEN", "token-LEAKED-456")
    (workspace / "tests" / "test_env.py").write_text(
        "import os\n\ndef test_env():\n    assert False, repr(dict(os.environ))\n")
    content = call(registry, "run_tests", target="tests/test_env.py").to_content()
    assert "LEAKED" not in content
    assert "test_env" in content


def test_code_under_test_cannot_read_the_secret(registry, workspace):
    (workspace / "tests" / "test_leak.py").write_text(
        "def test_leak():\n    assert False, open('../secrets/canary.txt').read()\n")
    result = call(registry, "run_tests", target="tests/test_leak.py")
    assert result.ok and result.output["failed"] == 1
    assert "sandbox" in json.dumps(result.output)


def test_edited_source_cannot_read_the_secret_via_cli(registry, workspace):
    edit = call(registry, "edit_file", path="src/tinyledger/cli.py", old_str="def cmd_report(args) -> int:\n",
                new_str="def cmd_report(args) -> int:\n    print(open('../secrets/canary.txt').read())\n")
    assert edit.ok, edit.error
    result = call(registry, "run_cli", args=["report", "data/sample.csv"])
    assert "sandbox" in json.dumps(result.output)


def test_code_under_test_cannot_start_processes(registry, workspace):
    (workspace / "tests" / "test_spawn.py").write_text(
        "import subprocess, sys\n\ndef test_spawn():\n"
        "    subprocess.run([sys.executable, '-c', 'print(1)'], check=True)\n")
    result = call(registry, "run_tests", target="tests/test_spawn.py")
    assert result.ok and result.output["failed"] == 1 and "sandbox" in json.dumps(result.output)


def test_code_under_test_cannot_write_outside(registry, workspace):
    outside = workspace.parent / "written.txt"
    (workspace / "tests" / "test_write.py").write_text(
        f"def test_write():\n    open({str(outside)!r}, 'w').write('x')\n")
    call(registry, "run_tests", target="tests/test_write.py")
    assert not outside.exists()


def test_hanging_test_is_stopped(workspace):
    from tools import ToolRegistry

    registry = ToolRegistry(workspace=workspace, timeout_s=3)
    (workspace / "tests" / "test_hang.py").write_text("import time\n\ndef test_hang():\n    time.sleep(600)\n")
    start = time.time()
    result = call(registry, "run_tests", target="tests/test_hang.py")
    assert not result.ok and "timed out" in result.error
    assert time.time() - start < 30


def test_infinite_loop_in_cli_is_stopped(workspace):
    from tools import ToolRegistry

    registry = ToolRegistry(workspace=workspace, timeout_s=3)
    path = workspace / "src" / "tinyledger" / "__main__.py"
    path.write_text("while True:\n    pass\n")
    start = time.time()
    assert not call(registry, "run_cli", args=["report"]).ok
    assert time.time() - start < 30


def test_catastrophic_regex_is_stopped(workspace):
    from tools import ToolRegistry

    registry = ToolRegistry(workspace=workspace, timeout_s=3)
    (workspace / "src" / "evil.txt").write_text("a" * 200 + "!\n")
    start = time.time()
    result = call(registry, "search_code", pattern="(a+)+$")
    assert not result.ok and "timed out" in result.error
    assert time.time() - start < 30


# ------------------------------------------------------------------ huge outputs

def test_huge_test_output_is_bounded(registry, workspace):
    (workspace / "tests" / "test_big.py").write_text(
        "def test_big():\n    print('y' * 5_000_000)\n    assert False, 'z' * 200_000\n")
    result = call(registry, "run_tests", target="tests/test_big.py")
    assert result.ok and result.output["failed"] == 1


def test_huge_cli_output_is_bounded(registry, workspace):
    (workspace / "src" / "tinyledger" / "__main__.py").write_text("print('x' * 3_000_000)\n")
    result = call(registry, "run_cli", args=["report"])
    assert result.ok and result.truncated is False or result.truncated is True  # bounded is checked in call()


def test_many_files_are_bounded(registry, workspace):
    many = workspace / "src" / "many"
    many.mkdir()
    for i in range(MAX_LIST_ENTRIES + 50):
        (many / f"f{i:04d}.txt").write_text("hit\n")
    assert call(registry, "list_files", path="src/many").truncated
    assert call(registry, "search_code", pattern="hit", max_results=200).truncated


def test_long_lines_are_bounded(registry, workspace):
    (workspace / "src" / "long.txt").write_text(("x" * 100_000 + "\n") * 50)
    assert call(registry, "read_file", path="src/long.txt").ok


# ------------------------------------------------------------------ malformed input

@pytest.mark.parametrize("arguments", [
    "", "null", "[]", "123", '"text"', "{", "{'path': 'README.md'}", "[" * 100_000 + "]" * 100_000,
    '{"path": "README.md", "path": 1}', '{"path": null}', '{"path": ["README.md"]}', '{"path": {"a": 1}}',
    "{\"path\": \"" + "a" * 1_000_000 + "\"}", '{"path": "README.md", "start_line": 0}',
    '{"path": "README.md", "start_line": -5}', '{"path": "README.md", "start_line": 1.5}',
    '{"path": "README.md", "start_line": true}', '{"path": "README.md", "start_line": 1e309}',
    '{"path": "README.md", "start_line": 5, "end_line": 2}', '{"path": "README.md", "start_line": 99999}',
], ids=lambda a: a[:40].encode("ascii", "replace").decode())  # short ids: pytest puts the id into an env variable
def test_read_file_malformed(registry, arguments):
    result = registry.execute("read_file", arguments)
    assert isinstance(result, ToolResult)
    if arguments not in ('{"path": "README.md", "path": 1}',):
        assert not result.ok, arguments[:80]
    assert result.error is None or len(result.error) < 3000


@pytest.mark.parametrize("name,arguments", [
    (None, "{}"), (123, "{}"), ("", "{}"), ("READ_FILE", '{"path": "README.md"}'), ("__init__", "{}"),
    ("_tool_read_file", '{"path": "README.md"}'), ("execute", "{}"), ("_resolve", '{"raw": "x"}'),
    ("search_code", '{"pattern": "("}'), ("search_code", '{"pattern": ""}'), ("search_code", '{"pattern": "x", "max_results": 0}'),
    ("search_code", '{"pattern": "x", "max_results": 100000}'), ("run_cli", '{"args": "report"}'),
    ("run_cli", '{"args": [1, 2]}'), ("run_cli", "{}"), ("run_tests", '{"target": 5}'), ("edit_file", '{"path": "src/tinyledger/money.py"}'),
    ("edit_file", '{"path": "src/tinyledger/money.py", "old_str": "", "new_str": "x"}'),
    ("list_files", '{"path": 7}'), ("list_files", '{"recursive": true}'),
])
def test_other_malformed_calls(registry, name, arguments):
    result = registry.execute(name, arguments)
    assert isinstance(result, ToolResult) and not result.ok and result.error


def test_arguments_as_dict_are_accepted(registry):
    assert registry.execute("read_file", {"path": "README.md"}).ok


def test_every_call_is_traced(registry):
    call(registry, "read_file", path="README.md")
    call(registry, "read_file", path="../secrets/canary.txt")
    registry.execute("nope", "{")
    assert len(registry.trace) == 3
    for entry in registry.trace:
        assert {"tool", "arguments", "ok", "error", "truncated", "duration_s"} <= set(entry)
    assert [e["ok"] for e in registry.trace] == [True, False, False]
