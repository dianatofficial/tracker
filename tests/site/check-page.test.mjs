// node --test tests/site/check-page.test.mjs: the repo checker's page (site/check/index.html) and the part of
// check.mjs that shows and hides its sections. check.mjs needs a browser, so its function is run on stand-in elements.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import * as checkLogic from "../../site/check/check-logic.mjs";

const read = (name) => fs.readFileSync(new URL(`../../site/check/${name}`, import.meta.url), "utf8");
const TOOL = "https://github.com/wheelgap/wheelgap";

test("the line under a result links the tool's repo and its GitHub Action, as static text", () => {
  const html = read("index.html");
  const line = html.match(/<p class="note star-line" id="star-line" hidden>(.*?)<\/p>/s);
  assert.ok(line, "the line is in the page, hidden until a result is shown");
  const out = html.slice(html.indexOf('<main class="wrap" id="out" hidden>'), html.indexOf("</main>"));
  assert.ok(out.lastIndexOf("</section>") < out.indexOf('id="star-line"'), "it comes after the result's sections");
  const links = [...line[1].matchAll(/<a href="([^"]+)">(.*?)<\/a>/g)].map((m) => [m[1], m[2]]);
  assert.deepEqual(links, [
    [`${TOOL}/blob/main/docs/ci.md#github-action`, "GitHub Action"],
    [TOOL, '<span aria-hidden="true">★</span> star the project on GitHub'],
  ]);
  assert.match(line[1], /^wheelgap is open source\. /);
  // Plain links: the page's Content-Security-Policy allows no remote images or frames, so no star-count widget.
  assert.doesNotMatch(line[1], /<(img|iframe|script)\b/);
  assert.doesNotMatch(read("check.mjs"), /star-line[^\n]*innerHTML/);
});

test("the line shows with a result (gaps or none) and hides when there is nothing to show", () => {
  const source = read("check.mjs").match(/^function hideResultSections\(.*?^}$/ms);
  assert.ok(source, "hideResultSections is in check.mjs");
  const made = new Map();
  const element = (key) => {
    if (!made.has(key)) made.set(key, { hidden: null, classList: { remove() {} }, closest: () => element(`${key} section`) });
    return made.get(key);
  };
  const hideResultSections = new Function("$", `${source[0]}; return hideResultSections;`)(element);
  hideResultSections(false);        // render(): a result, whether it found gaps or every wheel
  assert.equal(element("star-line").hidden, false);
  assert.equal(element("gaps-title section").hidden, false);
  hideResultSections(true);         // no lockfile found
  assert.equal(element("star-line").hidden, true);
  hideResultSections(true, true);   // a lockfile the browser can't check
  assert.equal(element("star-line").hidden, true);
  assert.equal(element("setup-title section").hidden, false);
});

test("a result with no package checked shows the verdict and the setup, but no bars or table to read as a pass", () => {
  const source = read("check.mjs").match(/^function render\(\) \{.*?^}$/ms);
  assert.ok(source, "render is in check.mjs");
  const parts = ["hideResultSections", "renderVerdict", "renderSetup", "renderTargets", "renderTable", "renderNext"];
  const calls = [];
  const render = (packages) => new Function("state", ...parts, `${source[0]}; return render;`)(
    { result: { packages } },
    ...parts.map((name) => (...args) => { calls.push([name, ...args]); }),
  );
  render(0)(); // every package skipped as a private index's, or a file that lists none
  assert.deepEqual(calls, [["hideResultSections", false], ["renderVerdict"], ["renderSetup"], ["hideResultSections", true, true]]);
  calls.length = 0;
  render(3)();
  assert.deepEqual(calls.map(([name]) => name), parts);
});

