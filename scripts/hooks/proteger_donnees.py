"""Hook ``PreToolUse`` de Claude Code : la session ne touche pas au dossier des données
(AN1-1, D13 ; règles 1 et 6 de ``CLAUDE.md``).

Lu sur l'entrée standard : l'appel d'outil en JSON (``tool_name``, ``tool_input``,
``cwd``). Refusé (code 2, raison sur la sortie d'erreur) :

- un outil de fichiers (``Read``, ``Write``, ``Edit``, ``NotebookEdit``) dont le chemin
  est sous ``MPA_DATA_DIR`` ; ``LSP``, dont toute valeur de texte se lit comme un
  chemin ;
- une recherche (``Glob``, ``Grep``) dont le dossier parcouru (``path``, sinon le
  dossier courant ; pour ``Glob``, prolongé par la partie fixe du motif) est sous
  ``MPA_DATA_DIR`` ou le contient ;
- une commande (``Bash``, ``PowerShell``, ``Monitor``) qui nomme ce dossier, sa
  variable, ou une commande qui écrit dans les données (``mperf ingest``,
  ``mperf backtest``, ``mperf tables``, ``mperf q1``, ``just ingest``,
  ``just backtest``, ``just process``, ``just q1``, ``just ui``, options de ``just``
  comprises, et ``python -m mountain_perf.cli`` suivi de ``ingest``, ``backtest``,
  ``tables``, ``process`` ou ``q1`` ; sans casse, ``mperf.exe`` et ``just.exe`` compris,
  sous-commande entre guillemets comprise ; une recette ``ui-…``, ``process-…`` ou
  ``q1-…`` est une autre recette) ;
- une commande qui lance l'interface (M5, ``0016``), qui lit et écrit les données :
  ``streamlit run`` sous toutes ses formes (``streamlit.exe``, ``python -m
  streamlit``, ``uv run streamlit``, guillemets, casse, options avant ``run``).

``MPA_DATA_DIR`` vient de l'environnement, sinon du ``.env`` à la racine du projet
(``CLAUDE_PROJECT_DIR``, lu en UTF-8, marque d'ordre des octets admise ; ``export`` en
tête, valeur entre guillemets ou commentaire après `` #`` admis, comme ``just`` le lit),
et se prend comme ``just`` le transmet à ``config.data_dir()`` : ``~`` développé, un
chemin relatif pris depuis la racine du projet (le dossier où ``just`` lance ``mperf``).
Un ``.env`` qui nomme la variable sans valeur lisible refuse tout appel contrôlé. Les
chemins des outils se lisent comme Claude Code les lit : ``~`` développé, et, sous
Windows, ``/c/x`` et ``/mnt/c/x`` pour ``C:/x`` ; une commande qui écrit le dossier
depuis le dossier personnel (``~/…``, ``$HOME/…``, ``${HOME}/…``,
``$env:USERPROFILE/…``, ``${env:USERPROFILE}/…``, ``$USERPROFILE/…``,
``${USERPROFILE}/…``, ``%USERPROFILE%/…``) le nomme aussi ;
dans une commande, les séparateurs sont des barres obliques ou inverses, mêlées ou
non. Sans dossier de données connu, seules les commandes qui écrivent dans les données,
ou qui nomment ``MPA_DATA_DIR``, sont refusées. Toute erreur du hook refuse l'appel
(code 2), et une entrée inattendue (un ``tool_input`` qui n'est pas un objet, un champ
lu qui n'est ni un texte ni absent) en est une : un hook qui plante ne doit pas laisser
passer ; ``.claude/settings.json`` y ajoute ``"onFailure": "block"`` (Claude Code
2.1.295 ou plus récent), pour un hook qui ne démarre pas ou dépasse son délai.
``MPA_HOOK_AUTORISER_DONNEES=1``, posé par rdw dans l'environnement de Claude Code pour
une mission bornée, lève le contrôle ; en cas de panne du hook, ``{"disableAllHooks":
true}`` dans ``.claude/settings.local.json`` (personnel, ignoré par git) le coupe.

Un garde-fou, pas un bac à sable : une commande de shell qui atteint les données sans
les nommer (un chemin relatif, un ``grep -r`` lancé d'un dossier parent) n'est pas vue,
ni un outil absent de la liste ci-dessus. Le nom de la variable est cherché sans casse
dans toute la commande : un dossier temporaire nommé ``mpa_data_dir`` (celui de
``tests/conftest.py``) fait aussi refuser la commande qui le nomme ; ``Read`` le lit.

Bibliothèque standard seule ; ce script n'importe pas ``mountain_perf``.
"""

from __future__ import annotations

import io
import json
import ntpath
import os
import posixpath
import re
import sys
from pathlib import Path, PureWindowsPath

