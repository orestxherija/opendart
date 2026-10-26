"""Run the offline Node harness (harness.mjs) against the built app pages.

The harness needs Node 20 or later and nothing else: no browser, packages, or network. The
test is skipped where ``node`` is not on PATH.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from opendart_mcp.apps.resources import CALENDAR_PAGE, FINANCIALS_PAGE, PEERS_PAGE

HARNESS = Path(__file__).with_name("harness.mjs")
NODE = shutil.which("node")
PAGES = {"financials": FINANCIALS_PAGE, "peers": PEERS_PAGE, "calendar": CALENDAR_PAGE}


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_app_pages_pass_the_node_harness(tmp_path):
    assert NODE is not None
    paths = []
    for app, page in PAGES.items():
        path = tmp_path / f"{app}.html"
        path.write_text(page, encoding="utf-8")
        paths.append(str(path))
    completed = subprocess.run(  # noqa: S603 - Node from PATH runs the repository harness on test-owned files
        [NODE, str(HARNESS), *paths], capture_output=True, text=True, timeout=60, check=False
    )
    report = completed.stdout + completed.stderr
    assert completed.returncode == 0, report
    assert " passed, 0 failed" in completed.stdout, report
    for app in PAGES:
        assert f"ok - {app}: handshake" in completed.stdout, report
