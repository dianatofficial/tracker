// node --test tests/site/check-logic.test.mjs: the repo checker's pure helpers (site/check/check-logic.mjs).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parseRepo, rawUrl, pickLockfile, toQuery, fromQuery, sortPythons, freeThreaded, fixFor, rowsFor, headline,
  cliCommand, fixPrompt, verdictText, nextSteps, validRef, labVerdict, labFor, canonicalName, gapWheelFor,
  gapWheelFixText, withoutUnreadable, unreadableReason, tileText, missedText, badgeMarkdown, trimProject, trimReleases,
  fixLinks, validIssuesUrl, rowLinks,
} from "../../site/check/check-logic.mjs";

test("PyPI trimming keeps the pinned consumer's fields without changing the input", () => {
  const file = {
    filename: "demo-1.0-py3-none-any.whl", requires_python: ">=3.13", yanked: "withdrawn",
    packagetype: "bdist_wheel", upload_time_iso_8601: "2026-11-21T00:00:00Z", size: 123,
    url: "https://files.pythonhosted.org/unused", digests: { sha256: "unused" }, comment_text: "unused",
  };
  const doc = {
    info: { version: "1.0", project_urls: { Source: "https://example.org/src" }, home_page: "https://example.org/",
      description: "unused", requires_python: ">=3.13", yanked: true },
    urls: [file], releases: { "1.0": [file], "0.9": [] }, last_serial: 123,
  };
  const before = structuredClone(doc);
  const keptFile = { filename: file.filename, requires_python: ">=3.13", yanked: "withdrawn" };
  const keptReleases = { "1.0": [keptFile], "0.9": [] };
  assert.deepEqual(trimProject(doc), {
    info: { version: "1.0", project_urls: doc.info.project_urls, home_page: doc.info.home_page },
    urls: [keptFile], releases: keptReleases,
  });
  assert.deepEqual(trimReleases(doc.releases), keptReleases);
  assert.deepEqual(doc, before);
  // A JSON key named __proto__ must remain an ordinary entry, not set the returned object's prototype.
  const special = trimReleases(JSON.parse('{"__proto__": [], "constructor": []}'));
  assert.deepEqual(Object.keys(special), ["__proto__", "constructor"]);
  assert.equal(Object.getPrototypeOf(special), Object.prototype);
});

test("trimming preserves malformed and missing shapes instead of inventing empty file lists", () => {
  for (const bad of [null, false, 3, "not JSON metadata", [], [null]]) {
    assert.deepEqual(trimProject(bad), bad);
    assert.deepEqual(trimReleases(bad), bad);
    assert.deepEqual(trimProject({ info: bad, urls: bad, releases: bad }), { info: bad, urls: bad, releases: bad });
  }
  assert.deepEqual(trimProject({ message: "Not Found" }), {}); // still missing urls and releases
  assert.deepEqual(trimProject({ info: { version: "1.0" } }), { info: { version: "1.0" } });
  assert.deepEqual(trimProject({ urls: [], releases: {} }), { urls: [], releases: {} }); // valid empty is distinct
  const files = [null, false, "bad", [], {}, { filename: null }, { filename: 1 }, { yanked: false },
    { filename: "demo.whl", requires_python: null, yanked: false }];
  assert.deepEqual(trimProject({ urls: files }), { urls: files });
  assert.deepEqual(trimReleases({ "1.0": files, "2.0": null, "3.0": {} }), { "1.0": files, "2.0": null, "3.0": {} });
  // Invalid values of consumed metadata are the consumer's decision too, not the trimmer's.
  assert.deepEqual(trimProject({ info: { version: null, project_urls: [], home_page: 4 } }),
    { info: { version: null, project_urls: [], home_page: 4 } });
});

