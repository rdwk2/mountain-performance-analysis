"""Écrit ``docs/DICTIONNAIRE_DONNEES.md`` depuis les docstrings des schémas.

Usage : ``just dictionary``. Le rendu est fait par
``mountain_perf.schemas._dictionary.render`` (sans E/S) ; ce script ne fait
qu'écrire, en UTF-8 et avec des fins de ligne LF quelle que soit la plateforme.
"""

from pathlib import Path

from mountain_perf.schemas._dictionary import render

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "DICTIONNAIRE_DONNEES.md"


def main() -> None:
    OUTPUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"-> {OUTPUT.relative_to(OUTPUT.parent.parent).as_posix()}")


if __name__ == "__main__":
    main()
