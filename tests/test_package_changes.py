"""Tests for recent wheel changes on package pages (scripts/build_pages.py, #115)."""

import html
import json
from pathlib import Path

import pytest

from scripts import build_pages, update_changes

TARGETS = [
    {"label": "3.14 win-arm64", "python": "3.14", "platform": "win-arm64"},
    {"label": "3.14 linux-x86_64", "python": "3.14", "platform": "linux-x86_64"},
    {"label": "3.13 musl-x86_64", "python": "3.13", "platform": "musl-x86_64"},
]


def make_package(name, rank=1, version="1.0.0", statuses=None):
    return {
        "rank": rank,
        "name": name,
        "version": version,
        "pure": False,
        "error": None,
        "results": statuses or ["wheel", "wheel", "wheel"],
    }


def make_scan(packages):
    return {
        "schema": 1,
        "wheelgap": "0.13.0",
        "generated": "2026-11-16T12:00:00Z",
        "targets": TARGETS,
        "packages": packages,
    }


def test_format_target():
    assert build_pages.format_target("3.14 win-arm64") == "Windows ARM64, Python 3.14"
    assert build_pages.format_target("3.14 linux-x86_64") == "Linux x86_64, Python 3.14"
    assert build_pages.format_target("3.13 musl-x86_64") == "Alpine x86_64, Python 3.13"
    assert build_pages.format_target("3.13 pyodide") == "Pyodide (browser), Python 3.13"
    assert build_pages.format_target("custom-platform") == "custom-platform"


def test_changes_render_in_order_with_target_formatting():
    pkg = make_package("demo")
    scan = make_scan([pkg])
    changes = [
        {"date": "2026-11-12", "target": "3.13 musl-x86_64", "action": "lost"},
        {"date": "2026-11-16", "target": "3.14 win-arm64", "action": "gained"},
    ]
    out = build_pages.page(pkg, scan, "3.14", changes=changes)

    assert '<section aria-labelledby="recent-changes">' in out
    assert '<h2 id="recent-changes">Recent changes</h2>' in out
    assert f"last {update_changes.KEEP_DAYS} days" in out

    # Newest first: 2026-11-16 must appear before 2026-11-12
    pos_16 = out.index("2026-11-16: gained a wheel for Windows ARM64, Python 3.14")
    pos_12 = out.index("2026-11-12: lost a wheel for Alpine x86_64, Python 3.13")
    assert pos_16 < pos_12


def test_empty_log_gives_no_section():
    pkg = make_package("demo")
    scan = make_scan([pkg])

    out_empty = build_pages.page(pkg, scan, "3.14", changes=[])
    assert 'aria-labelledby="recent-changes"' not in out_empty
    assert "Recent changes" not in out_empty

    out_none = build_pages.page(pkg, scan, "3.14", changes=None)
    assert 'aria-labelledby="recent-changes"' not in out_none
    assert "Recent changes" not in out_none


def test_capped_at_ten_entries():
    pkg = make_package("demo")
    scan = make_scan([pkg])
    changes = [
        {"date": f"2026-11-{day:02d}", "target": "3.14 win-arm64", "action": "gained"}
        for day in range(1, 16)
    ]
    out = build_pages.page(pkg, scan, "3.14", changes=changes)

    assert out.count("gained a wheel for Windows ARM64, Python 3.14") == 10
    # Day 15 (newest) down to day 06 should be present (10 items), day 05 (oldest) should be dropped
    assert "2026-11-15:" in out
    assert "2026-11-06:" in out
    assert "2026-11-05:" not in out


def test_package_isolation():
    pkg1 = make_package("pkg-one")
    pkg2 = make_package("pkg-two")
    scan = make_scan([pkg1, pkg2])

    raw_changes = [
        {
            "date": "2026-11-16",
            "gained": [
                {"name": "pkg-one", "target": "3.14 win-arm64", "to": "wheel", "version": "1.0"},
            ],
            "lost": [
                {"name": "pkg-two", "target": "3.13 musl-x86_64", "from": "wheel", "version": "2.0"},
            ],
        }
    ]

    by_pkg = build_pages.changes_by_package(raw_changes)
    out1 = build_pages.page(pkg1, scan, "3.14", changes=by_pkg.get("pkg-one"))
    out2 = build_pages.page(pkg2, scan, "3.14", changes=by_pkg.get("pkg-two"))

    assert "Windows ARM64, Python 3.14" in out1
    assert "Alpine x86_64, Python 3.13" not in out1

    assert "Alpine x86_64, Python 3.13" in out2
    assert "Windows ARM64, Python 3.14" not in out2


def test_changes_escapes_html():
    pkg = make_package("demo")
    scan = make_scan([pkg])
    changes = [
        {"date": "2026-11-16<tag>", "target": "3.14 <custom>", "action": "gained&fun"},
    ]
    out = build_pages.page(pkg, scan, "3.14", changes=changes)

    assert "<tag>" not in out
    assert "&lt;tag&gt;" in out
    assert "<custom>" not in out
    assert "&lt;custom&gt;" in out


def test_build_integration_with_changes_json(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    site_dir = tmp_path / "_site"

    pkg1 = make_package("pkg-one")
    pkg2 = make_package("pkg-two")
    scan = make_scan([pkg1, pkg2])
    (data_dir / "coverage.json").write_text(json.dumps(scan), encoding="utf-8")

    changes_data = [
        {
            "date": "2026-11-16",
            "gained": [
                {"name": "pkg-one", "target": "3.14 win-arm64", "to": "wheel", "version": "1.0"},
            ],
            "lost": [],
        }
    ]
    (data_dir / "changes.json").write_text(json.dumps(changes_data), encoding="utf-8")

    count = build_pages.build(data_dir / "coverage.json", site_dir, notes_dir=None, root=tmp_path)
    assert count == 2

    page1_text = (site_dir / "p" / "pkg-one" / "index.html").read_text(encoding="utf-8")
    page2_text = (site_dir / "p" / "pkg-two" / "index.html").read_text(encoding="utf-8")

    assert '<section aria-labelledby="recent-changes">' in page1_text
    assert "2026-11-16: gained a wheel for Windows ARM64, Python 3.14" in page1_text

    assert '<section aria-labelledby="recent-changes">' not in page2_text
    assert "Recent changes" not in page2_text
