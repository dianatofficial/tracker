"""Publish the 50 packages that block the most other top-500 installs for each target.

    python scripts/build_blockers.py data/coverage.json _site/data/blockers.json

A top-500 package's whole-tree install result (`install` in coverage.json) lists the packages in its tree that have
no wheel there (`source` or `missing`). This counts, per target, how many top-500 trees each of those blocks. A
package doesn't count as blocking its own tree: that's its own missing wheel, which most-wanted.json already ranks,
so this list is the dependencies that hold other packages back. Only checked trees count (`not_checked` is nothing),
and only targets with checked trees are written.

Built at publish time; the generated file is not committed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

if __package__:  # imported as scripts.build_blockers (the tests)
    from . import install_results
else:  # run as python scripts/build_blockers.py
    import install_results

SCAN_SCHEMA = 1
GAP = ("source", "missing")
TOP = 50
EXAMPLES = 3
SAFE_NAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$")


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def build(coverage_path: Path, out: Path) -> int:
    scan = json.loads(coverage_path.read_text(encoding="utf-8"))
    if scan.get("schema") != SCAN_SCHEMA:
        sys.exit(f"build_blockers: coverage.json schema {scan.get('schema')!r}, expected {SCAN_SCHEMA}")
    # Only the top 500 carry `install`; ranked so each blocker's examples are the most-used trees it blocks.
    packages = sorted(
        (p for p in scan["packages"] if isinstance(p.get("install"), dict)),
        key=lambda p: p.get("rank", float("inf")),
    )
    targets: dict[str, dict] = {}
    total = 0

    for label in (target["label"] for target in scan["targets"]):
        checked = 0
        blocked: dict[str, dict] = {}  # canonical name -> {"name", "trees": [package name, ...]}
        for package in packages:
            result = package["install"].get(label)
            if not isinstance(result, dict) or result.get("status") not in install_results.CHECKED:
                continue
            checked += 1
            root = canonical(package["name"])
            seen = set()
            for blocker in result.get("blockers") or []:
                name = blocker.get("name") if isinstance(blocker, dict) else None
                if not isinstance(name, str) or blocker.get("status") not in GAP or not SAFE_NAME.fullmatch(name):
                    continue
                key = canonical(name)
                if key == root or key in seen:  # its own tree, or the same blocker by another route
                    continue
                seen.add(key)
                blocked.setdefault(key, {"name": name, "trees": []})["trees"].append(package["name"])
        if not checked:
            continue

        ranked = sorted(blocked.values(), key=lambda b: (-len(b["trees"]), canonical(b["name"])))[:TOP]
        targets[label] = {
            "checked": checked,
            "blockers": [
                {"name": b["name"], "count": len(b["trees"]), "examples": b["trees"][:EXAMPLES]} for b in ranked
            ],
        }
        total += len(ranked)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"generated": scan["generated"], "targets": targets}, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return total


if __name__ == "__main__":
    coverage, out = (Path(p) for p in sys.argv[1:3])
    print(f"blockers: {build(coverage, out)} entries in {out}")