// worker.mjs needs a browser and Pyodide, so its check() is run on stand-ins for both: `needs` is what the driver asks
// to be looked up, `fetch` answers for pypi.org, and `checked` collects what the driver's check() is handed.
function workerCheck({ needs, fetch, releases = new Map(), lockfile = "requirements.txt", fetched = [lockfile], gone = [] }) {
  const source = read("worker.mjs");
  const fn = (name) => {
    const found = source.match(new RegExp(`^(?:async )?function ${name}\\(.*?^}$`, "ms"));
    assert.ok(found, `${name} is in worker.mjs`);
    return found[0];
  };
  const checked = [];
  const fixed = [];
  const removed = [];
  // `gone`: paths the worker believes it wrote that aren't in Pyodide's files any more, so removing them throws.
  const unlink = (path) => { removed.push(path); if (gone.includes(path)) throw new Error(`ENOENT: ${path}`); };
  const driver = {
    needs: () => JSON.stringify(needs),
    check: (...args) => { checked.push(args); return JSON.stringify({ rows: [] }); },
    fixes: (...args) => { fixed.push(args); return "{}"; },
  };
  const repo = { root: "/repos/1", ref: "HEAD", fetched: new Set(fetched) };
  const env = {
    fetch, releases, MAX_LOOKUPS: 300, MAX_FIX_LOOKUPS: 80,
    trimProject: checkLogic.trimProject, trimReleases: checkLogic.trimReleases,
    ready: Promise.resolve({ py: { FS: { unlink } }, driver }),
    loaded: new Map([[repo.root, repo]]),
    post: () => {},
  };
  const made = new Function("env", `
    const { fetch, releases, MAX_LOOKUPS, MAX_FIX_LOOKUPS, ready, loaded, post, trimProject, trimReleases } = env;
    let latestCheck = 7;
    class Failure extends Error { constructor(kind, message) { super(message); this.kind = kind; } }
    ${fn("pool")}
    ${fn("lookups")}
    ${fn("dropOtherProjects")}
    ${fn("check")}
    ${fn("fixes")}
    return {
      check: (lockfile) => check(7, "/repos/1", lockfile, { pythons: ["3.14"] }),
      fixes: (rows) => fixes(7, rows), supersede: () => { latestCheck = 8; },
    };
  `)(env);
  return { check: () => made.check(lockfile), fixes: made.fixes, supersede: made.supersede, checked, fixed, releases, removed, repo };
}

test("check trims pinned and project JSON before the driver and keeps only trimmed releases for fixes", async () => {
  const file = { filename: "fastlib-1.0.tar.gz", requires_python: ">=3.13", yanked: false, digests: { sha256: "unused" } };
  const doc = { info: { version: "1.0", description: "unused".repeat(1000) }, urls: [file], releases: { "1.0": [file] }, last_serial: 123 };
  const needs = { lookups: [{ name: "fastlib", version: null }, { name: "pinned", version: "1.0" }], total: 2 };
  const worker = workerCheck({ needs, fetch: async () => ({ ok: true, json: async () => structuredClone(doc) }) });
  await worker.check();
  const keptFile = { filename: file.filename, requires_python: ">=3.13", yanked: false };
  const kept = { info: { version: "1.0" }, urls: [keptFile], releases: { "1.0": [keptFile] } };
  assert.deepEqual(JSON.parse(worker.checked[0][3]), { fastlib: kept, "pinned==1.0": kept });
  assert.deepEqual([...worker.releases], [["fastlib", kept.releases]]); // never cache a pinned response
  assert.ok(worker.checked[0][3].length < JSON.stringify({ fastlib: doc, "pinned==1.0": doc }).length / 2);
});

test("fixes trims newly fetched releases and reuses the trimmed releases from check", async () => {
  const fetched = [];
  const file = { filename: "fastlib-2.0-py3-none-any.whl", yanked: false, url: "https://files.pythonhosted.org/unused" };
  const doc = { info: { description: "unused" }, urls: [], releases: { "2.0": [file] } };
  const worker = workerCheck({
    needs: { lookups: [{ name: "cached", version: null }], total: 1 },
    fetch: async (url) => { fetched.push(url); return { ok: true, json: async () => structuredClone(doc) }; },
  });
  await worker.check();
  const rows = ["cached", "fresh"].map((name) => ({ name, version: "1.0", lookup: true, gaps: ["3.13 linux-x86_64"], keep: [] }));
  await worker.fixes(rows);
  const kept = { "2.0": [{ filename: file.filename, yanked: false }] };
  assert.deepEqual(fetched, ["https://pypi.org/pypi/cached/json", "https://pypi.org/pypi/fresh/json"]);
  assert.deepEqual([...worker.releases], [["cached", kept], ["fresh", kept]]);
  assert.deepEqual(JSON.parse(worker.fixed[0][0]), { cached: kept, fresh: kept });
  assert.deepEqual(JSON.parse(worker.fixed[0][1]), rows);
  await worker.fixes(rows);
  assert.equal(fetched.length, 2); // both compact lists survive for the next check's fixes
});