test("parseRepo reads the forms people paste", () => {
  const plain = { owner: "fastapi", name: "fastapi", ref: null, dir: null };
  assert.deepEqual(parseRepo("fastapi/fastapi"), plain);
  assert.deepEqual(parseRepo("https://github.com/fastapi/fastapi"), plain);
  assert.deepEqual(parseRepo("github.com/fastapi/fastapi.git/"), plain);
  assert.deepEqual(parseRepo("git@github.com:fastapi/fastapi.git"), plain);
  assert.deepEqual(parseRepo("https://www.github.com/fastapi/fastapi?tab=readme#top"), plain);
  assert.deepEqual(parseRepo("https://github.com/o/r/tree/dev/backend/api"), { owner: "o", name: "r", ref: "dev", dir: "backend/api" });
  assert.deepEqual(parseRepo("https://github.com/o/r/blob/main/backend/uv.lock"), { owner: "o", name: "r", ref: "main", dir: "backend" });
  assert.deepEqual(parseRepo("https://github.com/o/r/blob/main/uv.lock"), { owner: "o", name: "r", ref: "main", dir: null });
});

test("parseRepo refuses what isn't a repo", () => {
  for (const bad of ["", "fastapi", "https://gitlab.com/a", "a b/c", "../x", "o/..", "o/r/tree/main/../../etc", "javascript:alert(1)", "o/r/tree/ma in/x"]) {
    assert.equal(parseRepo(bad), null, bad);
  }
});

test("rawUrl encodes each path segment", () => {
  assert.equal(rawUrl({ owner: "o", name: "r" }, "HEAD", "a b/uv.lock"), "https://raw.githubusercontent.com/o/r/HEAD/a%20b/uv.lock");
  assert.equal(rawUrl({ owner: "o", name: "r" }, "feat/x", "uv.lock"), "https://raw.githubusercontent.com/o/r/feat/x/uv.lock");
});

test("pickLockfile prefers the URL's folder, then plan()'s first file, whichever kind it is", () => {
  // In plan()'s order: shallowest folder first, then wheelgap's own order, a pyproject.toml last in its folder.
  const locks = [
    { path: "requirements.txt", offline: false },
    { path: "pyproject.toml", offline: false },
    { path: "backend/uv.lock", offline: true },
    { path: "backend/requirements.txt", offline: false },
    { path: "docs/requirements.txt", offline: false },
  ];
  // `wheelgap` in the root reads requirements.txt: a lockfile deeper in the repo doesn't outrank it.
  assert.equal(pickLockfile(locks, null).path, "requirements.txt");
  assert.equal(pickLockfile(locks, "backend").path, "backend/uv.lock");
  // The folder the URL named wins, also when its only file is checked by PyPI lookups.
  assert.equal(pickLockfile(locks, "docs").path, "docs/requirements.txt");
  assert.equal(pickLockfile(locks, "elsewhere").path, "requirements.txt");
  assert.equal(pickLockfile(locks.slice(1), null).path, "pyproject.toml");
  assert.equal(pickLockfile([], null), null);
});

test("an unreadable pyproject.toml the page picked itself gives way to the repo's other files", () => {
  const locks = [{ path: "pyproject.toml", offline: false }, { path: "backend/uv.lock", offline: true }];
  assert.deepEqual(withoutUnreadable(locks, "pyproject.toml", true), [locks[1]]);
  assert.equal(withoutUnreadable(locks, "pyproject.toml", false), null); // a link or the visitor named it: say why
  assert.equal(withoutUnreadable(locks, "backend/uv.lock", true), null); // a broken lockfile is reported, not skipped
  assert.equal(withoutUnreadable([locks[0]], "pyproject.toml", true), null); // nothing else to check
  const nested = [{ path: "a/pyproject.toml", offline: false }, { path: "a/b/pyproject.toml", offline: false }];
  assert.deepEqual(withoutUnreadable(nested, "a/pyproject.toml", true), [nested[1]]);
});

test("a file with nothing to check is no answer; one whose packages were skipped or aren't installed is", () => {
  const error = "pyproject.toml: no [project] table, so there are no dependencies to read";
  assert.equal(unreadableReason({ kind: "source", error }), error);
  // A [project] table with no dependencies: read without an error, and nothing in it to check.
  const empty = { looked_up: true, listed: 0, packages: 0, skipped: [], rows: [] };
  assert.equal(unreadableReason(empty), "it lists no dependencies");
  assert.equal(unreadableReason({ ...empty, listed: 2 }), null); // left off pypi.org, or no target picked installs them
  assert.equal(unreadableReason({ ...empty, listed: 3, packages: 3 }), null);
  assert.equal(unreadableReason({ ...empty, looked_up: false }), null); // a lockfile with no packages says so itself
  assert.equal(unreadableReason({ ...empty, listed: undefined }), null); // a driver that doesn't count them
  assert.equal(unreadableReason({ kind: "targets", error: "unknown platform" }), null);
  assert.equal(unreadableReason({ kind: "needs-index", error: "poetry.lock needs the index" }), null);
});

