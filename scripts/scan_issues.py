"""Add maintainer issue tracker links for known wheel gaps in the public PyPI tracker scan."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path

TOP = 5_000
DEADLINE = 180  # seconds across all packages (the scan job's cap leaves little room for optional passes)
GAPS = {"source", "missing"}
WORKERS = 8
TIMEOUT = 10
USER_AGENT = "wheelgap-tracker (+https://wheelgap.github.io/tracker/)"
SAFE_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def fetch_pypi_metadata(
    name: str, timeout: float = TIMEOUT
) -> tuple[dict[str, str] | None, str | None]:
    """Fetch project_urls and home_page from PyPI's JSON API."""
    url = f"https://pypi.org/pypi/{canonical(name)}/json"
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
            info = data.get("info") or {}
            return info.get("project_urls"), info.get("home_page")
    except Exception:  # noqa: BLE001 - one bad response (IncompleteRead, a non-dict body) means no link, never no step
        return None, None


def scan(
    path: Path,
    top: int = TOP,
    deadline_seconds: float = DEADLINE,
    fetcher=fetch_pypi_metadata,
    extract=None,
) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1:
        raise ValueError("expected coverage schema 1")
    if extract is None:
        # wheelgap's own rule (`--explain`'s "ask for a wheel" link), so the site and the CLI never disagree and a
        # fix there reaches both: PEP 753 labels, https only, no user@ host, printable ASCII.
        from wheelgap.pypi import extract_issues_url as extract

    for package in data["packages"]:
        package.pop("issues_url", None)

    candidates = []
    for package in sorted(data["packages"], key=lambda row: row["rank"])[:top]:
        name = package.get("name")
        if (
            package.get("error")
            or not isinstance(name, str)
            or not SAFE_NAME.fullmatch(canonical(name))
        ):
            continue
        if any(status in GAPS for status in package.get("results", [])):
            candidates.append(package)

    found = 0
    if candidates:
        deadline = time.monotonic() + deadline_seconds
        pool = ThreadPoolExecutor(max_workers=WORKERS)
        try:
            futures = {
                pool.submit(fetcher, package["name"], min(TIMEOUT, max(0.5, deadline_seconds))): package
                for package in candidates
            }
            # Past the deadline the packages not yet answered get no link (never a guessed one) and the
            # lookups still queued are cancelled; only those in flight (TIMEOUT each) hold the exit.
            for future in as_completed(futures, timeout=max(0.0, deadline - time.monotonic())):
                package = futures[future]
                try:
                    urls, home = future.result()
                    # wheelgap 0.12.0's urlsplit raises ValueError on a bracketed host ("https://[x"): skip the
                    # package, as for any metadata it can't read, rather than lose every link tonight.
                    url = extract(urls, home)
                except Exception:  # noqa: BLE001
                    continue
                if url:
                    package["issues_url"] = url
                    found += 1
        except FuturesTimeout:
            print("issue trackers: deadline passed; the packages not yet looked up get no link tonight")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(json.dumps(data, separators=(",", ":")) + "\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"issue trackers: {found} found across {len(candidates)} packages with gaps")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coverage", type=Path)
    parser.add_argument("--top", type=int, default=TOP)
    args = parser.parse_args()
    scan(args.coverage, top=args.top)
