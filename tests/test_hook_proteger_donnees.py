"""Le hook qui protège ``MPA_DATA_DIR`` des sessions Code (AN1-1, D13), joué comme
Claude Code le joue : un processus, l'appel en JSON sur l'entrée standard, le code de
sortie (2 = refusé)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "hooks" / "proteger_donnees.py"


def run(
    tmp_path: Path,
    call: object,
    *,
    env_file: str | None = None,
    env: dict[str, str] | None = None,
    raw: str | None = None,
) -> subprocess.CompletedProcess[str]:
    project = tmp_path / "projet"
    project.mkdir(exist_ok=True)
    if env_file is not None:
        (project / ".env").write_text(env_file, encoding="utf-8")
    environment = {
        k: v
        for k, v in os.environ.items()
        if k not in ("MPA_DATA_DIR", "MPA_HOOK_AUTORISER_DONNEES")
    }
    environment["CLAUDE_PROJECT_DIR"] = str(project)
    environment.update(env or {})
    if env and "HOME" in env and "USERPROFILE" not in env:
        # sous Windows, ``~`` se lit dans USERPROFILE, et HOME ne compte pas
        environment["USERPROFILE"] = env["HOME"]
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=raw if raw is not None else json.dumps(call),
        capture_output=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )


WIN = "MPA_DATA_DIR=C:/Users/x/mpa-data\n"
POSIX = 'MPA_DATA_DIR="/data/mpa"\n'


def file_call(tool: str, path: str, cwd: str = "") -> dict[str, object]:
    key = {"NotebookEdit": "notebook_path", "Glob": "path", "Grep": "path"}.get(
        tool, "file_path"
    )
    return {"tool_name": tool, "tool_input": {key: path}, "cwd": cwd}


@pytest.mark.parametrize(
    "tool", ["Read", "Write", "Edit", "NotebookEdit", "Glob", "Grep"]
)
def test_file_tools_under_the_data_dir_are_refused(tmp_path: Path, tool: str) -> None:
    result = run(
        tmp_path, file_call(tool, "C:\\Users\\x\\mpa-data\\raw\\1.zip"), env_file=WIN
    )
    assert result.returncode == 2
    assert "Refusé" in result.stderr


@pytest.mark.parametrize(
    ("path", "cwd", "code"),
    [
        ("C:/Users/x/mpa-data", "", 2),
        ("c:\\users\\X\\MPA-DATA\\interim\\a.json", "", 2),
        ("C:/Users/x/mpa-data2/a.json", "", 0),
        ("C:/Users/x/mpa-data/../projet/a.py", "", 0),
        ("raw\\1.zip", "C:\\Users\\x\\mpa-data", 2),
        ("src\\a.py", "C:\\Users\\x\\projet", 0),
    ],
)
def test_windows_paths(tmp_path: Path, path: str, cwd: str, code: int) -> None:
    assert run(tmp_path, file_call("Write", path, cwd), env_file=WIN).returncode == code


@pytest.mark.parametrize(
    ("path", "cwd", "code"),
    [
        ("/data/mpa/raw/x", "", 2),
        ("/data/mpa-other/x", "", 0),
        ("/data/x/../mpa/raw", "", 2),
        ("raw/x", "/data/mpa", 2),
        ("src/a.py", "/home/u/projet", 0),
    ],
)
def test_posix_paths(tmp_path: Path, path: str, cwd: str, code: int) -> None:
    assert (
        run(tmp_path, file_call("Edit", path, cwd), env_file=POSIX).returncode == code
    )


def test_glob_and_grep_without_path_use_the_working_directory(tmp_path: Path) -> None:
    for tool in ("Glob", "Grep"):
        call = {
            "tool_name": tool,
            "tool_input": {"pattern": "*.json"},
            "cwd": "/data/mpa/raw",
        }
        assert run(tmp_path, call, env_file=POSIX).returncode == 2
    call = {
        "tool_name": "Glob",
        "tool_input": {"pattern": "/data/mpa/**/*.json"},
        "cwd": "/home/u",
    }
    assert run(tmp_path, call, env_file=POSIX).returncode == 2


@pytest.mark.parametrize(
    ("command", "code"),
    [
        ("ls /data/mpa/raw", 2),
        ("echo $MPA_DATA_DIR", 2),
        ("Get-ChildItem $env:MPA_DATA_DIR", 2),
        ("Get-ChildItem $env:mpa_data_dir", 2),
        ("uv run mperf   ingest", 2),
        ("uv run mperf ingest", 2),
        ("uv run mperf backtest m.json --curve c.csv", 2),
        ("just backtest courbe.csv", 2),
        ("just ingest", 2),
        ("just -f justfile ingest", 2),
        ("just --justfile justfile backtest courbe.csv", 2),
        ("uv run python -m mountain_perf.cli ingest", 2),
        ("just.exe ingest", 2),
        ("just.exe backtest courbe.csv", 2),
        ("mperf.exe ingest", 2),
        (".venv\\Scripts\\mperf.exe ingest", 2),
        ("uv run mperf.exe ingest", 2),
        ("& .venv/Scripts/mperf.exe backtest m.json --curve c.csv", 2),
        ('& "C:/x/.venv/Scripts/mperf.exe" ingest', 2),
        ('uv run mperf "ingest"', 2),
        ("just 'ingest'", 2),
        ("JUST INGEST", 2),
        ("Just.EXE Backtest courbe.csv", 2),
        ("uv run mperf tables", 2),
        ("uv run --extra analyse mperf tables", 2),
        ("uv run python -m mountain_perf.cli tables", 2),
        ("just process", 2),
        ("just.exe process", 2),
        ("uv run pytest tests/test_analyse_tables.py", 0),
        ("just processing-notes", 0),
        ("uv run pytest tests/test_ingest_export.py", 0),
        ("uv run pytest -k 'ingest'", 0),
        ("uv run mperf.exe profile tests/fixtures/mini_11.gpx", 0),
        ("adjust ingest", 0),
        ("justify backtest", 0),
        ("mperfx ingest", 0),
        ("just ingestion-notes", 0),
        ("just test", 0),
        ("just check", 0),
        ("uv run mperf profile tests/fixtures/mini_11.gpx", 0),
        ("git status", 0),
        ("just ui", 2),
        ("just.exe ui", 2),
        ("JUST UI", 2),
        ('just "ui"', 2),
        ("just --dotenv-path .env ui", 2),
        ("just uiq", 0),
        ("just ui-notes", 0),
        ("uv run streamlit run src/mountain_perf/ui/app.py", 2),
        ("uv run --extra tableau streamlit run src/mountain_perf/ui/app.py", 2),
        ("streamlit.exe run app.py", 2),
        (".venv\\Scripts\\streamlit.exe run app.py", 2),
        ("python -m streamlit run app.py", 2),
        ('"streamlit" run app.py', 2),
        ("streamlit 'run' app.py", 2),
        ("STREAMLIT RUN app.py", 2),
        ("streamlit --log_level debug run app.py", 2),
        ("streamlit hello", 0),
        ("streamlit runner", 0),
        ("uv pip show streamlit", 0),
    ],
)
def test_shell_commands(tmp_path: Path, command: str, code: int) -> None:
    for tool in ("Bash", "PowerShell"):
        call = {"tool_name": tool, "tool_input": {"command": command}, "cwd": "/home/u"}
        assert run(tmp_path, call, env_file=POSIX).returncode == code, (tool, command)


@pytest.mark.parametrize(
    "command",
    [
        "dir C:\\Users\\x\\mpa-data",
        "ls /c/Users/x/mpa-data/raw",
        "ls /mnt/c/Users/x/mpa-data",
        "type c:/users/X/MPA-DATA/raw/a.json",
        "Get-ChildItem C:\\Users\\x/mpa-data/raw",
        "Get-ChildItem C:/Users/x\\mpa-data",
        "dir C:\\\\Users\\\\x\\\\mpa-data",
    ],
)
def test_shell_names_the_windows_data_dir_in_any_form(
    tmp_path: Path, command: str
) -> None:
    call = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": ""}
    assert run(tmp_path, call, env_file=WIN).returncode == 2


def test_without_known_data_dir_only_writing_commands_are_refused(
    tmp_path: Path,
) -> None:
    assert run(tmp_path, file_call("Write", "/data/mpa/raw/x")).returncode == 0
    call = {"tool_name": "Bash", "tool_input": {"command": "uv run mperf ingest"}}
    assert run(tmp_path, call).returncode == 2


def test_environment_wins_over_env_file(tmp_path: Path) -> None:
    call = file_call("Write", "/autre/raw/x")
    assert (
        run(tmp_path, call, env_file=POSIX, env={"MPA_DATA_DIR": "/autre"}).returncode
        == 2
    )
    assert run(tmp_path, call, env_file=POSIX).returncode == 0


def test_bypass_lets_everything_through(tmp_path: Path) -> None:
    env = {"MPA_HOOK_AUTORISER_DONNEES": "1"}
    assert (
        run(
            tmp_path, file_call("Write", "/data/mpa/raw/x"), env_file=POSIX, env=env
        ).returncode
        == 0
    )


def test_unreadable_call_is_refused(tmp_path: Path) -> None:
    assert run(tmp_path, None, raw="{non json").returncode == 2
    assert run(tmp_path, None, raw="[1]").returncode == 2


def test_monitor_commands_are_checked_like_shell_commands(tmp_path: Path) -> None:
    for command, code in (
        ("uv run mperf ingest", 2),
        ("tail -f /data/mpa/interim/activities/report.json", 2),
        ("uv run pytest -q", 0),
    ):
        call = {"tool_name": "Monitor", "tool_input": {"command": command}}
        assert run(tmp_path, call, env_file=POSIX).returncode == code, command
    socket = {"tool_name": "Monitor", "tool_input": {"ws": {"url": "wss://x/y"}}}
    assert run(tmp_path, socket, env_file=POSIX).returncode == 0


def test_lsp_reads_every_text_value_as_a_path(tmp_path: Path) -> None:
    call = {
        "tool_name": "LSP",
        "tool_input": {"operation": "hover", "filePath": "/data/mpa/raw/a.py"},
        "cwd": "/home/u/projet",
    }
    assert run(tmp_path, call, env_file=POSIX).returncode == 2
    call["tool_input"] = {"operation": "hover", "filePath": "src/a.py"}
    assert run(tmp_path, call, env_file=POSIX).returncode == 0
    call["tool_input"] = {
        "operation": "workspaceSymbol",
        "filePath": "src/a.py",
        "query": "/data/mpa/raw/x",
    }
    assert run(tmp_path, call, env_file=POSIX).returncode == 2


@pytest.mark.parametrize(
    ("tool", "tool_input", "cwd", "code"),
    [
        ("Grep", {"pattern": "activityId", "path": "C:/Users/x"}, "", 2),
        ("Grep", {"pattern": "activityId"}, "C:\\Users\\x", 2),
        ("Grep", {"pattern": "x", "path": "C:/Users/x/projet"}, "", 0),
        ("Grep", {"pattern": "x", "path": ".."}, "C:/Users/x/projet", 2),
        ("Glob", {"pattern": "mpa-data/raw/**/*.zip", "path": "C:/Users/x"}, "", 2),
        ("Glob", {"pattern": "../*/raw/*.zip"}, "C:/Users/x/projet", 2),
        ("Glob", {"pattern": "C:/Users/*/mpa-data/**"}, "C:/Users/x/projet", 2),
        ("Glob", {"pattern": "**/*.py"}, "C:/Users/x/projet", 0),
        ("Glob", {"pattern": "src/**/*.py", "path": "C:/Users/x/projet"}, "", 0),
        ("Glob", {"pattern": "../a.txt"}, "C:/Users/x/projet", 0),
        ("Glob", {"pattern": "../mpa-data/raw/1.zip"}, "C:/Users/x/projet", 2),
        ("Glob", {"pattern": "*/../../mpa-data/raw/*.zip"}, "C:/Users/x/projet", 2),
        ("Glob", {"pattern": "src/*/../*.py"}, "C:/Users/x/projet", 0),
    ],
)
def test_searches_that_reach_the_data_dir_are_refused(
    tmp_path: Path, tool: str, tool_input: dict[str, str], cwd: str, code: int
) -> None:
    call = {"tool_name": tool, "tool_input": tool_input, "cwd": cwd}
    assert run(tmp_path, call, env_file=WIN).returncode == code


def test_the_data_dir_is_taken_as_just_passes_it(tmp_path: Path) -> None:
    """``~`` développé ; un chemin relatif pris depuis la racine du projet, le dossier
    où ``just`` lance ``mperf``."""
    home = tmp_path / "maison"
    env = {"HOME": str(home), "USERPROFILE": str(home)}
    inside = file_call("Read", str(home / "mpa-data" / "raw" / "1.zip"))
    assert (
        run(tmp_path, inside, env_file="MPA_DATA_DIR=~/mpa-data\n", env=env).returncode
        == 2
    )
    relative = file_call("Read", str(tmp_path / "mpa-data" / "raw" / "1.zip"))
    assert (
        run(tmp_path, relative, env_file="MPA_DATA_DIR=../mpa-data\n").returncode == 2
    )
    elsewhere = file_call("Read", str(tmp_path / "projet" / "src" / "a.py"))
    assert (
        run(tmp_path, elsewhere, env_file="MPA_DATA_DIR=../mpa-data\n").returncode == 0
    )


def test_an_env_file_with_a_byte_order_mark_is_read(tmp_path: Path) -> None:
    project = tmp_path / "projet"
    project.mkdir()
    (project / ".env").write_bytes(b"\xef\xbb\xbf" + POSIX.encode("utf-8"))
    assert run(tmp_path, file_call("Read", "/data/mpa/raw/x")).returncode == 2


@pytest.mark.parametrize(
    ("command", "code"),
    [
        ("ls C:/Users/x/mpa-data2", 0),
        ("ls C:/Users/x/mpa-data_old/a", 0),
        ("ls C:/Users/x/mpa-data-old", 0),
        ("ls C:/Users/x/mpa-data.bak", 0),
        ("ls C:\\Users\\x/mpa-data2", 0),
        ("ls C:/Users/x/mpa-data", 2),
        ('ls "C:/Users/x/mpa-data"', 2),
        ("ls C:/Users/x/mpa-data/raw", 2),
        ("dir C:\\Users\\x\\mpa-data\\", 2),
    ],
)
def test_a_longer_folder_name_is_not_the_data_dir(
    tmp_path: Path, command: str, code: int
) -> None:
    call = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": ""}
    assert run(tmp_path, call, env_file=WIN).returncode == code


@pytest.mark.parametrize(
    "env_file",
    [
        "export MPA_DATA_DIR=/data/mpa\n",
        "MPA_DATA_DIR=/data/mpa # le dossier des données\n",
        "MPA_DATA_DIR='/data/mpa' # commentaire\n",
        '  MPA_DATA_DIR = "/data/mpa"\n',
        "# MPA_DATA_DIR=/autre\nMPA_DATA_DIR=/data/mpa\n",
    ],
)
def test_env_file_lines_are_read_as_just_reads_them(
    tmp_path: Path, env_file: str
) -> None:
    for call in (
        file_call("Read", "/data/mpa/raw/acquisition.json"),
        {"tool_name": "Bash", "tool_input": {"command": "cat /data/mpa/raw/x"}},
        {"tool_name": "Grep", "tool_input": {"pattern": "x", "path": "/data/mpa"}},
    ):
        assert run(tmp_path, call, env_file=env_file).returncode == 2, call


@pytest.mark.parametrize(
    "env_file", ["MPA_DATA_DIR=\n", 'MPA_DATA_DIR="/data/mpa\n', "MPA_DATA_DIR= # x\n"]
)
def test_env_file_naming_the_variable_without_a_value_refuses_everything(
    tmp_path: Path, env_file: str
) -> None:
    harmless = file_call("Read", "/home/u/projet/src/a.py")
    result = run(tmp_path, harmless, env_file=env_file)
    assert result.returncode == 2
    assert "sans valeur lisible" in result.stderr


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [
        ("Grep", {"pattern": "x", "path": "~/mpa-data"}),
        ("Grep", {"pattern": "x", "path": "/c/Users/x/mpa-data/raw"}),
        ("Glob", {"pattern": "**/*.json", "path": "/mnt/c/Users/x/mpa-data"}),
        ("Glob", {"pattern": "~/mpa-data/raw/*.zip"}),
        ("LSP", {"operation": "hover", "filePath": "~/mpa-data/raw/a.py"}),
        ("Read", {"file_path": "/c/users/x/MPA-DATA/raw/1.zip"}),
    ],
)
def test_paths_are_read_as_claude_code_reads_them(
    tmp_path: Path, tool: str, tool_input: dict[str, str]
) -> None:
    call = {"tool_name": tool, "tool_input": tool_input, "cwd": "C:/Users/x/projet"}
    env = {"HOME": "C:/Users/x"}
    assert run(tmp_path, call, env_file=WIN, env=env).returncode == 2


@pytest.mark.parametrize(
    ("command", "code"),
    [
        ("ls ~/mpa-data/raw", 2),
        ("cat $HOME/mpa-data/raw/acquisition.json", 2),
        ("cat ${HOME}/mpa-data", 2),
        ("ls ~/mpa-data2", 0),
        ("ls ~/projet", 0),
    ],
)
def test_commands_that_reach_the_data_dir_from_home(
    tmp_path: Path, command: str, code: int
) -> None:
    call = {"tool_name": "Bash", "tool_input": {"command": command}}
    env = {"HOME": "/home/u"}
    env_file = "MPA_DATA_DIR=/home/u/mpa-data\n"
    assert run(tmp_path, call, env_file=env_file, env=env).returncode == code


@pytest.mark.parametrize(
    "command",
    [
        "Get-ChildItem $env:USERPROFILE\\mpa-data",
        "type %USERPROFILE%\\mpa-data\\raw\\a.json",
        "ls ~/mpa-data/raw",
        "Get-ChildItem ${env:USERPROFILE}\\mpa-data",
        'ls "$USERPROFILE/mpa-data"',
        "ls ${USERPROFILE}/mpa-data/raw",
        "Get-ChildItem $env:USERPROFILE/mpa-data\\raw",
    ],
)
def test_windows_commands_from_home(tmp_path: Path, command: str) -> None:
    call = {"tool_name": "PowerShell", "tool_input": {"command": command}}
    env = {"HOME": "C:/Users/x"}
    assert run(tmp_path, call, env_file=WIN, env=env).returncode == 2


@pytest.mark.parametrize(
    "call",
    [
        {"tool_name": "Read", "tool_input": ["/data/mpa/raw/x"]},
        {"tool_name": "Read", "tool_input": None},
        {"tool_name": "Read", "tool_input": {"file_path": ["/data/mpa/raw/x"]}},
        {"tool_name": "Write", "tool_input": {"file_path": 3}},
        {"tool_name": "Bash", "tool_input": {"command": ["cat", "/data/mpa/x"]}},
        {"tool_name": "Grep", "tool_input": {"pattern": "x", "path": ["/data/mpa"]}},
        {"tool_name": "Glob", "tool_input": {"pattern": ["/data/mpa/*"]}},
        {"tool_name": "Read", "tool_input": {"file_path": "a.py"}, "cwd": ["/data"]},
    ],
)
def test_an_unexpected_input_of_a_checked_tool_is_refused(
    tmp_path: Path, call: dict[str, object]
) -> None:
    assert run(tmp_path, call, env_file=POSIX).returncode == 2


def test_the_call_is_read_as_utf8_whatever_the_locale(tmp_path: Path) -> None:
    """Claude Code envoie de l'UTF-8 : un chemin accentué se lit tel quel, même quand
    l'encodage local en lirait un autre, et la raison du refus s'écrit en UTF-8."""
    call = file_call("Read", "/data/données/raw/x")
    result = run(
        tmp_path,
        None,
        env_file="MPA_DATA_DIR=/data/données\n",
        env={"PYTHONIOENCODING": "latin-1"},
        raw=json.dumps(call, ensure_ascii=False),
    )
    assert result.returncode == 2
    assert "Refusé" in result.stderr


def test_other_tools_pass(tmp_path: Path) -> None:
    call = {"tool_name": "WebFetch", "tool_input": {"url": "/data/mpa"}}
    assert run(tmp_path, call, env_file=POSIX).returncode == 0


def test_settings_declare_the_hook_for_every_tool_and_fail_closed() -> None:
    """La déclaration de ``.claude/settings.json`` : chaque outil que le script
    contrôle, appel sans shell par ``uv``, et un hook qui ne démarre pas, dépasse son
    délai ou rend un code inattendu refuse l'appel (``onFailure``)."""
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text("utf-8"))
    (entry,) = settings["hooks"]["PreToolUse"]
    assert set(entry["matcher"].split("|")) == {
        "Bash",
        "PowerShell",
        "Monitor",
        "LSP",
        "Read",
        "Write",
        "Edit",
        "NotebookEdit",
        "Glob",
        "Grep",
    }
    (hook,) = entry["hooks"]
    assert hook["type"] == "command"
    assert hook["command"] == "uv"
    assert hook["args"][-1] == "${CLAUDE_PROJECT_DIR}/scripts/hooks/proteger_donnees.py"
    assert hook["onFailure"] == "block"