test("a result's query round-trips, and unknown values are dropped", () => {
  const state = { repo: { owner: "o", name: "r", ref: "dev" }, lockfile: "backend/uv.lock", pythons: ["3.14", "3.14t"], platforms: ["linux-aarch64", "win-arm64"] };
  const q = toQuery(state);
  assert.equal(q, "repo=o/r&ref=dev&lock=backend/uv.lock&py=3.14,3.14t&t=linux-aarch64,win-arm64");
  const back = fromQuery(`?${q}`);
  assert.deepEqual(back, { repo: { owner: "o", name: "r", ref: "dev", dir: null }, lockfile: "backend/uv.lock", pythons: ["3.14", "3.14t"], platforms: ["linux-aarch64", "win-arm64"] });
  const odd = fromQuery("?repo=o/r&lock=../x&py=3.14,2.7,evil&t=linux-x86_64,amiga");
  assert.equal(odd.lockfile, null);
  assert.deepEqual(odd.pythons, ["3.14"]);
  assert.deepEqual(odd.platforms, ["linux-x86_64"]);
  assert.equal(fromQuery("?repo=nope"), null);
  assert.equal(fromQuery(""), null);
});

test("the badge Markdown links the check of the repo alone, and names the lockfile only when it isn't the default", () => {
  const repo = { owner: "fastapi", name: "full-stack-fastapi-template", ref: "dev", dir: "backend" };
  const badge = "[![Check wheels](https://wheelgap.github.io/tracker/check/badge.svg)]";
  const check = "https://wheelgap.github.io/tracker/check/";
  // Never the ref, the Pythons or the platforms: a click checks the default branch on its CI's targets that day.
  const plain = `${badge}(${check}?repo=fastapi/full-stack-fastapi-template)`;
  assert.equal(badgeMarkdown(repo, "uv.lock", "uv.lock"), plain);
  assert.equal(badgeMarkdown(repo, null, null), plain);
  assert.equal(badgeMarkdown(repo, "backend/uv.lock", "uv.lock"), `${badge}(${check}?repo=fastapi/full-stack-fastapi-template&lock=backend/uv.lock)`);
  // A path with characters that would end the Markdown link, or the query, early.
  const odd = "my app/a(1)&b=c#d/100%/[x] \"q\"/uv.lock";
  const md = badgeMarkdown({ owner: "o", name: "r" }, odd, "uv.lock");
  assert.equal(md, `${badge}(${check}?repo=o/r&lock=my+app/a%281%29%26b%3Dc%23d/100%25/%5Bx%5D+%22q%22/uv.lock)`);
  const url = md.slice(badge.length + 1, -1);
  assert.doesNotMatch(url, /[\s()[\]<>"']/);
  // The page reads the link back as the same repo and file, with nothing else picked.
  assert.deepEqual(fromQuery(new URL(url).search), { repo: { owner: "o", name: "r", ref: null, dir: null }, lockfile: odd, pythons: [], platforms: [] });
});

test("Pythons sort with each free-threaded build after its own", () => {
  assert.deepEqual(sortPythons(["3.15t", "3.13", "3.15", "3.14t", "3.14", "3.14"]), ["3.13", "3.14", "3.14t", "3.15", "3.15t"]);
  assert.equal(freeThreaded(["3.12", "3.14"]), "3.14t");
  assert.equal(freeThreaded(["3.10", "3.11"]), "3.13t"); // free-threading starts at 3.13
  assert.equal(freeThreaded(["3.14", "3.14t"]), null);
});

const row = (name, version, gaps, statuses = {}, extra = {}) => ({ name, version, gaps, unknown: [], keep: [], statuses, lookup: true, ...extra });

test("fixFor says one release, some, none, or not looked up", () => {
  const r = row("numpy", "1.26.4", ["3.14 linux-x86_64", "3.14 win-arm64"]);
  assert.deepEqual(fixFor(r, null), { kind: "pending", text: "" });
  assert.deepEqual(fixFor(r, { "numpy==1.26.4": { found: {}, loses: [] } }), { kind: "none", text: "no newer release has a wheel" });
  const all = fixFor(r, { "numpy==1.26.4": { found: { "3.14 linux-x86_64": "2.3.2", "3.14 win-arm64": "2.3.2" }, loses: [] } });
  assert.deepEqual(all, { kind: "all", version: "2.3.2", text: "2.3.2 (a new major version)" });
  const some = fixFor(r, { "numpy==1.26.4": { found: { "3.14 linux-x86_64": "1.26.5" }, loses: [] } });
  assert.deepEqual(some, { kind: "some", version: "1.26.5", text: "1.26.5 for 1 of 2 gaps" });
});

const result = {
  lockfile: "uv.lock",
  packages: 10,
  outside_lock: ["3.15"],
  targets: [
    { label: "3.14 linux-x86_64", python: "3.14", platform: "linux-x86_64" },
    { label: "3.14 win-arm64", python: "3.14", platform: "win-arm64" },
    { label: "3.15 linux-x86_64", python: "3.15", platform: "linux-x86_64" },
  ],
  rows: [
    row("a", "1.0", ["3.14 win-arm64"], { "3.14 linux-x86_64": "wheel", "3.14 win-arm64": "source", "3.15 linux-x86_64": "missing" }),
    row("b", "2.0", ["3.14 linux-x86_64", "3.14 win-arm64"], { "3.14 linux-x86_64": "missing", "3.14 win-arm64": "missing", "3.15 linux-x86_64": "wheel" }),
  ],
};

test("rowsFor lists one Python's gaps, most first; headline counts distinct packages on counted targets", () => {
  assert.deepEqual(rowsFor(result, "3.14").map((r) => [r.name, r.here.length]), [["b", 2], ["a", 1]]);
  assert.deepEqual(rowsFor(result, "3.15"), []); // outside the lock: check() reports no gaps there
  assert.deepEqual(headline(result), { gaps: 2, unknown: 0, packages: 10, targets: 2 });
});

test("the CLI command and the fix prompt reproduce the check", () => {
  assert.equal(cliCommand(result, ["3.14t", "3.14"], ["linux-x86_64", "win-arm64"]), "uvx wheelgap uv.lock -p 3.14,3.14t -t linux-x86_64,win-arm64");
  assert.equal(cliCommand({ lockfile: "my app/uv.lock" }, ["3.14"], ["linux-x86_64"]), "uvx wheelgap 'my app/uv.lock' -p 3.14 -t linux-x86_64");
  const fixes = { "a==1.0": { found: { "3.14 win-arm64": "1.1" }, loses: [] }, "b==2.0": { found: {}, loses: [] } };
  const prompt = fixPrompt("o/r", result, fixes, ["3.14"], ["linux-x86_64", "win-arm64"]);
  assert.match(prompt, /- a 1\.0 -> 1\.1\n/);
  assert.match(prompt, /No newer release has a wheel for these[^\n]*\n- b 2\.0: 3\.14 linux-x86_64, 3\.14 win-arm64/);
  assert.match(prompt, /uvx wheelgap uv\.lock -p 3\.14 -t linux-x86_64,win-arm64/);
  assert.doesNotMatch(prompt, /weren't looked up/);
  assert.match(fixPrompt("o/r", result, null, ["3.14"], ["linux-x86_64"]), /weren't looked up on PyPI/);
});

test("the verdict reads right for one target and many", () => {
  assert.equal(verdictText({ gaps: 1, packages: 77, targets: 1 }), "1 of 77 packages has no wheel for this target");
  assert.equal(verdictText({ gaps: 5, packages: 79, targets: 4 }), "5 of 79 packages have no wheel for at least one of the 4 targets");
  assert.equal(verdictText({ gaps: 0, packages: 10, targets: 1 }), "✓ All 10 packages have a wheel for this target");
  assert.equal(verdictText({ gaps: 0, packages: 10, targets: 6 }), "✓ All 10 packages have a wheel for all 6 targets");
  // Every package skipped (a requirements file that names another index, say), or none listed: never a ✓.
  assert.equal(verdictText({ gaps: 0, unknown: 0, packages: 0, targets: 4 }), "No packages were checked");
});

test("next steps offer what isn't picked yet, as whole selections", () => {
  const steps = nextSteps(["3.14"], ["linux-x86_64"]);
  assert.deepEqual(steps.map((s) => s.label), ["Free-threaded 3.14t", "Windows on ARM", "Linux ARM64", "Alpine Linux", "Python 3.15", "Everything"]);
  assert.deepEqual(steps[0], { label: "Free-threaded 3.14t", pythons: ["3.14", "3.14t"], platforms: ["linux-x86_64"] });
  assert.deepEqual(steps[3].platforms, ["linux-x86_64", "musl-x86_64", "musl-aarch64"]);
  assert.equal(steps.at(-1).platforms.length, 8);
  const all = ["linux-x86_64", "linux-aarch64", "musl-x86_64", "musl-aarch64", "macos-arm64", "macos-x86_64", "win-amd64", "win-arm64"];
  assert.deepEqual(nextSteps(["3.15", "3.15t"], all), []);
});

test("fixFor: a bump that drops a wheel elsewhere isn't 'no newer wheel', and private packages aren't looked up", () => {
  const r = row("foo", "1.0", ["3.13 linux-aarch64"]);
  const loses = fixFor(r, { "foo==1.0": { found: {}, loses: ["3.13 linux-aarch64"] } });
  assert.equal(loses.kind, "loses");
  const priv = row("corp-utils", "1.0", ["3.13 linux-x86_64"], {}, { lookup: false });
  assert.equal(fixFor(priv, { "corp-utils==1.0": { found: { "3.13 linux-x86_64": "9.9" }, loses: [] } }).kind, "private");
  assert.equal(fixFor(row("x", "1", [], {}, { unknown: ["3.13 linux-x86_64"] }), {}).kind, "unchecked");
  const res = { ...result, rows: [r, priv] };
  const prompt = fixPrompt("o/r", res, { "foo==1.0": { found: {}, loses: ["3.13 linux-aarch64"] } }, ["3.13"], ["linux-aarch64"]);
  assert.match(prompt, /trades one gap for another[^\n]*\n- foo 1\.0: 3\.13 linux-aarch64/);
  assert.match(prompt, /doesn't record their index as PyPI[^\n]*\n- corp-utils 1\.0/);
  assert.doesNotMatch(prompt, /don't come from PyPI/);
  assert.doesNotMatch(prompt, /No newer release has a wheel/);
  assert.doesNotMatch(prompt, /9\.9/);
});

test("unknown cells are listed but not counted as missing a wheel", () => {
  const res = {
    ...result,
    outside_lock: [],
    rows: [row("u", "1", [], { "3.14 linux-x86_64": "unknown", "3.14 win-arm64": "wheel" }, { unknown: ["3.14 linux-x86_64"] })],
  };
  assert.deepEqual(headline(res), { gaps: 0, unknown: 1, packages: 10, targets: 3 });
  assert.deepEqual(rowsFor(res, "3.14").map((r) => r.name), ["u"]);
  assert.equal(verdictText(headline(res)), "No package is missing a wheel, but 1 of 10 couldn't be checked on some targets");
});

test("a platform's tile shows a ✓ only when every package was checked and has a wheel", () => {
  assert.deepEqual(tileText({ wheel: 10, source: 0, missing: 0, unknown: 0 }, false), { mark: "✓", note: "all wheels" });
  assert.deepEqual(tileText({ wheel: 7, source: 2, missing: 1, unknown: 4 }, false), { mark: "3", note: "without a wheel" });
  // None known to lack a wheel, but some couldn't be checked (PyPI unreachable, over the lookup cap): never a ✓.
  assert.deepEqual(tileText({ wheel: 9, source: 0, missing: 0, unknown: 1 }, false), { mark: "?", note: "1 unknown" });
  assert.deepEqual(tileText({ wheel: 0, source: 0, missing: 0, unknown: 18 }, false), { mark: "?", note: "18 unknown" });
  assert.deepEqual(tileText({ wheel: 0, source: 0, missing: 0, unknown: 0 }, true), { mark: "–", note: "not locked" });
});

test("the page says why lookups got no answer, and nothing when they all did", () => {
  assert.equal(missedText(undefined, "uv.lock"), null); // a lockfile read from its own files
  assert.equal(missedText({ cap: 300, over_cap: 0, not_found: 0, failed: 0 }, "requirements.txt"), null);
  assert.equal(
    missedText({ cap: 300, over_cap: 12, not_found: 1, failed: 2 }, "requirements.txt"),
    "Not looked up on PyPI, so shown as unknown: 12 beyond the 300 packages this page looks up for one file; " +
      "2 whose lookup failed or timed out (check again to retry); 1 that PyPI doesn't have under that name or version. " +
      "uvx wheelgap requirements.txt in a checkout looks them up.",
  );
  // The command line wouldn't find these either, so it isn't offered for them.
  assert.equal(
    missedText({ cap: 300, over_cap: 0, not_found: 2, failed: 0 }, "Pipfile.lock"),
    "Not looked up on PyPI, so shown as unknown: 2 that PyPI doesn't have under that name or version.",
  );
});

test("refs with '..' or empty segments are refused", () => {
  assert.ok(validRef("main") && validRef("feature/x") && validRef("v1.2.3"));
  for (const bad of ["..", "a/../b", "a//b", "/a", "a/", ".", "a b"]) assert.equal(validRef(bad), false, bad);
  assert.equal(parseRepo("https://github.com/o/r/tree/../../other/repo"), null);
  assert.equal(fromQuery("?repo=o/r&ref=../../x/y").repo.ref, null);
});

test("the checker's lab verdicts match the tracker's", async () => {
  const { createRequire } = await import("node:module");
  const site = createRequire(import.meta.url)("../../site/logic.js");
  const base = { outcome: "built", seconds: 87, wheel: "cp314-cp314-win_arm64", extensions: 1, import: "ok", gil: null, reason: null };
  const cases = [
    {}, { gil: "kept-off", seconds: 289 }, { gil: "re-enabled" }, { extensions: 0, wheel: "py3-none-any" }, { extensions: 0 },
    { import: "failed" }, { import: "deps-failed" }, { outcome: "failed", reason: "needs OpenSSL" }, { outcome: "failed", reason: "other" }, { outcome: "failed", reason: "unsupported platform" },
    { outcome: "timeout", seconds: 2400 },
  ];
  for (const c of cases) assert.deepEqual(labVerdict({ ...base, ...c }), site.labVerdict({ ...base, ...c }), JSON.stringify(c));
});

test("a lab result counts only for its own release and target", () => {
  const builds = [{ target: "3.14 win-arm64", version: "0.14.0", outcome: "built" }];
  assert.equal(labFor(builds, "0.14.0", "3.14 win-arm64").outcome, "built");
  assert.equal(labFor(builds, "0.13.0", "3.14 win-arm64"), null);
  assert.equal(labFor(builds, "0.14.0", "3.14t win-arm64"), null);
  assert.equal(labFor("nope", "0.14.0", "3.14 win-arm64"), null);
  assert.equal(canonicalName("Typing_Extensions.x"), "typing-extensions-x");
});


test("the copy prompt includes only the driver's gap wheel instructions", () => {
  const result = { lockfile: "uv.lock", rows: [] };
  const gapWheels = {
    cells: [{ name: "fastlib", version: "2.0.0", target: "3.13 win-amd64" }],
    text: "[[tool.uv.index]]\nname = \"wheelgap\"",
    unofficial: "unofficial, built by wheelgap",
  };
  assert.equal(gapWheelFor({ name: "fastlib", version: "2.0.0" }, gapWheels, "3.13 win-amd64"), true);
  assert.equal(gapWheelFor({ name: "fastlib", version: "2.0.1" }, gapWheels, "3.13 win-amd64"), false);
  // The Fix column counts over all of a row's gaps: one filled target of two isn't "available" for the row.
  const row = { name: "fastlib", version: "2.0.0", gaps: ["3.13 win-amd64"] };
  assert.equal(gapWheelFixText(row, gapWheels), "gap wheel available");
  assert.equal(gapWheelFixText({ ...row, gaps: ["3.13 win-amd64", "3.13 win-arm64"] }, gapWheels), "gap wheel for 1 of 2 gaps");
  assert.equal(gapWheelFixText({ ...row, version: "2.0.1" }, gapWheels), null);
  assert.equal(gapWheelFixText(row, null), null);
  const prompt = fixPrompt("o/r", result, {}, ["3.13"], ["win-amd64"], gapWheels);
  assert.match(prompt, /unofficial, built by wheelgap/);
  assert.ok(prompt.includes(gapWheels.text));
});

test("fixLinks picks a row's links under Fix: none, loses, gap wheel, private, and invalid issues URLs", () => {
  const rNone = { name: "demo-pkg", version: "1.0", gaps: ["3.14 linux-x86_64"], lookup: true };
  const fNone = { kind: "none", text: "no newer release has a wheel" };

  // 1. none with issues_url:
  const withIssues = fixLinks(rNone, fNone, { ok: true, issues_url: "https://github.com/org/demo/issues" });
  assert.deepEqual(withIssues, [
    { text: "coverage and build results", href: "../p/demo-pkg/" },
    { text: "ask the maintainers", href: "https://github.com/org/demo/issues", rel: "noopener nofollow" },
  ]);

  // none without issues_url:
  const withoutIssues = fixLinks(rNone, fNone, { ok: true });
  assert.deepEqual(withoutIssues, [
    { text: "coverage and build results", href: "../p/demo-pkg/" },
  ]);

  // 2. loses:
  const fLoses = { kind: "loses", text: "only releases that drop a wheel elsewhere" };
  const losesLinks = fixLinks(rNone, fLoses, { ok: true, issues_url: "https://github.com/org/demo/issues" });
  assert.deepEqual(losesLinks, [
    { text: "coverage and build results", href: "../p/demo-pkg/" },
    { text: "ask the maintainers", href: "https://github.com/org/demo/issues", rel: "noopener nofollow" },
  ]);

  // 3. a row a gap wheel fills (no links needed):
  const gapWheels = {
    cells: [{ name: "demo-pkg", version: "1.0", target: "3.14 linux-x86_64" }],
    text: "gap-wheels",
    unofficial: "unofficial",
  };
  assert.deepEqual(fixLinks(rNone, fNone, { ok: true, issues_url: "https://github.com/org/demo/issues" }, gapWheels), []);

  // 4. private (none):
  const rPriv = { name: "corp-lib", version: "1.0", gaps: ["3.14 linux-x86_64"], lookup: false };
  const fPriv = { kind: "private", text: "not looked up" };
  assert.deepEqual(fixLinks(rPriv, fPriv, { ok: true, issues_url: "https://github.com/org/demo/issues" }), []);

  // 5. an issues_url that isn't https or is on an unknown host (dropped):
  const notHttps = fixLinks(rNone, fNone, { ok: true, issues_url: "http://insecure.example/issues" });
  assert.deepEqual(notHttps, [{ text: "coverage and build results", href: "../p/demo-pkg/" }]);

  const noHost = fixLinks(rNone, fNone, { ok: true, issues_url: "https:///issues" });
  assert.deepEqual(noHost, [{ text: "coverage and build results", href: "../p/demo-pkg/" }]);

  const userinfo = fixLinks(rNone, fNone, { ok: true, issues_url: "https://github.com@evil.example/issues" });
  assert.deepEqual(userinfo, [{ text: "coverage and build results", href: "../p/demo-pkg/" }]);

  const controlChar = fixLinks(rNone, fNone, { ok: true, issues_url: "https://github.com/org/demo/issues\n" });
  assert.deepEqual(controlChar, [{ text: "coverage and build results", href: "../p/demo-pkg/" }]);

  // rowLinks alias works the same
  assert.deepEqual(rowLinks(fNone, rNone, { ok: true }), [{ text: "coverage and build results", href: "../p/demo-pkg/" }]);

  // fixPrompt includes the issue tracker URL for none and loses groups when known
  const prompt = fixPrompt(
    "o/r",
    { lockfile: "uv.lock", rows: [rNone] },
    { "demo-pkg==1.0": { found: {}, loses: [] } },
    ["3.14"],
    ["linux-x86_64"],
    null,
    { "demo-pkg": { issues_url: "https://github.com/org/demo/issues" } }
  );
  assert.match(prompt, /- demo-pkg 1\.0: 3\.14 linux-x86_64 \(ask the maintainers: https:\/\/github\.com\/org\/demo\/issues\)/);
});
