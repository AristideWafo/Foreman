import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "annotate_failures.py"

REPORT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="3">
  <testcase classname="tests.test_a" name="test_ok"/>
  <testcase classname="tests.test_a" name="test_ko">
    <failure message="assert 1 == 2">ligne 1
assert 1 == 2
100% faux</failure>
  </testcase>
  <testcase classname="tests.test_b" name="test_boom">
    <error message="RuntimeError">Traceback...</error>
  </testcase>
</testsuite></testsuites>
"""


def run(tmp_path: Path, content: str) -> list[str]:
    report = tmp_path / "junit.xml"
    report.write_text(content)
    out = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), str(report)], capture_output=True, text=True, check=True
    )
    return out.stdout.splitlines()


def test_each_failure_and_error_becomes_one_escaped_annotation(tmp_path: Path) -> None:
    lines = run(tmp_path, REPORT)
    assert len(lines) == 2
    assert lines[0].startswith("::error title=Test en échec : tests.test_a::test_ko::")
    assert "assert 1 == 2" in lines[0]
    assert "%0A" in lines[0]  # sauts de ligne échappés : une annotation = une seule ligne
    assert "100%25 faux" in lines[0]  # `%` échappé
    assert "test_b::test_boom" in lines[1]


def test_a_green_report_produces_no_annotation(tmp_path: Path) -> None:
    green = REPORT.replace("<failure", "<skipped").replace("</failure>", "</skipped>")
    green = green.replace("<error", "<skipped").replace("</error>", "</skipped>")
    assert run(tmp_path, green) == []