VARIABLE = "MPA_DATA_DIR"
BYPASS = "MPA_HOOK_AUTORISER_DONNEES"
FILE_TOOLS = {
    "Read": ("file_path",),
    "Write": ("file_path",),
    "Edit": ("file_path",),
    "NotebookEdit": ("notebook_path", "file_path"),
}
SEARCH_TOOLS = {"Glob", "Grep"}
SCANNED_TOOLS = {"LSP"}
SHELL_TOOLS = {"Bash", "PowerShell", "Monitor"}
WRITING_COMMANDS = re.compile(
    r"\b(?:mperf|just|mountain_perf\.cli)(?:\.exe)?[\"']?"
    r"(?:\s+-\S+(?:\s+[^\s-]\S*)?)*"
    r"\s+[\"']?(?:ingest|backtest|tables|process|q1|ui)(?![\w-])",
    re.IGNORECASE,
)
INTERFACE_COMMANDS = re.compile(
    r"\bstreamlit(?:\.exe)?[\"']?"
    r"(?:\s+-\S+(?:\s+[^\s-]\S*)?)*"
    r"\s+[\"']?run(?![\w-])",
    re.IGNORECASE,
)
HOME_PREFIXES = (
    "~",
    "$home",
    "${home}",
    "$env:userprofile",
    "${env:userprofile}",
    "$userprofile",
    "${userprofile}",
    "%userprofile%",
)
SEPARATORS = r"[/\\]+"
WILDCARDS = re.compile(r"[*?\[{]")
DRIVE = re.compile(r"^[A-Za-z]:[/\\]")
MOUNTED = re.compile(r"^(?:/mnt)?/([A-Za-z])(?=/|$)")


def _windows(*paths: str | None) -> bool:
    return any(DRIVE.match(p or "") for p in paths)


def _env_value(line: str) -> str | None:
    """La valeur que la ligne d'un ``.env`` donne à ``MPA_DATA_DIR``, ou ``None`` si
    elle ne la donne pas ; ``ValueError`` si elle la nomme sans valeur lisible."""
    text = line.strip()
    if text.startswith("export "):
        text = text[len("export ") :].lstrip()
    key, sep, raw = text.partition("=")
    if not sep or key.strip() != VARIABLE:
        return None
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        end = raw.find(raw[0], 1)
        value = raw[1:end] if end > 0 else ""
    else:
        value = re.split(r"(?:^|\s)#", raw, maxsplit=1)[0].strip()
    if not value:
        raise ValueError(f".env : {VARIABLE} sans valeur lisible")
    return value


def data_dir(project_dir: str | None) -> str | None:
    """Le dossier des données : l'environnement, sinon le ``.env`` ; ``~`` développé,
    un chemin relatif pris depuis ``project_dir``."""
    value = os.environ.get(VARIABLE, "").strip()
    if not value and project_dir:
        env_file = Path(project_dir) / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8-sig").splitlines():
                found = _env_value(line)
                if found is not None:
                    value = found
    if not value:
        return None
    value = os.path.expanduser(value)
    absolute = _windows(value) or value.startswith(("/", "\\"))
    if not absolute and project_dir:
        if _windows(project_dir):
            return ntpath.normpath(ntpath.join(project_dir, value))
        return posixpath.normpath(posixpath.join(project_dir, value))
    return value


def _forms(path: str) -> list[str]:
    """Les écritures d'un chemin qu'une commande peut employer, en minuscules : pour
    ``C:/x`` aussi ``/c/x`` et ``/mnt/c/x`` ; sous le dossier personnel, aussi
    ``~/…``, ``$HOME/…``, ``${HOME}/…``, ``$env:USERPROFILE/…``,
    ``${env:USERPROFILE}/…``, ``$USERPROFILE/…``, ``${USERPROFILE}/…`` et
    ``%USERPROFILE%/…``. Les séparateurs y sont des barres obliques ; ``_names`` admet
    aussi les barres inverses, mêlées ou non."""
    slash = path.replace("\\", "/").rstrip("/").lower()
    bases = {slash}
    match = re.match(r"^([a-z]):/(.*)$", slash)
    if match:
        drive, rest = match.groups()
        bases |= {f"/{drive}/{rest}", f"/mnt/{drive}/{rest}"}
    home = os.path.expanduser("~").replace("\\", "/").rstrip("/").lower()
    if home not in ("", "~") and slash.startswith(home + "/"):
        rest = slash[len(home) + 1 :]
        for prefix in HOME_PREFIXES:
            bases.add(f"{prefix}/{rest}")
    return sorted(b for b in bases if b)


def _names(command: str, root: str) -> bool:
    """La commande nomme-t-elle ``root`` (une de ses écritures, sans casse, chaque
    séparateur fait de barres obliques ou inverses, que ne prolonge pas un caractère
    de nom : ``mpa-data2`` n'est pas ``mpa-data``) ?"""
    lowered = command.lower()
    return any(
        re.search(
            SEPARATORS.join(map(re.escape, form.split("/"))) + r"(?![\w.\-])", lowered
        )
        for form in _forms(root)
    )


