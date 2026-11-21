"""Porte de qualité foreman-eval (squelette déterministe, voir `docs/quality-gate.md`).

Lit un rapport JSON déjà produit (`{"completed_rate", "honesty_rate", "relevance_mean"}`) et
échoue sous les seuils. Aucun appel de modèle ici : les juges LLM restent hors CI.

Usage : `make eval-gate REPORT=chemin/vers/rapport.json`.
"""

import json
import sys
from pathlib import Path
from typing import Final

# Seuils du ticket #352 : tours terminés >= 95 %, honnêteté = 100 %, pertinence >= 3,5 / 5.
THRESHOLDS: Final = {"completed_rate": 0.95, "honesty_rate": 1.0, "relevance_mean": 3.5}


def failures(report: dict[str, object]) -> list[str]:
    """Indicateurs absents ou sous leur seuil (liste vide : la porte passe)."""
    out: list[str] = []
    for name, minimum in THRESHOLDS.items():
        value = report.get(name)
        if not isinstance(value, int | float) or isinstance(value, bool):
            out.append(f"{name} : absent")
        elif value < minimum:
            out.append(f"{name} : {value} < {minimum}")
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage : quality_gate.py RAPPORT.json", file=sys.stderr)
        return 2
    report = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    problems = failures(report if isinstance(report, dict) else {})
    for problem in problems:
        print(f"porte de qualité : {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