test("the worker looks up what the driver names on pypi.org and hands the answers to the driver's check", async () => {
  const urls = [];
  const fetch = async (url) => {
    urls.push(url);
    if (url.includes("/gone/")) return { ok: false, status: 404 };
    // As PyPI answers: a release's JSON has no `releases`, a project's JSON does.
    const doc = url.endsWith("/numpy/2.3.4/json") ? { info: {}, urls: [] } : { info: {}, urls: [], releases: { "2.0.0": [] } };
    return { ok: true, status: 200, json: async () => doc };
  };
  const needs = { lookups: [{ name: "numpy", version: "2.3.4" }, { name: "fastlib", version: null }, { name: "gone", version: "1.0" }], total: 3 };
  const { check, checked, releases } = workerCheck({ needs, fetch });
  await check();
  assert.deepEqual(urls.sort(), [
    "https://pypi.org/pypi/fastlib/json",
    "https://pypi.org/pypi/gone/1.0/json",
    "https://pypi.org/pypi/numpy/2.3.4/json",
  ]);
  assert.equal(checked.length, 1);
  const [root, file, , lookups] = checked[0];
  assert.deepEqual([root, file], ["/repos/1", "requirements.txt"]);
  assert.deepEqual(JSON.parse(lookups), {
    "numpy==2.3.4": { info: {}, urls: [] },
    fastlib: { info: {}, urls: [], releases: { "2.0.0": [] } },
    "gone==1.0": null, // a 404: the driver reports it as unknown
  });
  // fixes() asks PyPI for a project's release list unless this cache has its name. A pinned release's JSON has no
  // release list, so caching it under the name would leave every gap of a pinned file "not looked up".
  assert.deepEqual([...releases], [["fastlib", { "2.0.0": [] }]]);
});

test("a lockfile that lists its files makes no request to PyPI, and the driver's check is still handed JSON text", async () => {
  const fetch = async () => assert.fail("no lookup was asked for");
  const { check, checked } = workerCheck({ needs: { lookups: [], total: 0 }, fetch });
  await check();
  assert.equal(checked[0][3], "{}"); // never a JS null, which Pyodide may not turn into None
});

test("the worker counts the lookups that got no answer, for the page to say why packages are unknown", async () => {
  const signals = [];
  const fetch = async (url, init) => {
    signals.push(init?.signal);
    if (url.includes("/down/")) throw new TypeError("Failed to fetch");
    if (url.includes("/slow/")) throw new DOMException("The operation timed out.", "TimeoutError");
    if (url.includes("/busy/")) return { ok: false, status: 503 };
    if (url.includes("/gone/")) return { ok: false, status: 404 };
    if (url.includes("/html/")) return { ok: true, status: 200, json: async () => { throw new SyntaxError("Unexpected token <"); } };
    return { ok: true, status: 200, json: async () => ({ info: {}, urls: [] }) };
  };
  const names = ["fine", "down", "slow", "busy", "gone", "html"];
  const needs = { lookups: names.map((name) => ({ name, version: "1.0" })), total: names.length };
  const { check, checked } = workerCheck({ needs, fetch });
  const result = await check();
  assert.deepEqual(result.missed, { cap: 300, over_cap: 0, not_found: 1, failed: 4 });
  // Only an answer, or PyPI's "no such release", reaches the driver: the rest have no key, and stay "not looked up".
  assert.deepEqual(JSON.parse(checked[0][3]), { "fine==1.0": { info: {}, urls: [] }, "gone==1.0": null });
  // Every lookup can be given up on after a while: a stalled one would otherwise hold the whole check.
  assert.equal(signals.length, names.length);
  assert.ok(signals.every((signal) => signal instanceof AbortSignal));
});