def _normal(path: str, cwd: str, windows: bool) -> str:
    if path.startswith("~"):
        path = os.path.expanduser(path)
    if windows:
        path = MOUNTED.sub(lambda m: f"{m.group(1)}:", path.replace("\\", "/"))
        full = PureWindowsPath(path.replace("\\", "/"))
        if not full.is_absolute():
            full = PureWindowsPath(cwd) / full
        return ntpath.normpath(str(full)).replace("\\", "/").rstrip("/").lower()
    joined = path if path.startswith("/") else posixpath.join(cwd or ".", path)
    return posixpath.normpath(joined).rstrip("/")


def _under(candidate: str, root: str, cwd: str) -> bool:
    """Le chemin ``candidate`` (relatif à ``cwd`` s'il n'est pas absolu) est-il
    ``root`` ou dessous ? Chemins Windows comparés sans casse ; ``..`` résolus."""
    windows = _windows(os.path.expanduser(candidate), root, cwd)
    path, top = _normal(candidate, cwd, windows), _normal(root, cwd, windows)
    return path == top or path.startswith(top + "/")


def _fixed_part(pattern: str) -> str:
    """Le dossier qu'un motif de ``Glob`` parcourt : sa partie avant le premier joker
    (``*``, ``?``, ``[``, ``{``), coupée à une limite de dossier, remontée d'autant de
    niveaux que le reste du motif compte de ``..``."""
    parts = pattern.replace("\\", "/").split("/")
    fixed: list[str] = []
    for part in parts:
        if WILDCARDS.search(part):
            break
        fixed.append(part)
    climbs = parts[len(fixed) :].count("..")
    return "/".join(fixed + [".."] * climbs) or "."


def _join(base: str, relative: str) -> str:
    if _windows(relative) or relative.startswith(("/", "\\", "~")) or not base:
        return relative
    if _windows(base):
        return ntpath.join(base, relative)
    return posixpath.join(base, relative)


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _text(value: object, name: str) -> str:
    """Un champ lu : un texte, ou absent ; toute autre valeur est une erreur."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{name} n'est pas un texte")
    return value


def decide(call: dict[str, object], root: str | None) -> str | None:
    """La raison du refus, ou ``None`` si l'appel passe ; ``ValueError`` sur une
    entrée inattendue d'un outil contrôlé."""
    tool = call.get("tool_name")
    if not (
        tool in SHELL_TOOLS
        or tool in FILE_TOOLS
        or tool in SCANNED_TOOLS
        or tool in SEARCH_TOOLS
    ):
        return None
    tool_input = call.get("tool_input")
    if not isinstance(tool_input, dict):
        raise ValueError("tool_input n'est pas un objet")
    cwd = _text(call.get("cwd"), "cwd")
    if tool in SHELL_TOOLS:
        command = _text(tool_input.get("command"), "command")
        if WRITING_COMMANDS.search(command):
            return "commande qui écrit dans les données : rdw la lance lui-même"
        if INTERFACE_COMMANDS.search(command):
            return "commande qui lance l'interface : rdw la lance lui-même"
        if VARIABLE.lower() in command.lower():
            return f"commande qui nomme {VARIABLE}"
        if root and _names(command, root):
            return "commande qui nomme le dossier des données"
        return None
    if not root:
        return None
    if tool in FILE_TOOLS or tool in SCANNED_TOOLS:
        if tool in FILE_TOOLS:
            paths = [_text(tool_input.get(key), key) for key in FILE_TOOLS[tool]]
        else:
            paths = _strings(tool_input)
        for path in paths:
            if path and _under(path, root, cwd):
                return f"{tool} sous le dossier des données"
        return None
    base = _text(tool_input.get("path"), "path") or cwd
    pattern = _text(tool_input.get("pattern"), "pattern")
    if tool == "Glob" and pattern:
        if not WILDCARDS.search(pattern):
            if _under(_join(base, pattern), root, cwd):
                return f"{tool} sous le dossier des données"
            return None
        base = _join(base, _fixed_part(pattern))
    if base and (_under(base, root, cwd) or _under(root, base, cwd)):
        return f"{tool} sur un dossier qui est ou contient celui des données"
    return None


def main() -> int:
    """Lit l'appel en octets UTF-8 (ce que Claude Code envoie, quel que soit l'encodage
    local : sous Windows, un chemin accentué lu en cp1252 ne serait plus le même) et
    écrit sa raison en UTF-8."""
    try:
        if isinstance(sys.stderr, io.TextIOWrapper):
            sys.stderr.reconfigure(encoding="utf-8")
        if os.environ.get(BYPASS) == "1":
            return 0
        call = json.loads(sys.stdin.buffer.read() or b"{}")
        if not isinstance(call, dict):
            raise ValueError("appel d'outil illisible")
        reason = decide(call, data_dir(os.environ.get("CLAUDE_PROJECT_DIR")))
    except Exception as error:
        print(
            f"Refusé par le hook de protection des données (erreur : {error}).",
            file=sys.stderr,
        )
        return 2
    if reason is None:
        return 0
    print(
        f"Refusé : {reason}. La session Code ne lit ni n'écrit MPA_DATA_DIR "
        "(CLAUDE.md, règles 1 et 6) ; demande à rdw.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
