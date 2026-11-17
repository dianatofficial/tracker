"""Publish the 50 packages that block the most top-500 dependency trees for each target.

    python scripts/build_blockers.py data/coverage.json _site/data/blockers.json

Built at publish time; the generated file is not committed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCAN_SCHEMA = 1
GAP = ("source", "missing")
SAFE_NAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$")


def canonical(name: str) -> str:
    return name.lower().replace("_", "-")


def build(coverage_path: Path, out: Path) -> int:
    scan = json.loads(coverage_path.read_text(encoding="utf-8"))
    if scan.get("schema") != SCAN_SCHEMA:
        sys.exit(f"build_blockers: coverage.json schema {scan.get('schema')!r}, expected {SCAN_SCHEMA}")
    labels = [target["label"] for target in scan["targets"]]
    targets_data = {}
    total_entries = 0

    for label in labels:
        checked = 0
        blocker_map: dict[str, dict] = {}
        for package in scan["packages"]:
            inst = package.get("install", {}).get(label)
            if not inst or inst.get("status") == "not_checked":
                continue
            checked += 1
            seen_blockers = set()
            for blocker in inst.get("blockers", []):
                if blocker.get("status") in GAP:
                    b_name = blocker.get("name")
                    if not b_name or not isinstance(b_name, str) or not SAFE_NAME.fullmatch(b_name):
                        continue
                    b_key = canonical(b_name)
                    if b_key not in seen_blockers:
                        seen_blockers.add(b_key)
                        if b_key not in blocker_map:
                            blocker_map[b_key] = {"name": b_name, "packages": []}
                        blocker_map[b_key]["packages"].append(package["name"])

        # Sort by count desc, then name asc
        sorted_blockers = sorted(
            blocker_map.values(),
            key=lambda item: (-len(item["packages"]), item["name"].lower()),
        )
        top_50 = [
            {
                "name": item["name"],
                "count": len(item["packages"]),
                "examples": item["packages"][:3],
            }
            for item in sorted_blockers[:50]
        ]
        total_entries += len(top_50)
        targets_data[label] = {
            "checked": checked,
            "blockers": top_50,
        }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({
            "generated": scan["generated"],
            "targets": targets_data,
        }, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return total_entries


if __name__ == "__main__":
    coverage, out = (Path(p) for p in sys.argv[1:3])
    print(f"blockers: {build(coverage, out)} entries in {out}")
