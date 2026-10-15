"""The Skin Profile page never prints "null" or "undefined": profile.js hands nothing null or
undefined to replaceChildren, append or textContent (the DOM would turn it into that text).
Rendered in Node with a stub DOM, once per branch: skin type from the answers, an assumed
skin type with the Sensitive indicator, no profile yet, a server error. Skipped if Node
isn't installed; no npm packages."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def test_the_profile_page_never_hands_null_or_undefined_to_the_dom():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js not installed")
    script = Path(__file__).with_name("frontend_profile_render.mjs")
    run = subprocess.run(
        [node, str(script), str(REPO)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.startswith("ok ")
