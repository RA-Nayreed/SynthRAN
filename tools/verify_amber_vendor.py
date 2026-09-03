"""Verify the vendored Amber tree against its pinned upstream checkout."""
from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path


OPTIONAL_PLOTTING = """try:  # plotting is an optional analysis feature
    import matplotlib.pyplot as plt
    from matplotlib.patches import Wedge, Circle
except ImportError:  # headless model runs do not require matplotlib
    plt = None
    Wedge = Circle = None"""
UPSTREAM_PLOTTING = """import matplotlib.pyplot as plt
from matplotlib.patches import Wedge, Circle"""


def verify(repository: Path, upstream: Path) -> None:
    metadata = json.loads((repository / "third_party/amber/SOURCE.json").read_text(encoding="utf-8"))
    actual_commit = __import__("subprocess").check_output(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual_commit != metadata["vendored_commit"]:
        raise SystemExit(f"wrong upstream commit: {actual_commit}")
    failures = []
    for source in sorted((upstream / "amber").glob("*.py")):
        expected = source.read_text(encoding="utf-8")
        local = (repository / "amber" / source.name).read_text(encoding="utf-8")
        if source.name == "propagation.py":
            local = local.replace(OPTIONAL_PLOTTING, UPSTREAM_PLOTTING)
        if local != expected:
            failures.append("".join(difflib.unified_diff(expected.splitlines(True), local.splitlines(True), fromfile=f"upstream/{source.name}", tofile=f"vendored/{source.name}")))
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("upstream", type=Path)
    parser.add_argument("--repository", type=Path, default=Path(__file__).parents[1])
    arguments = parser.parse_args()
    verify(arguments.repository.resolve(), arguments.upstream.resolve())
