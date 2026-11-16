"""Add maintainer issue tracker links for known wheel gaps in the public PyPI tracker scan."""

from __future__ import annotations

import argparse
import json
import re
import string
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlsplit

TOP = 5_000
DEADLINE = 300  # seconds across all packages
GAPS = {"source", "missing"}
WORKERS = 8
TIMEOUT = 10
USER_AGENT = "wheelgap-tracker (+https://wheelgap.github.io/tracker/)"
SAFE_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")

_ISSUE_KEYS = (
    "issues",
    "issuetracker",
    "bugtracker",
    "tracker",
    "bugs",
    "bugreports",
    "issuereports",
    "issue",
    "bug",
    "githubissues",
    "gitlabissues",
)
_REPO_KEYS = ("source", "sourcecode", "code", "repository", "homepage", "home")
_LABEL_DROP = str.maketrans("", "", string.punctuation + string.whitespace)


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _normalise_label(label: str) -> str:
    """PEP 753's label normalisation: lowercase, with punctuation and whitespace removed."""
    return label.translate(_LABEL_DROP).lower()


def _plain(url: str) -> bool:
    """Printable ASCII with no spaces: nothing a terminal or browser would misinterpret."""
    return url.isascii() and url.isprintable() and " " not in url


def extract_issues_url(
    project_urls: dict[str, str] | None, homepage: str | None = None
) -> str | None:
    """Extract an HTTPS issue tracker URL from PyPI metadata.

    Reads `project_urls` with labels normalised as PEP 753 does (so `Issue-Tracker` and `bug_tracker` count),
    preferring issue tracker keys (Issues, Bug Tracker, Tracker).
    Falls back to a GitHub Source/Homepage URL with `/issues` added.
    Refuses any URL that is not an https:// URL, any with userinfo (@ in netloc),
    and any with characters that are not printable ASCII.
    """
    by_label: dict[str, list[str]] = {}
    if project_urls and isinstance(project_urls, dict):
        for k, v in project_urls.items():
            if isinstance(k, str) and isinstance(v, str):
                by_label.setdefault(_normalise_label(k), []).append(v)
        for target_key in _ISSUE_KEYS:
            for url in by_label.get(target_key, []):
                candidate = url.strip()
                if not candidate:
                    continue
                parsed = urlsplit(candidate)
                # No userinfo: https://github.com@evil.example/ reads as GitHub but opens evil.example.
                if (
                    parsed.scheme == "https"
                    and parsed.netloc
                    and "@" not in parsed.netloc
                    and _plain(candidate)
                ):
                    return candidate

    repo_candidates: list[str] = []
    for rk in _REPO_KEYS:
        repo_candidates.extend(by_label.get(rk, []))
    if homepage and isinstance(homepage, str):
        repo_candidates.append(homepage)

    for cand in repo_candidates:
        if not cand:
            continue
        candidate = cand.strip()
        parsed = urlsplit(candidate)
        if (
            parsed.scheme == "https"
            and parsed.netloc.lower() in ("github.com", "www.github.com")
            and _plain(candidate)
        ):
            segments = [s for s in parsed.path.strip("/").split("/") if s]
            if len(segments) >= 2:
                owner, repo = segments[0], segments[1].removesuffix(".git")
                return f"https://github.com/{owner}/{repo}/issues"

    return None


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
    except (OSError, ValueError, TimeoutError):
        return None, None


def scan(
    path: Path,
    top: int = TOP,
    deadline_seconds: float = DEADLINE,
    fetcher=fetch_pypi_metadata,
) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1:
        raise ValueError("expected coverage schema 1")

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
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {
                pool.submit(
                    fetcher,
                    package["name"],
                    min(TIMEOUT, max(0.5, deadline - time.monotonic())),
                ): package
                for package in candidates
            }
            for future in as_completed(futures):
                package = futures[future]
                if time.monotonic() > deadline:
                    break
                try:
                    urls, home = future.result()
                    if url := extract_issues_url(urls, home):
                        package["issues_url"] = url
                        found += 1
                except (OSError, ValueError, TimeoutError):
                    continue

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