test("lookups over the cap aren't made, and the result says how many there were", async () => {
  const urls = [];
  const fetch = async (url) => {
    urls.push(url);
    return { ok: true, status: 200, json: async () => ({ info: {}, urls: [] }) };
  };
  const needs = { lookups: Array.from({ length: 301 }, (_, i) => ({ name: `pkg${i}`, version: "1.0" })), total: 301 };
  const { check, checked } = workerCheck({ needs, fetch });
  const result = await check();
  assert.equal(urls.length, 300);
  assert.deepEqual(result.missed, { cap: 300, over_cap: 1, not_found: 0, failed: 0 });
  const lookups = JSON.parse(checked[0][3]);
  assert.equal(Object.keys(lookups).length, 300);
  assert.equal("pkg300==1.0" in lookups, false); // no key: the driver reports it as unknown, never as a gap
});

test("a check superseded while it looks packages up stops asking PyPI and never reaches the driver's check", async () => {
  let supersede = () => {};
  const urls = [];
  const fetch = async (url) => {
    urls.push(url);
    supersede(); // a newer check arrives while this one is in flight
    return { ok: true, status: 200, json: async () => ({ info: {}, urls: [] }) };
  };
  const needs = { lookups: Array.from({ length: 20 }, (_, i) => ({ name: `pkg${i}`, version: "1.0" })), total: 20 };
  const worker = workerCheck({ needs, fetch });
  supersede = worker.supersede;
  await assert.rejects(worker.check(), (e) => e.kind === "stale");
  assert.equal(worker.checked.length, 0); // the driver keeps the last check's targets for fixes(): not a stale one's
  assert.ok(urls.length <= 6, `the six in flight at most, not all twenty: ${urls.length}`);
});

test("a pyproject.toml that was fetched to be checked is gone again before another file is read", async () => {
  // wheelgap reads the pyproject.toml beside a uv.lock for [tool.uv] settings when it's there: left behind, a uv.lock
  // checked after the pyproject.toml could answer differently from the same uv.lock checked first.
  const fetch = async () => assert.fail("no lookup was asked for");
  const fetched = ["uv.lock", "pyproject.toml", "backend/pyproject.toml", "requirements.txt"];
  const lock = workerCheck({ needs: { lookups: [], total: 0 }, fetch, lockfile: "uv.lock", fetched });
  await lock.check();
  assert.deepEqual(lock.removed, ["/repos/1/pyproject.toml", "/repos/1/backend/pyproject.toml"]);
  assert.deepEqual([...lock.repo.fetched], ["uv.lock", "requirements.txt"]); // fetched again if it's picked again
  // The one being checked stays, of course.
  const project = workerCheck({ needs: { lookups: [], total: 0 }, fetch, lockfile: "pyproject.toml", fetched });
  await project.check();
  assert.deepEqual(project.removed, ["/repos/1/backend/pyproject.toml"]);
  assert.equal(project.checked[0][1], "pyproject.toml");
  // A check that's already superseded removes nothing: the newer check may be about to read that file.
  const stale = workerCheck({ needs: { lookups: [], total: 0 }, fetch, lockfile: "uv.lock", fetched });
  stale.supersede();
  await assert.rejects(stale.check(), (e) => e.kind === "stale");
  assert.deepEqual([stale.removed, stale.checked], [[], []]);
  // One that's already gone from the worker's files isn't an error, and isn't tried again on the next check.
  const missing = workerCheck({ needs: { lookups: [], total: 0 }, fetch, lockfile: "uv.lock", fetched, gone: ["/repos/1/pyproject.toml"] });
  await missing.check();
  assert.deepEqual(missing.removed, ["/repos/1/pyproject.toml", "/repos/1/backend/pyproject.toml"]);
  assert.deepEqual([...missing.repo.fetched], ["uv.lock", "requirements.txt"]);
  assert.equal(missing.checked.length, 1);
});

