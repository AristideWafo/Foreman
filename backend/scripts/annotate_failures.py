"""Transforme un rapport JUnit en annotations GitHub (`::error`).

Les journaux bruts d'un job ne sont pas toujours accessibles ; une annotation reste visible sur la
PR et par l'API des check-runs. Usage : python scripts/annotate_failures.py junit.xml
"""

import sys
import xml.etree.ElementTree as ET

MAX_LINES = 12


def escape(text: str) -> str:
    """Échappement des commandes de workflow GitHub."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def annotations(report: str) -> list[str]:
    root = ET.parse(report).getroot()  # noqa: S314
    lines: list[str] = []
    for case in root.iter("testcase"):
        for kind in ("failure", "error"):
            node = case.find(kind)
            if node is None:
                continue
            name = f"{case.get('classname', '')}::{case.get('name', '')}"
            detail = "\n".join((node.text or node.get("message") or "").splitlines()[-MAX_LINES:])
            title = escape(f"Test en échec : {name}")
            lines.append(f"::error title={title}::{escape(detail)}")
    return lines


def main() -> int:
    for line in annotations(sys.argv[1]):
        sys.stdout.write(line + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
