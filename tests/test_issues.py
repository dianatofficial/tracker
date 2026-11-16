"""Tests for issue tracker URLs: extraction, refusals, scan pass, page rendering and package lookup."""

import json

import pytest
from scripts import build_lookup, build_pages, scan_issues


def target(platform):
    return {
        "label": f"3.14 {platform}",
        "python": "3.14",
        "platform": platform,
        "glibc": "2.31",
        "musl": "1.2",
        "macos": "13.0",
    }


def package(rank, name, statuses, **extra):
    return {
        "rank": rank,
        "name": name,
        "version": "1.0",
        "pure": False,
        "error": None,
        "results": statuses,
        **extra,
    }


def snapshot(packages):
    return {
        "schema": 1,
        "generated": "2026-11-16T03:17:00Z",
        "wheelgap": "0.9.0",
        "targets": [target("win-arm64"), target("macos-arm64"), target("linux-x86_64")],
        "packages": packages,
    }


def write_scan(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def first_issues_label(urls, home):
    """A stand-in for wheelgap.pypi.extract_issues_url, whose rules wheelgap's own tests cover."""
    return (urls or {}).get("Issues")


def test_scan_issues_populates_only_packages_with_gaps(tmp_path):
    data = snapshot(
        [
            package(1, "needs-wheel", ["source", "missing", "wheel"]),
            package(2, "has-wheel", ["wheel", "wheel", "wheel"]),
            package(3, "errored", ["source", "wheel", "wheel"], error="scan failed"),
            package(
                4,
                "no-issues-url",
                ["source", "wheel", "wheel"],
                issues_url="https://stale.example/issues",
            ),
        ]
    )
    scan_file = write_scan(tmp_path / "coverage.json", data)

    metadata = {
        "needs-wheel": ({"Issues": "https://github.com/org/needs-wheel/issues"}, None),
        "has-wheel": ({"Issues": "https://github.com/org/has-wheel/issues"}, None),
        "no-issues-url": ({"Homepage": "https://example.com"}, None),
    }

    def mock_fetch(name, timeout):
        return metadata.get(name, (None, None))

    scan_issues.scan(scan_file, top=10, deadline_seconds=10, fetcher=mock_fetch, extract=first_issues_label)
    updated = json.loads(scan_file.read_text(encoding="utf-8"))

    assert (
        updated["packages"][0]["issues_url"]
        == "https://github.com/org/needs-wheel/issues"
    )
    assert "issues_url" not in updated["packages"][1]
    assert "issues_url" not in updated["packages"][2]
    # Stale issues_url popped because no issues URL was found
    assert "issues_url" not in updated["packages"][3]


def test_scan_issues_stops_at_the_deadline(tmp_path):
    # One lookup hangs: the scan must still end near its deadline, write what it found, and give the slow
    # package no link rather than wait for it.
    import threading
    import time

    release = threading.Event()
    data = snapshot(
        [
            package(1, "quick", ["source", "wheel", "wheel"]),
            package(2, "stuck", ["source", "wheel", "wheel"], issues_url="https://example.com/old"),
        ]
    )
    scan_file = write_scan(tmp_path / "coverage.json", data)

    def fetch(name, timeout):
        if name == "stuck":
            release.wait(10)
        return {"Issues": f"https://example.com/{name}/issues"}, None

    started = time.monotonic()
    try:
        scan_issues.scan(scan_file, top=10, deadline_seconds=0.5, fetcher=fetch, extract=first_issues_label)
        elapsed = time.monotonic() - started
    finally:
        release.set()
    assert elapsed < 5
    updated = json.loads(scan_file.read_text(encoding="utf-8"))
    assert updated["packages"][0]["issues_url"] == "https://example.com/quick/issues"
    assert "issues_url" not in updated["packages"][1]


def test_scan_issues_one_bad_package_costs_only_its_own_link(tmp_path):
    # A dropped connection (IncompleteRead isn't an OSError) or metadata urlsplit can't read ("https://[x")
    # must not stop the step: the other packages still get their links.
    import http.client

    data = snapshot(
        [
            package(1, "dropped", ["source", "wheel", "wheel"]),
            package(2, "bracketed", ["source", "wheel", "wheel"]),
            package(3, "fine", ["source", "wheel", "wheel"]),
        ]
    )
    scan_file = write_scan(tmp_path / "coverage.json", data)

    def fetch(name, timeout):
        if name == "dropped":
            raise http.client.IncompleteRead(b"{")
        return {"Issues": f"https://example.com/{name}/issues"}, None

    def extract(urls, home):
        if "bracketed" in urls["Issues"]:
            raise ValueError("Invalid IPv6 URL")
        return urls["Issues"]

    scan_issues.scan(scan_file, top=10, deadline_seconds=10, fetcher=fetch, extract=extract)
    updated = json.loads(scan_file.read_text(encoding="utf-8"))
    assert "issues_url" not in updated["packages"][0]
    assert "issues_url" not in updated["packages"][1]
    assert updated["packages"][2]["issues_url"] == "https://example.com/fine/issues"


def test_fetch_pypi_metadata_never_raises(monkeypatch):
    import http.client

    def boom(*a, **k):
        raise http.client.IncompleteRead(b"")

    monkeypatch.setattr(scan_issues.urllib.request, "urlopen", boom)
    assert scan_issues.fetch_pypi_metadata("demo") == (None, None)


def test_scan_issues_refuses_invalid_schema(tmp_path):
    data = snapshot([package(1, "demo", ["source", "wheel", "wheel"])])
    data["schema"] = 2
    scan_file = write_scan(tmp_path / "coverage.json", data)
    with pytest.raises(ValueError, match="expected coverage schema 1"):
        scan_issues.scan(scan_file)


def test_package_page_renders_maintainer_link_for_gaps(tmp_path):
    url = "https://github.com/org/demo/issues?q=is%3Aissue&sort=created"
    data = snapshot(
        [
            package(1, "demo", ["source", "missing", "wheel"], issues_url=url),
            package(2, "nowheels-noissues", ["source", "wheel", "wheel"]),
            package(
                3,
                "allwheels-withissues",
                ["wheel", "wheel", "wheel"],
                issues_url="https://github.com/org/all/issues",
            ),
            package(
                4,
                "badurl",
                ["source", "wheel", "wheel"],
                issues_url="http://insecure.example/issues",
            ),
            package(
                5,
                "userinfourl",
                ["source", "wheel", "wheel"],
                issues_url="https://github.com@evil.example/issues",
            ),
            package(
                6,
                "controlcharurl",
                ["source", "wheel", "wheel"],
                issues_url="https://github.com/org/repo/issues\n",
            ),
        ]
    )
    scan_file = write_scan(tmp_path / "coverage.json", data)
    site = tmp_path / "site"
    build_pages.build(scan_file, site, root=tmp_path)

    # 1. Package with gap and valid issues_url: link rendered with proper HTML escaping
    demo_page = (site / "p" / "demo" / "index.html").read_text(encoding="utf-8")
    assert "No wheel for your platform? Ask the maintainers:" in demo_page
    assert (
        'href="https://github.com/org/demo/issues?q=is%3Aissue&amp;sort=created"'
        in demo_page
    )
    assert (
        ">https://github.com/org/demo/issues?q=is%3Aissue&amp;sort=created</a>"
        in demo_page
    )

    # 2. Package with gap but no issues_url: no link
    no_issues_page = (site / "p" / "nowheels-noissues" / "index.html").read_text(
        encoding="utf-8"
    )
    assert "No wheel for your platform?" not in no_issues_page

    # 3. Package with all wheels: no link even if issues_url key exists
    all_wheels_page = (site / "p" / "allwheels-withissues" / "index.html").read_text(
        encoding="utf-8"
    )
    assert "No wheel for your platform?" not in all_wheels_page

    # 4. Refusals: http URL not rendered
    bad_url_page = (site / "p" / "badurl" / "index.html").read_text(encoding="utf-8")
    assert "No wheel for your platform?" not in bad_url_page

    # 5. Refusals: userinfo URL not rendered
    userinfo_page = (site / "p" / "userinfourl" / "index.html").read_text(
        encoding="utf-8"
    )
    assert "No wheel for your platform?" not in userinfo_page

    # 6. Refusals: control character URL not rendered
    control_page = (site / "p" / "controlcharurl" / "index.html").read_text(
        encoding="utf-8"
    )
    assert "No wheel for your platform?" not in control_page


def test_build_lookup_includes_issues_url(tmp_path):
    url = "https://github.com/org/demo/issues"
    data = snapshot(
        [
            package(1, "demo", ["source", "missing", "wheel"], issues_url=url),
            package(2, "other", ["source", "wheel", "wheel"]),
        ]
    )
    scan_file = write_scan(tmp_path / "coverage.json", data)
    out = tmp_path / "data" / "packages"
    build_lookup.build(scan_file, out, root=tmp_path)

    demo = json.loads((out / "demo.json").read_text(encoding="utf-8"))
    other = json.loads((out / "other.json").read_text(encoding="utf-8"))

    assert demo.get("issues_url") == url
    assert "issues_url" not in other