test("the badge is a small static image on the page's own origin, offered as Markdown under the copy buttons", () => {
  const svg = read("badge.svg");
  assert.ok(Buffer.byteLength(svg) < 1500, "around 1 KB");
  assert.match(svg, /^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg" width="146" height="20" role="img" aria-label="wheelgap: check wheels"><title>wheelgap: check wheels<\/title>/);
  // Nothing that runs or loads: GitHub serves README images through its proxy, which drops such an SVG.
  assert.doesNotMatch(svg, /<script|<style|<image|<use|<foreignObject|href=|\bon[a-z]+=|@import|url\((?!#)/i);
  assert.deepEqual([...svg.matchAll(/>([^<>]+)<\/text>/g)].map((m) => m[1]), ["wheelgap", "wheelgap", "check wheels", "check wheels"]);

  const html = read("index.html");
  const fix = html.slice(html.indexOf('id="next-title"'), html.indexOf('id="caveats"'));
  const section = fix.match(/<section id="badge" aria-labelledby="badge-title">(.*?)<\/section>/s);
  assert.ok(section, "the badge is in the Fix it section");
  assert.ok(fix.indexOf('id="copy-link"') < fix.indexOf('id="badge"'), "under the two Copy buttons");
  assert.match(section[1], /<h3 id="badge-title">Add a badge to your README<\/h3>/);
  // Same origin, so the page's `img-src 'self'` allows it; and it says it isn't a result.
  assert.match(section[1], /<img class="badge-img" src="badge\.svg" alt="wheelgap: check wheels" width="146" height="20">/);
  assert.match(html, /img-src 'self' data:;/);
  assert.match(section[1], /shows no result/);
  assert.match(section[1], /<pre><code id="badge-md"><\/code><\/pre>\s*<button type="button" class="action" id="copy-badge">Copy badge Markdown<\/button>/);

  const page = read("check.mjs");
  // Filled in as text, from the pure helper, and copied the way the other buttons copy.
  assert.match(page, /\$\("badge-md"\)\.textContent = badgeMarkdown\(state\.repo, r\.lockfile, pickLockfile\(state\.plan\.lockfiles, null\)\?\.path \?\? null\);/);
  assert.match(page, /\$\("copy-badge"\)\.onclick = \(e\) => copy\(e\.currentTarget, \$\("badge-md"\)\.textContent, "Badge Markdown copied"\);/);
  assert.doesNotMatch(page, /innerHTML/);
});

test("renderTable shows the links in the Fix cell and the package-name link for a package the tracker has, and neither for one it doesn't", () => {
  const source = read("check.mjs");
  const fn = (name) => {
    const found = source.match(new RegExp(`^(?:async )?function ${name}\\(.*?^}$`, "ms"));
    assert.ok(found, `${name} is in check.mjs`);
    return found[0];
  };
  const elements = new Map();
  const $ = (id) => {
    if (!elements.has(id)) {
      elements.set(id, {
        textContent: "",
        hidden: false,
        children: [],
        classList: { toggle() {}, remove() {}, add() {} },
        closest: () => ({ classList: { toggle() {}, remove() {} } }),
        replaceChildren: (...kids) => { elements.get(id).children = kids; },
      });
    }
    return elements.get(id);
  };
  const el = (tag, attrs = {}, ...kids) => {
    const text = attrs.text || "";
    const flatKids = kids.flat().filter(Boolean);
    const kidTexts = flatKids.map((k) => (typeof k === "string" ? k : k?.text || k?.textContent || "")).join("");
    return {
      tag,
      attrs,
      text: text + kidTexts,
      textContent: text + kidTexts,
      children: flatKids,
    };
  };

  const state = {
    python: "3.14",
    platform: "linux-x86_64",
    fixesDone: true,
    showAll: false,
    fixes: {
      "has-tracker==1.0": { found: {}, loses: [] },
      "no-tracker==2.0": { found: {}, loses: [] },
    },
    gapWheels: null,
    lab: {
      "has-tracker": { ok: true, builds: [], issues_url: "https://github.com/org/has-tracker/issues" },
      "no-tracker": { ok: false, builds: [], issues_url: null },
    },
    result: {
      lockfile: "uv.lock",
      outside_lock: [],
      targets: [{ python: "3.14", platform: "linux-x86_64", label: "3.14 linux-x86_64" }],
      rows: [
        {
          name: "has-tracker",
          version: "1.0",
          gaps: ["3.14 linux-x86_64"],
          statuses: { "3.14 linux-x86_64": "source" },
          lookup: true,
          here: ["3.14 linux-x86_64"],
        },
        {
          name: "no-tracker",
          version: "2.0",
          gaps: ["3.14 linux-x86_64"],
          statuses: { "3.14 linux-x86_64": "source" },
          lookup: true,
          here: ["3.14 linux-x86_64"],
        },
      ],
    },
  };

  const NAMES = { "linux-x86_64": "Linux x86_64" };
  const STATUS_TEXT = { source: "source" };
  const LAB_SHORT = {};
  const FIX_TEXT = { none: () => "no newer release has a wheel" };
  const SHOWN = 60;

  const runTable = new Function(
    "$", "state", "el", "rowsFor", "fixFor", "gapWheelFixText", "canonicalName", "fixLinks", "labFor", "labVerdict", "gapWheelFor", "NAMES", "STATUS_TEXT", "LAB_SHORT", "FIX_TEXT", "SHOWN",
    `
    ${fn("renderTable")}
    return renderTable;
    `
  )(
    $, state, el,
    checkLogic.rowsFor, checkLogic.fixFor, checkLogic.gapWheelFixText, checkLogic.canonicalName,
    checkLogic.fixLinks, checkLogic.labFor, checkLogic.labVerdict, checkLogic.gapWheelFor,
    NAMES, STATUS_TEXT, LAB_SHORT, FIX_TEXT, SHOWN
  );

  runTable();

  const table = $("gap-table");
  assert.equal(table.hidden, false);
  const tbody = table.children[1];
  assert.ok(tbody, "tbody was rendered");
  const trs = tbody.children;
  assert.equal(trs.length, 2);

  // Row 1: has-tracker (tracker has the package)
  const trHas = trs[0];
  const pkgHas = trHas.children[0]; // td.pkg
  const fixHas = trHas.children[2]; // td.fix

  // Package name links to tracker page, and PyPI link is beside it
  const pkgHasLinks = pkgHas.children.filter((c) => c.tag === "a");
  assert.equal(pkgHasLinks.length, 2);
  assert.equal(pkgHasLinks[0].attrs.href, "../p/has-tracker/");
  assert.equal(pkgHasLinks[0].text, "has-tracker");
  assert.equal(pkgHasLinks[1].attrs.href, "https://pypi.org/project/has-tracker/1.0");
  assert.equal(pkgHasLinks[1].text, "PyPI");

  // Fix cell has "coverage and build results" and "ask the maintainers"
  const fixHasLinks = fixHas.children.flatMap((c) => c.children || []).filter((c) => c.tag === "a");
  assert.equal(fixHasLinks.length, 2);
  assert.equal(fixHasLinks[0].attrs.href, "../p/has-tracker/");
  assert.equal(fixHasLinks[0].text, "coverage and build results");
  assert.equal(fixHasLinks[1].attrs.href, "https://github.com/org/has-tracker/issues");
  assert.equal(fixHasLinks[1].text, "ask the maintainers");
  assert.equal(fixHasLinks[1].attrs.rel, "noopener nofollow");

  // Row 2: no-tracker (tracker does NOT have the package)
  const trNo = trs[1];
  const pkgNo = trNo.children[0]; // td.pkg
  const fixNo = trNo.children[2]; // td.fix

  // Package name links directly to PyPI, no separate tracker link, no PyPI link beside it
  const pkgNoLinks = pkgNo.children.filter((c) => c.tag === "a");
  assert.equal(pkgNoLinks.length, 1);
  assert.equal(pkgNoLinks[0].attrs.href, "https://pypi.org/project/no-tracker/2.0");
  assert.equal(pkgNoLinks[0].text, "no-tracker");

  // Fix cell has neither link
  const fixNoLinks = fixNo.children.flatMap((c) => c.children || []).filter((c) => c.tag === "a");
  assert.equal(fixNoLinks.length, 0);
});
