"""Tests for the bundled FITAGE dashboard card and its frontend registration."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.fitage import async_setup
from custom_components.fitage.frontend import (
    CARD_FILENAME,
    CARD_VERSION,
    LEGACY_PROTOTYPE_URL_PATH,
    MODULE_URL,
    STATIC_URL_PATH,
    async_register_frontend,
)

CARD_PATH = (
    Path(__file__).parents[1] / "custom_components" / "fitage" / "www" / CARD_FILENAME
)

_JS_VERSION_RE = re.compile(r"""const\s+VERSION\s*=\s*["']([^"']+)["']""")


def _find_node() -> str | None:
    """Locate a Node.js runtime for real JS-behavior tests. Falls back to
    the editor-bundled binary in this dev container when `node` is not on
    PATH; tests using this skip gracefully if neither is found."""
    if node := shutil.which("node"):
        return node
    for candidate in Path("/vscode/vscode-server/bin").glob("linux-x64/*/node"):
        if candidate.is_file():
            return str(candidate)
    return None


NODE_BIN = _find_node()


def _run_node_js(harness: str, **js_consts: object) -> subprocess.CompletedProcess:
    """Run a Node.js harness with CARD_PATH (and any extra JS consts) defined
    ahead of it, so tests can drive the real bundled card under Node instead
    of only pattern-matching its source text."""
    prelude = f"const CARD_PATH = {json.dumps(str(CARD_PATH))};\n"
    for name, value in js_consts.items():
        prelude += f"const {name} = {json.dumps(value)};\n"
    return subprocess.run(
        [NODE_BIN, "-e", prelude + harness],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


_LOAD_CARD_JS_PRELUDE = r"""
class FakeElement {
  attachShadow() { this.shadowRoot = { innerHTML: "", querySelector: () => null, querySelectorAll: () => [] }; return this.shadowRoot; }
}
global.HTMLElement = FakeElement;
global.customElements = { registry: new Map(), get(n){return this.registry.get(n)}, define(n,c){this.registry.set(n,c)} };
global.window = { customCards: undefined, loadCardHelpers: async () => ({ createCardElement: () => ({}) }) };
global.document = { createElement: () => ({}) };

const fs = require("fs");
const src = fs.readFileSync(CARD_PATH, "utf8");
eval(src);

const Card = customElements.get("fitage-card");
"""

_STUB_HINT_JS_HARNESS = (
    _LOAD_CARD_JS_PRELUDE
    + r"""
async function run(profile, hass) {
  const el = Object.create(Card.prototype);
  el.attachShadow = FakeElement.prototype.attachShadow;
  el.attachShadow();
  el.range = "1m"; el.graphs = new Map(); el.latest = new Map(); el.graphGeneration = 0;
  el.setConfig({ profile });
  el._hass = hass;
  await el.initialize();
  return { error: el.error, hint: el.hint };
}

(async () => {
  const hassEmpty = { callWS: async ({type}) => type === "recorder/list_statistic_ids" ? [] : {}, states: {} };

  const stub = await run("jouw_profiel", hassEmpty);
  if (stub.error) throw new Error("stub profile must not set this.error: " + stub.error);
  if (stub.hint !== "Kies een FITAGE-profiel in de kaarteditor.") throw new Error("stub profile must set the neutral hint, got: " + stub.hint);

  const invalid = await run("een_niet_bestaand_profiel", hassEmpty);
  if (!invalid.error) throw new Error("a real but invalid profile must still set this.error");
  if (invalid.hint) throw new Error("a real but invalid profile must not set the neutral hint");

  console.log("ALL JS BEHAVIOR CHECKS PASSED");
})().catch(e => { console.error(e); process.exit(1); });
"""
)

_FORMAT_JS_HARNESS = (
    _LOAD_CARD_JS_PRELUDE
    + r"""
const cases = CASES;
const failures = [];
for (const [value, unit, key, expected] of cases) {
  const actual = Card.prototype.format(value, unit, key);
  if (actual !== expected) {
    failures.push(`format(${JSON.stringify(value)}, ${JSON.stringify(unit)}, ${JSON.stringify(key)}) = ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`);
  }
}
if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("ALL FORMAT CHECKS PASSED");
"""
)

_FIND_PREFIX_JS_HARNESS = (
    _LOAD_CARD_JS_PRELUDE
    + r"""
function makeEl(slug, states, statsById) {
  const el = Object.create(Card.prototype);
  el.slug = slug;
  el.config = {};
  el._hass = {
    states: states || {},
    callWS: async ({ type, statistic_ids }) => {
      if (type !== "recorder/statistics_during_period") return {};
      const out = {};
      for (const id of statistic_ids) out[id] = (statsById || {})[id] || [];
      return out;
    },
  };
  return el;
}

(async () => {
  // 1) Structural fix: "fitage:aaa_fat_free_weight" must never be mistaken
  // for a weight statistic just because it also ends in "_weight".
  {
    const el = makeEl("profiel_een", {});
    const prefix = await el.findPrefix(["fitage:aaa_weight", "fitage:aaa_fat_free_weight"], []);
    if (prefix !== "fitage:aaa") throw new Error("check 1: expected fitage:aaa, got " + prefix);
  }

  // 2) Reliable statistic metadata (the display name our own backend writes
  // in statistics.py) resolves the right profile deterministically, with no
  // value comparison involved at all.
  {
    const el = makeEl("piet", {});
    const metadata = [
      { statistic_id: "fitage:h1_weight", name: "FITAGE Jan – Weight" },
      { statistic_id: "fitage:h2_weight", name: "FITAGE Piet – Weight" },
    ];
    const prefix = await el.findPrefix(["fitage:h1_weight", "fitage:h2_weight"], metadata);
    if (prefix !== "fitage:h2") throw new Error("check 2: expected fitage:h2, got " + prefix);
  }

  // 3) Two profiles whose display names collide (the "(<hex>)" disambiguation
  // suffix statistics.py appends stripped back off) must never be guessed
  // between, even with metadata present.
  {
    const el = makeEl("jan", {});
    const metadata = [
      { statistic_id: "fitage:h1_weight", name: "FITAGE Jan (a1b2) – Weight" },
      { statistic_id: "fitage:h2_weight", name: "FITAGE Jan (a1b3) – Weight" },
    ];
    const prefix = await el.findPrefix(["fitage:h1_weight", "fitage:h2_weight"], metadata);
    if (prefix !== null) throw new Error("check 3: expected null for a colliding display name, got " + prefix);
  }

  // 4) Without usable metadata, a single unambiguously close value candidate
  // still resolves - the pre-existing fallback behavior stays intact.
  {
    const el = makeEl("profiel_een", { "sensor.profiel_een_weight": { state: "80.0" } }, {
      "fitage:h1_weight": [{ state: "80.05" }],
      "fitage:h2_weight": [{ state: "95.0" }],
    });
    const prefix = await el.findPrefix(["fitage:h1_weight", "fitage:h2_weight"], []);
    if (prefix !== "fitage:h1") throw new Error("check 4: expected fitage:h1, got " + prefix);
  }

  // 5) Two candidates equally close to the live value must never be guessed
  // between - the multi-profile ambiguity this whole fix is about.
  {
    const el = makeEl("profiel_een", { "sensor.profiel_een_weight": { state: "80.0" } }, {
      "fitage:h1_weight": [{ state: "80.05" }],
      "fitage:h2_weight": [{ state: "80.06" }],
    });
    const prefix = await el.findPrefix(["fitage:h1_weight", "fitage:h2_weight"], []);
    if (prefix !== null) throw new Error("check 5: expected null for two equally plausible candidates, got " + prefix);
  }

  console.log("ALL FIND-PREFIX CHECKS PASSED");
})().catch((e) => { console.error(e.stack || e); process.exit(1); });
"""
)

# Reproduces, in isolation, the exact Home Assistant lazy-loading race that
# caused "TypeError: Cannot read properties of undefined (reading 'config')"
# in hui-graph-header-footer's _subscribeHistory(): per Home Assistant's own
# src/panels/lovelace/create-element/create-element-base.ts (_lazyCreate),
# createCardElement() for a not-yet-loaded card type returns an unconfigured
# element synchronously and only calls customElements.upgrade(element) then
# element.setConfig(config) later, inside a .then() on
# customElements.whenDefined(tag). A first fix (awaiting that promise before
# ever *attaching* the element to the DOM) was not enough: setting a
# property such as .hass on the still-un-upgraded element in the meantime
# creates a plain own data property; verified against the real, locally
# installed home-assistant-frontend in an actual Chromium build, upgrading
# such an element deletes that shadowing own property but does *not* replay
# its value through the real accessor - the assigned value is silently
# lost, .hass reads back as undefined, and any nested element that reads
# this.hass.config throws exactly the reported TypeError. This harness
# implements just enough of customElements/DOM (FakeRegistry/FakeContainer,
# with a real GraphCard constructor/prototype so property lookup exhibits
# the actual own-property-shadows-prototype-accessor dynamic) to reproduce
# both the upgrade-then-setConfig ordering and the hass-shadowing
# faithfully, then drives the real, bundled createGraphs()/render()/hass
# setter through it.
_GRAPH_LIFECYCLE_JS_HARNESS = r"""
const fs = require("fs");
const src = fs.readFileSync(CARD_PATH, "utf8");
class FakeContainer {
  constructor() { this.child = null; }
  replaceChildren(el) {
    if (this.child && this.child !== el) {
      this.child.__connected = false;
      if (this.child.__upgraded && typeof this.child.disconnectedCallback === "function") this.child.disconnectedCallback();
    }
    this.child = el || null;
    if (el) {
      el.__connected = true;
      if (el.__upgraded && typeof el.connectedCallback === "function") el.connectedCallback();
    }
  }
  disconnect() {
    if (this.child) {
      this.child.__connected = false;
      if (this.child.__upgraded && typeof this.child.disconnectedCallback === "function") this.child.disconnectedCallback();
    }
  }
}
class FakeRegistry {
  constructor() { this.factories = new Map(); this.waiters = new Map(); }
  define(tag, value) {
    this.factories.set(tag, value);
    const list = this.waiters.get(tag);
    if (list) { this.waiters.delete(tag); list.forEach((resolve) => resolve()); }
  }
  get(tag) { return this.factories.get(tag); }
  whenDefined(tag) {
    if (this.factories.has(tag)) return Promise.resolve();
    return new Promise((resolve) => {
      const list = this.waiters.get(tag) || [];
      list.push(resolve);
      this.waiters.set(tag, list);
    });
  }
  upgrade(el) {
    const Ctor = this.factories.get(el.__tag);
    if (!Ctor || el.__upgraded || !Ctor.__isLovelaceStub) return;
    upgradeElement(el, Ctor);
    el.__upgraded = true;
    if (el.__connected && typeof el.connectedCallback === "function") el.connectedCallback();
  }
}
const registry = new FakeRegistry();
global.customElements = registry;
const GRAPH_CARD_TAG = "hui-statistics-graph-card";
const violations = [];
// A real constructor + prototype (not per-instance methods) so property
// lookup exhibits the actual own-property-shadows-prototype-accessor
// dynamic this whole fix is about, and `instanceof` behaves like it does
// for a real, defined custom element class. hassSetterCalls only
// increments when an assignment genuinely reaches this accessor - the
// decisive signal a plain instance-property shadow was never used.
let hassSetterCalls = 0;
class GraphCard {
  setConfig(cfg) { this._config = cfg; }
  connectedCallback() {
    if (this._config === undefined) violations.push("connectedCallback fired with _config still undefined");
    if (this.hass === undefined) violations.push("connectedCallback fired with hass still undefined");
  }
  disconnectedCallback() {}
}
GraphCard.__isLovelaceStub = true;
Object.defineProperty(GraphCard.prototype, "hass", {
  configurable: true,
  get() { return this.__hassValue; },
  set(v) { hassSetterCalls += 1; this.__hassValue = v; },
});
function upgradeElement(el, Ctor) {
  // Verified against the real, locally installed home-assistant-frontend in
  // an actual Chromium build: upgrading an element whose "hass" was set
  // beforehand (an own data property, since no accessor existed yet)
  // deletes that shadowing own property, but does *not* replay its value
  // through the real accessor - the assigned value is silently lost, and
  // .hass reads back as undefined afterwards. Reproduced faithfully here.
  if (Object.hasOwn(el, "hass")) delete el.hass;
  Object.setPrototypeOf(el, Ctor.prototype);
}
global.document = {
  createElement(tag) {
    const el = { __tag: tag, __upgraded: false, __connected: false };
    const Ctor = registry.get(tag);
    if (Ctor && Ctor.__isLovelaceStub) { upgradeElement(el, Ctor); el.__upgraded = true; }
    return el;
  },
};
let createCount = 0;
const createWaiters = [];
function waitForCreateCount(n) {
  if (createCount >= n) return Promise.resolve();
  return new Promise((resolve) => createWaiters.push({ n, resolve }));
}
function haCreateCardElement(config) {
  const tag = `hui-${config.type}-card`;
  let el;
  if (registry.get(tag)) {
    el = document.createElement(tag);
    el.setConfig(config);
  } else {
    el = document.createElement(tag);
    registry.whenDefined(tag).then(() => {
      registry.upgrade(el);
      el.setConfig(config);
    });
  }
  createCount += 1;
  for (let i = createWaiters.length - 1; i >= 0; i -= 1) {
    if (createWaiters[i].n <= createCount) { createWaiters[i].resolve(); createWaiters.splice(i, 1); }
  }
  return el;
}
global.window = { customCards: undefined, loadCardHelpers: async () => ({ createCardElement: haCreateCardElement }) };
class FakeElement {
  constructor() {
    // A newly created custom element starts out connected to the DOM in
    // these scenarios (matching Home Assistant inserting a freshly built
    // card into a dashboard/preview); scenario J flips this to false to
    // simulate removal.
    this.isConnected = true;
  }
  attachShadow() {
    const containers = new Map();
    let html = "";
    this.shadowRoot = {
      get innerHTML() { return html; },
      set innerHTML(value) { html = value; containers.forEach((c) => c.disconnect()); },
      querySelector(sel) {
        if (!containers.has(sel)) containers.set(sel, new FakeContainer());
        return containers.get(sel);
      },
      querySelectorAll: () => [],
    };
    return this.shadowRoot;
  }
}
global.HTMLElement = FakeElement;

eval(src);
const Card = customElements.get("fitage-card");

function makeCard(available) {
  const el = Object.create(Card.prototype);
  el.isConnected = true;
  el.attachShadow();
  el.range = "1m";
  el.graphs = new Map();
  el.latest = new Map();
  el.graphGeneration = 0;
  el.config = { title: "FITAGE", display: "graphs", profile: "test_profiel" };
  el.slug = "test_profiel";
  el.statisticPrefix = "fitage:test_profiel";
  el._hass = { states: {}, config: { components: [] } };
  el.ready = true;
  el.initialized = true; // a real ready:true card would already have completed initialize()
  el.available = available;
  return el;
}

const oneMetric = () => [{ key: "weight", title: "Gewicht", entity: "weight", unit: "kg" }];

function makeFreshCard() {
  // A genuinely new instance the way Home Assistant creates one - via the
  // real constructor, with neither hass nor config assigned yet - so these
  // scenarios exercise the real setConfig()/hass ordering guards, not a
  // hand-poked internal state.
  return new Card();
}
function fakeHass(profile) {
  return {
    config: { components: [] },
    states: {},
    callWS: async ({ type }) => {
      if (type === "recorder/list_statistic_ids") {
        return [{ statistic_id: `fitage:${profile}_weight` }];
      }
      return {};
    },
  };
}
// Like fakeHass(), but callWS() only resolves once `gate` resolves - lets a
// test hold initialize()'s prefix resolution open to switch the config
// (e.g. to the stub profile) while it is still in flight.
function fakeHassGated(profile, gate) {
  return {
    config: { components: [] },
    states: {},
    callWS: async ({ type }) => {
      await gate;
      if (type === "recorder/list_statistic_ids") {
        return [{ statistic_id: `fitage:${profile}_weight` }];
      }
      return {};
    },
  };
}
const STUB_PROFILE_VALUE = "jouw_profiel"; // mirrors fitage-card.js's own STUB_PROFILE constant, not reachable directly since it is scoped to the eval() below
// Test-only synchronization: lets an already-scheduled async chain
// (initialize() -> listStatistics() -> findPrefix() -> loadLatest() ->
// createGraphs() -> whenDefined()) actually settle before asserting on its
// outcome. This is purely a test-timing helper, never part of the
// production ordering guarantee itself, which relies solely on the
// setConfig()/hass two-sided gate and the generation token.
function settle() { return new Promise((resolve) => setTimeout(resolve, 20)); }

async function scenarioA_setConfigBeforeAttach() {
  const el = makeCard(oneMetric());
  const hassBefore = hassSetterCalls;
  const before = createCount;
  const p = el.createGraphs();
  await waitForCreateCount(before + 1);
  // The lazy module "finishes loading" only now - after the element was
  // already constructed but before production code has touched any
  // property on it.
  registry.define(GRAPH_CARD_TAG, GraphCard);
  await p;
  const container = el.shadowRoot.querySelector("#graph-weight");
  if (!container.child) throw new Error("scenario A: no graph element ended up attached");
  if (container.child.hass === undefined) throw new Error("scenario A: attached element has no hass");
  if (container.child.hass !== el._hass) throw new Error("scenario A: attached element's hass is not the card's real hass object");
  if (Object.hasOwn(container.child, "hass")) throw new Error("scenario A: hass is a shadowing own property, not delivered via the real accessor");
  if (hassSetterCalls === hassBefore) throw new Error("scenario A: the real hass accessor/setter was never actually invoked");
}

async function scenarioB_rerenderDuringInFlightCreateGraphs() {
  const el = makeCard(oneMetric());
  const previous = { __tag: GRAPH_CARD_TAG, __upgraded: true, _config: { entities: ["old"] }, hass: el._hass, connectedCallback(){}, disconnectedCallback(){} };
  el.graphs.set("weight", previous);
  el.render();
  const before = createCount;
  const p = el.createGraphs();
  await waitForCreateCount(before + 1);
  el.render();
  const containerDuringFlight = el.shadowRoot.querySelector("#graph-weight");
  if (containerDuringFlight.child !== previous) {
    throw new Error("scenario B: rerender while a new generation is in flight did not keep the previous, fully configured element");
  }
  registry.define(GRAPH_CARD_TAG, GraphCard);
  await p;
}

async function scenarioC_compactSwitchIsSafe() {
  const el = makeCard(oneMetric());
  el.config.display = "compact";
  await el.createGraphs();
  if (el.graphs.size !== 0) throw new Error("scenario C: compact mode must not create graph elements");
  el.config.display = "graphs";
  registry.define(GRAPH_CARD_TAG, GraphCard);
  await el.createGraphs();
  if (!el.graphs.get("weight")) throw new Error("scenario C: switching back to graphs mode must create the graph element");
}

async function scenarioD_periodSwitchIsSafe() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeCard(oneMetric());
  el.range = "7d";
  const p1 = el.createGraphs();
  el.range = "1m";
  const p2 = el.createGraphs();
  await Promise.all([p1, p2]);
  const container = el.shadowRoot.querySelector("#graph-weight");
  if (!container.child || container.child.hass === undefined) {
    throw new Error("scenario D: rapid period switching must still end with a single, fully configured graph attached");
  }
  if (el.graphs.get("weight") !== container.child) {
    throw new Error("scenario D: this.graphs and the DOM disagree on which generation won");
  }
}

async function scenarioE_editorPreviewReconfigureIsSafe() {
  registry.factories.delete(GRAPH_CARD_TAG);
  const el = makeCard(oneMetric());
  const before = createCount;
  const p1 = el.createGraphs();
  await waitForCreateCount(before + 1);
  // A build is already legitimately in flight (p1); setConfig() must only
  // reconfigure and bump the generation here, not also kick off a second,
  // real initialize() cycle on top of the manual createGraphs() calls this
  // scenario is specifically about - matching how set hass()'s own guard
  // already treats "loading" as "something is already in charge of this".
  el.loading = true;
  el.setConfig({ profile: "ander_profiel" });
  el.available = oneMetric();
  // Simulate metrics for the new profile already resolved, isolating this
  // scenario to the createGraphs() overlap itself rather than re-running a
  // full initialize()/findPrefix() cycle.
  el.ready = true;
  el.statisticPrefix = "fitage:ander_profiel";
  const p2 = el.createGraphs();
  await waitForCreateCount(before + 2);
  registry.define(GRAPH_CARD_TAG, GraphCard);
  await Promise.all([p1, p2]);
  const container = el.shadowRoot.querySelector("#graph-weight");
  if (!container.child || container.child.hass === undefined) {
    throw new Error("scenario E: editor reconfigure during an in-flight createGraphs() must still end configured");
  }
}

async function scenarioF_assigningHassBeforeUpgradeIsDemonstrablyLost() {
  // Proves this harness (and thus scenario A) actually discriminates
  // correct from incorrect code: deliberately reproduce the *old*,
  // pre-fix ordering (create -> set hass -> await whenDefined) using the
  // same low-level primitives production code uses, bypassing
  // createGraphs() itself, and confirm the assignment is provably lost -
  // exactly the mechanism behind "Cannot read properties of undefined
  // (reading 'config')" in a nested element that reads this.hass.config.
  registry.factories.delete(GRAPH_CARD_TAG);
  const el = document.createElement(GRAPH_CARD_TAG);
  const hassBefore = hassSetterCalls;
  const marker = { states: {} };
  el.hass = marker; // pre-upgrade: creates a shadowing own property
  if (!Object.hasOwn(el, "hass")) {
    throw new Error("scenario F: expected a shadowing own 'hass' property before upgrade");
  }
  registry.define(GRAPH_CARD_TAG, GraphCard); // lazy module "loads" now
  registry.upgrade(el);
  el.setConfig({ entities: ["sensor.time"] });
  if (Object.hasOwn(el, "hass")) {
    throw new Error("scenario F: the shadowing own property should be gone after upgrade");
  }
  if (el.hass !== undefined) {
    throw new Error("scenario F: expected the pre-upgrade value to be lost, not delivered");
  }
  if (hassSetterCalls !== hassBefore) {
    throw new Error("scenario F: the real accessor must not have been invoked by the pre-upgrade assignment");
  }
  // A nested header/footer-style element that reads this.hass.config, the
  // same way hui-graph-header-footer.ts's _subscribeHistory() does, must
  // reproduce the exact reported TypeError when handed this undefined hass.
  let threw = null;
  try {
    void el.hass.config;
  } catch (e) {
    threw = e;
  }
  if (!(threw instanceof TypeError)) {
    throw new Error("scenario F: reading .config off the lost hass value must throw the same TypeError Home Assistant does");
  }
}

async function scenarioG_setConfigWithoutHassBuildsNothing() {
  // Mirrors Home Assistant's card-picker/editor-preview flow, which can
  // call setConfig() on a freshly created card before it ever receives a
  // hass instance.
  const el = makeFreshCard();
  const createBefore = createCount;
  el.setConfig({ profile: "order_test_profiel" });
  await settle();
  if (el.initialized) throw new Error("scenario G: setConfig() without hass must not start initialize()");
  if (createCount !== createBefore) throw new Error("scenario G: setConfig() without hass must not create any graph element");
  const container = el.shadowRoot.querySelector("#graph-weight");
  if (container.child) throw new Error("scenario G: nothing may be attached to the DOM without hass");
}

async function scenarioH_hassArrivesAfterSetConfigBuildsExactlyOnce() {
  registry.define(GRAPH_CARD_TAG, GraphCard); // already loaded: isolates the setConfig/hass order from the separate lazy-load race covered by scenario A
  const el = makeFreshCard();
  el.setConfig({ profile: "order_test_profiel" });
  const createBefore = createCount;
  const hassBefore = hassSetterCalls;
  el.hass = fakeHass("order_test_profiel"); // setConfig already ran; hass arrives second
  await settle();
  const graph = el.graphs.get("weight");
  if (!graph) throw new Error("scenario H: expected exactly one graph to have been built once hass arrived");
  if (createCount !== createBefore + 1) throw new Error("scenario H: expected exactly one graph element created, got " + (createCount - createBefore));
  if (graph.hass !== el._hass) throw new Error("scenario H: graph.hass must be the card's real hass object");
  if (!graph.hass.config) throw new Error("scenario H: graph.hass.config must exist before connectedCallback could read it");
  if (hassSetterCalls === hassBefore) throw new Error("scenario H: the real hass accessor must have been invoked");
  const container = el.shadowRoot.querySelector("#graph-weight");
  if (container.child !== graph) throw new Error("scenario H: the built graph must actually be attached to the DOM");
}

async function scenarioI_multipleSetConfigBeforeHassOnlyBuildsTheLast() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  el.setConfig({ profile: "eerste_profiel" });
  el.setConfig({ profile: "order_test_profiel" }); // the editor changing a field again before hass ever arrived
  const createBefore = createCount;
  el.hass = fakeHass("order_test_profiel");
  await settle();
  if (createCount !== createBefore + 1) throw new Error("scenario I: only the latest config may ever be built, got " + (createCount - createBefore) + " graph element(s)");
  if (el.slug !== "order_test_profiel") throw new Error("scenario I: the card must have kept the latest config, not an earlier one");
}

async function scenarioJ_cardRemovedBeforeDeferredBuildIsNeverAttached() {
  registry.factories.delete(GRAPH_CARD_TAG); // first-time lazy load, so the build genuinely stays in flight
  const el = makeFreshCard();
  el.setConfig({ profile: "order_test_profiel" });
  el.hass = fakeHass("order_test_profiel"); // starts initialize() -> ... -> createGraphs(), still awaiting whenDefined()
  await Promise.resolve();
  el.isConnected = false; // the card has been removed from the dashboard
  registry.define(GRAPH_CARD_TAG, GraphCard); // the lazy module finishes loading only now, after removal
  await settle();
  const container = el.shadowRoot.querySelector("#graph-weight");
  if (container.child) throw new Error("scenario J: nothing may be attached once the card was removed before the deferred build finished");
}

async function scenarioL_createGraphsCalledDirectlyWithoutHassDefersAndLaterResumesOnce() {
  // Exercises createGraphs()'s own guard directly (e.g. a period button
  // click reaching selectRange() before the card is fully ready), not only
  // via the setConfig()/hass ordering scenarios above, and proves the
  // deferred build resumes exactly once - never twice - once hass arrives.
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  el.config = { title: "FITAGE", display: "graphs", profile: "order_test_profiel" };
  el.slug = "order_test_profiel";
  el.statisticPrefix = "fitage:order_test_profiel";
  el.available = oneMetric();
  el.ready = true;
  // A real initialize() cycle would already have set these by the time
  // anything could call createGraphs() directly (e.g. selectRange()); set
  // them up front so this scenario isolates createGraphs()'s own
  // defer/resume guard from the separate initialize()-triggering gate in
  // set hass(), already covered by scenarios G-K above.
  el.initialized = true;
  el.lastToken = el.updateToken();
  const createBefore = createCount;
  await el.createGraphs(); // this._hass is still undefined at this point
  if (createCount !== createBefore) throw new Error("scenario L: createGraphs() must not create any element while hass is missing");
  if (el.graphsPending !== true) throw new Error("scenario L: createGraphs() must mark a build as pending when it declines to run");
  const hassSetterCallsBefore = hassSetterCalls;
  el.hass = fakeHass("order_test_profiel");
  await settle();
  const graph = el.graphs.get("weight");
  if (!graph) throw new Error("scenario L: the deferred build must resume once hass arrives");
  if (createCount !== createBefore + 1) throw new Error("scenario L: exactly one graph must have been built, got " + (createCount - createBefore));
  if (hassSetterCalls === hassSetterCallsBefore) throw new Error("scenario L: the real hass accessor must have been invoked");
  if (el.graphsPending !== false) throw new Error("scenario L: the pending flag must be cleared once the build resumed");
  // A second, unrelated hass update (same token, nothing pending anymore)
  // must not start a second, duplicate build.
  const createAfterFirstResume = createCount;
  el.hass = fakeHass("order_test_profiel");
  await settle();
  if (createCount !== createAfterFirstResume) throw new Error("scenario L: a resumed build must never be started twice");
}

async function scenarioM1_singleStubPreviewCreatesNothing() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  const createBefore = createCount;
  el.setConfig(Card.getStubConfig());
  el.hass = fakeHass(STUB_PROFILE_VALUE);
  await settle();
  if (createCount !== createBefore) throw new Error("scenario M1: a stub preview must call createCardElement() zero times");
  if (el.graphs.size !== 0) throw new Error("scenario M1: a stub preview must attach zero graphs");
  if (el.hint !== "Kies een FITAGE-profiel in de kaarteditor.") throw new Error("scenario M1: the stub hint must be shown");
}

async function scenarioM2_twoSimultaneousStubPreviewsCreateNothing() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const elA = makeFreshCard();
  const elB = makeFreshCard();
  const createBefore = createCount;
  elA.setConfig(Card.getStubConfig());
  elB.setConfig(Card.getStubConfig());
  const hass = fakeHass(STUB_PROFILE_VALUE);
  elA.hass = hass;
  elB.hass = hass;
  await settle();
  if (createCount !== createBefore) throw new Error("scenario M2: two simultaneous stub previews must call createCardElement() zero times combined");
  if (elA.graphs.size !== 0 || elB.graphs.size !== 0) throw new Error("scenario M2: neither simultaneous stub preview may attach a graph");
}

async function scenarioM3_setConfigStubThenHass() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  const createBefore = createCount;
  el.setConfig({ profile: STUB_PROFILE_VALUE });
  el.hass = fakeHass(STUB_PROFILE_VALUE);
  await settle();
  if (createCount !== createBefore || el.graphs.size !== 0) throw new Error("scenario M3: setConfig(stub) -> hass must build nothing");
}

async function scenarioM4_hassThenSetConfigStub() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  const createBefore = createCount;
  el.hass = fakeHass(STUB_PROFILE_VALUE);
  el.setConfig({ profile: STUB_PROFILE_VALUE });
  await settle();
  if (createCount !== createBefore || el.graphs.size !== 0) throw new Error("scenario M4: hass -> setConfig(stub) must build nothing");
}

async function scenarioM5_multipleStubSetConfigCallsBuildNothing() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  const createBefore = createCount;
  el.setConfig({ profile: STUB_PROFILE_VALUE });
  el.setConfig({ profile: STUB_PROFILE_VALUE, title: "Nog een keer" });
  el.setConfig({ profile: STUB_PROFILE_VALUE, text_size: "large" });
  el.hass = fakeHass(STUB_PROFILE_VALUE);
  await settle();
  if (createCount !== createBefore || el.graphs.size !== 0) throw new Error("scenario M5: repeated stub setConfig() calls must build nothing");
}

async function scenarioM6_stubWithDisplayGraphsBuildsNothingButKeepsDisplaySelection() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  const createBefore = createCount;
  el.setConfig({ profile: STUB_PROFILE_VALUE, display: "graphs" });
  el.hass = fakeHass(STUB_PROFILE_VALUE);
  await settle();
  if (createCount !== createBefore || el.graphs.size !== 0) throw new Error("scenario M6: stub with display: graphs must still build nothing");
  if (el.config.display !== "graphs") throw new Error("scenario M6: the editor's display: graphs selection must not be changed to compact");
}

async function scenarioM7_validProfileSwitchedToStubMidPrefixResolutionBuildsNothing() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  let releaseGate;
  const gate = new Promise((resolve) => { releaseGate = resolve; });
  el.setConfig({ profile: "order_test_profiel" });
  const createBefore = createCount;
  el.hass = fakeHassGated("order_test_profiel", gate); // initialize() now blocked inside listStatistics()
  await Promise.resolve();
  el.setConfig({ profile: STUB_PROFILE_VALUE }); // switched to the stub while the old resolution is still in flight
  releaseGate(); // let the *stale* initialize() run continue and see it has been superseded
  await settle();
  if (createCount !== createBefore) throw new Error("scenario M7: a switch to the stub profile during prefix resolution must still build nothing");
  if (el.graphs.size !== 0) throw new Error("scenario M7: no graph may end up attached after switching to the stub mid-resolution");
  if (el.hint !== "Kies een FITAGE-profiel in de kaarteditor.") throw new Error("scenario M7: the stub hint must win");
}

async function scenarioM8_stubLaterSwitchedToValidProfileBuildsOnlyAfterward() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  el.setConfig({ profile: STUB_PROFILE_VALUE });
  el.hass = fakeHass("order_test_profiel");
  await settle();
  const createBeforeSwitch = createCount;
  if (el.graphs.size !== 0) throw new Error("scenario M8: still on the stub, nothing may be built yet");
  el.setConfig({ profile: "order_test_profiel" });
  el.hass = fakeHass("order_test_profiel");
  await settle();
  if (el.graphs.size !== 1) throw new Error("scenario M8: switching to a valid profile must build its graph");
  if (createCount === createBeforeSwitch) throw new Error("scenario M8: createCardElement() must actually have run after switching away from the stub");
}

async function scenarioM9_validProfileWithCurrentPrefixKeepsWorking() {
  registry.define(GRAPH_CARD_TAG, GraphCard);
  const el = makeFreshCard();
  el.setConfig({ profile: "order_test_profiel" });
  el.hass = fakeHass("order_test_profiel");
  await settle();
  if (el.graphs.size !== 1) throw new Error("scenario M9: a valid profile with a resolvable prefix must still build its graph normally");
  if (el.error) throw new Error("scenario M9: a valid profile must not show an error: " + el.error);
  if (!el.ready) throw new Error("scenario M9: a valid profile must reach the ready state");
}

async function scenarioK_theOldOrderReproducesTheSameCrash() {
  // Demonstrates the exact failure this fix closes: the *old* invariant
  // (graph.hass !== this._hass) does not reject two undefined values, so a
  // graph built while hass is genuinely missing slips through and a nested
  // element reading .hass.config crashes exactly like hui-graph-header-footer.
  const graph = {};
  const cardHass = undefined; // this._hass, as it would be if createGraphs() ran without the new guard
  graph.hass = cardHass;
  const oldInvariantWouldReject = graph.hass !== cardHass;
  if (oldInvariantWouldReject) {
    throw new Error("scenario K: the old equality-only invariant was expected to (wrongly) accept this");
  }
  let threw = null;
  try {
    void graph.hass.config;
  } catch (e) {
    threw = e;
  }
  if (!(threw instanceof TypeError)) {
    throw new Error("scenario K: reading .config off a graph with no real hass must throw the same TypeError Home Assistant does");
  }
}

(async () => {
  await scenarioA_setConfigBeforeAttach();
  await scenarioF_assigningHassBeforeUpgradeIsDemonstrablyLost();
  await scenarioB_rerenderDuringInFlightCreateGraphs();
  await scenarioC_compactSwitchIsSafe();
  await scenarioD_periodSwitchIsSafe();
  await scenarioE_editorPreviewReconfigureIsSafe();
  await scenarioG_setConfigWithoutHassBuildsNothing();
  await scenarioH_hassArrivesAfterSetConfigBuildsExactlyOnce();
  await scenarioI_multipleSetConfigBeforeHassOnlyBuildsTheLast();
  await scenarioJ_cardRemovedBeforeDeferredBuildIsNeverAttached();
  await scenarioL_createGraphsCalledDirectlyWithoutHassDefersAndLaterResumesOnce();
  await scenarioM1_singleStubPreviewCreatesNothing();
  await scenarioM2_twoSimultaneousStubPreviewsCreateNothing();
  await scenarioM3_setConfigStubThenHass();
  await scenarioM4_hassThenSetConfigStub();
  await scenarioM5_multipleStubSetConfigCallsBuildNothing();
  await scenarioM6_stubWithDisplayGraphsBuildsNothingButKeepsDisplaySelection();
  await scenarioM7_validProfileSwitchedToStubMidPrefixResolutionBuildsNothing();
  await scenarioM8_stubLaterSwitchedToValidProfileBuildsOnlyAfterward();
  await scenarioM9_validProfileWithCurrentPrefixKeepsWorking();
  await scenarioK_theOldOrderReproducesTheSameCrash();
  if (violations.length) {
    console.error(violations.join("\n"));
    process.exit(1);
  }
  console.log("ALL LIFECYCLE CHECKS PASSED");
})().catch((e) => { console.error(e.stack || e); process.exit(1); });
"""


def run_async(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapped


def fake_hass() -> SimpleNamespace:
    http = SimpleNamespace(async_register_static_paths=AsyncMock())
    config = SimpleNamespace(config_dir="/tmp")
    return SimpleNamespace(data={}, http=http, config=config)


def storage_lovelace_data(items: dict[str, dict] | None = None):
    """Build a real (non-mocked) storage-mode LovelaceData/ResourceStorageCollection
    pair, pre-loaded with `items` so tests exercise Home Assistant's own
    resource collection class instead of a hand-rolled stand-in.

    Store I/O is bypassed by setting `loaded = True` and seeding `.data`
    directly, matching how tests avoid real disk access elsewhere; callers
    still need to patch Store.async_delay_save since async_create_item/
    async_update_item schedule one.
    """
    from homeassistant.components.lovelace import LovelaceData
    from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE
    from homeassistant.components.lovelace.resources import ResourceStorageCollection

    hass = fake_hass()
    resources = ResourceStorageCollection(hass, None)
    resources.loaded = True
    resources.data = dict(items or {})
    hass.data[LOVELACE_DATA] = LovelaceData(
        resource_mode=MODE_STORAGE,
        dashboards={},
        resources=resources,
        yaml_dashboards={},
    )
    return hass, resources


def test_bundled_card_ships_in_the_expected_distribution_location() -> None:
    assert CARD_PATH.is_file()


def test_bundled_card_is_version_0_5_1() -> None:
    assert CARD_PATH.read_text(encoding="utf-8").startswith('const VERSION = "0.5.1";')


def test_card_version_constant_matches_the_javascript_version() -> None:
    """custom_components/fitage/frontend.py hardcodes CARD_VERSION instead of
    reading it from the JS file at runtime (that would be a blocking file
    read during async_setup). This test is the only place allowed to read
    the file to keep the two in sync."""
    content = CARD_PATH.read_text(encoding="utf-8")
    match = _JS_VERSION_RE.search(content[:200])
    assert match is not None
    assert CARD_VERSION == match.group(1)


def test_bundled_card_registers_card_and_editor_elements() -> None:
    content = CARD_PATH.read_text(encoding="utf-8")
    assert 'customElements.define("fitage-card"' in content
    assert 'customElements.define("fitage-card-editor"' in content


def test_bundled_card_element_registration_is_idempotent() -> None:
    """Guards the frontend JS's own double-registration guards, which stay
    unchanged: the card must survive being imported more than once (e.g. a
    stale extra_js_url still importing it alongside the new Lovelace
    resource) without throwing on a duplicate customElements.define."""
    content = CARD_PATH.read_text(encoding="utf-8")
    assert 'if(!customElements.get("fitage-card"))customElements.define(' in content
    assert (
        'if(!customElements.get("fitage-card-editor"))customElements.define(' in content
    )
    assert 'window.customCards.some(c=>c.type==="fitage-card")' in content


def test_static_url_path_matches_the_bundled_card() -> None:
    assert STATIC_URL_PATH == "/fitage/fitage-card.js"


def test_module_url_is_exactly_the_expected_value() -> None:
    assert MODULE_URL == "/fitage/fitage-card.js?v=0.5.1"


def test_default_stub_profile_shows_a_neutral_instruction_in_source() -> None:
    """Static guard (always runs, no Node.js needed): the default stub
    preview (getStubConfig()'s profile: "jouw_profiel") must show a neutral
    instruction instead of the red "kon niet betrouwbaar worden gekoppeld"
    error, while a genuinely filled-in but invalid profile must still raise
    that error - see test_default_stub_profile_shows_hint_not_a_red_error
    for the real-Node.js behavioral proof of this distinction."""
    content = CARD_PATH.read_text(encoding="utf-8")
    assert 'const STUB_PROFILE = "jouw_profiel";' in content
    assert "getStubConfig() { return { profile: STUB_PROFILE }; }" in content
    assert "this.config.profile === STUB_PROFILE" in content
    assert 'this.hint = "Kies een FITAGE-profiel in de kaarteditor."' in content
    assert (
        'throw Error("Het juiste FITAGE-profiel kon niet betrouwbaar worden gekoppeld.")'
        in content
    )
    assert (
        'throw Error("Voor dit profiel zijn geen FITAGE-statistieken gevonden.")'
        in content
    )


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_default_stub_profile_shows_hint_not_a_red_error() -> None:
    """Real-Node.js behavioral proof: load the actual bundled card under a
    minimal customElements/HTMLElement stub and drive setConfig()/hass the
    same way Home Assistant's card picker preview does."""
    result = _run_node_js(_STUB_HINT_JS_HARNESS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL JS BEHAVIOR CHECKS PASSED" in result.stdout


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_graph_element_is_never_connected_to_the_dom_before_it_is_configured() -> None:
    """Regression test for "TypeError: Cannot read properties of undefined
    (reading 'config')" at hui-graph-header-footer.ts:163, in
    _subscribeHistory(), called from connectedCallback(). Drives the real
    createGraphs()/render() through a faithful simulation of Home
    Assistant's own createCardElement() lazy-loading race (see the harness
    docstring above for the exact Core-adjacent source reference) and checks
    five scenarios: setConfig() before DOM attachment, a rerender while a
    new generation is still loading, switching between graphs and compact,
    rapid period switching, and an editor-preview reconfigure mid-flight."""
    result = _run_node_js(_GRAPH_LIFECYCLE_JS_HARNESS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL LIFECYCLE CHECKS PASSED" in result.stdout


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_find_prefix_selects_the_real_weight_metric_deterministically() -> None:
    """findPrefix() must never mistake a statistic ID ending in
    "_fat_free_weight" for the "weight" metric just because it also ends in
    "_weight" as a substring, must prefer the display name FITAGE's own
    statistics.py writes into statistic metadata over any value comparison,
    and must refuse to guess - returning null - whenever two candidates are
    equally plausible, whether by colliding display name or by value."""
    result = _run_node_js(_FIND_PREFIX_JS_HARNESS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL FIND-PREFIX CHECKS PASSED" in result.stdout


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_two_decimal_precision_group() -> None:
    """weight, bone, fat_free_weight, body_fat_mass, body_water_mass and
    protein_mass show at most 2 decimals, with unnecessary trailing zeros
    dropped (minimumFractionDigits: 0)."""
    cases = [
        [94.75, "kg", "weight", "94,75 kg"],
        [25.00, "kg", "weight", "25 kg"],
        [67.10, "kg", "bone", "67,1 kg"],
        [1.005, "kg", "fat_free_weight", "1,01 kg"],
        [12.345, "kg", "body_fat_mass", "12,35 kg"],
        [0, "kg", "body_water_mass", "0 kg"],
        [3.5, "kg", "protein_mass", "3,5 kg"],
    ]
    result = _run_node_js(_FORMAT_JS_HARNESS.replace("CASES", json.dumps(cases)))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL FORMAT CHECKS PASSED" in result.stdout


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_one_decimal_precision_group() -> None:
    """bmi, bodyfat, water, muscle, protein, subfat and score show at most 1
    decimal, with unnecessary trailing zeros dropped."""
    cases = [
        [67.10, "", "bmi", "67,1"],
        [25.00, "%", "bodyfat", "25 %"],
        [50.5, "%", "water", "50,5 %"],
        [33.33, "%", "muscle", "33,3 %"],
        [18.0, "%", "protein", "18 %"],
        [12.34, "%", "subfat", "12,3 %"],
        [8.5, "", "score", "8,5"],
    ]
    result = _run_node_js(_FORMAT_JS_HARNESS.replace("CASES", json.dumps(cases)))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL FORMAT CHECKS PASSED" in result.stdout


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_zero_decimal_precision_group_and_dutch_thousands_separator() -> None:
    """bmr shows 0 decimals, and Dutch locale groups thousands with a dot."""
    cases = [
        [1818.0, "kcal", "bmr", "1.818 kcal"],
        [999, "kcal", "bmr", "999 kcal"],
        [1818.6, "kcal", "bmr", "1.819 kcal"],
    ]
    result = _run_node_js(_FORMAT_JS_HARNESS.replace("CASES", json.dumps(cases)))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL FORMAT CHECKS PASSED" in result.stdout


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_negative_and_missing_values_are_formatted_correctly() -> None:
    cases = [
        [-5.5, "kg", "weight", "-5,5 kg"],
        [-1818.0, "kcal", "bmr", "-1.818 kcal"],
        ["not-a-number", "kg", "weight", "—"],
    ]
    result = _run_node_js(_FORMAT_JS_HARNESS.replace("CASES", json.dumps(cases)))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL FORMAT CHECKS PASSED" in result.stdout


@pytest.mark.skipif(NODE_BIN is None, reason="no local Node.js runtime available")
def test_missing_and_falsy_edge_cases_never_show_as_a_real_zero() -> None:
    """Number(null), Number(""), Number("   ") and Number(false) all equal 0
    in JavaScript, and Number(true) equals 1 - none of these represent an
    actual measurement. format() must special-case them to the placeholder
    dash before ever calling Number(...), while a genuine numeric (or
    numeric-string) zero must still render as "0", not be swallowed."""
    harness = (
        _LOAD_CARD_JS_PRELUDE
        + r"""
const cases = [
  [undefined, "—"],
  [null, "—"],
  ["", "—"],
  ["   ", "—"],
  [true, "—"],
  [false, "—"],
  [0, "0"],
  ["0", "0"],
];
const failures = [];
for (const [value, expected] of cases) {
  const actual = Card.prototype.format(value, "", "weight");
  if (actual !== expected) {
    failures.push(`format(${JSON.stringify(value)}) = ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`);
  }
}
if (failures.length) { console.error(failures.join("\n")); process.exit(1); }
console.log("ALL FORMAT CHECKS PASSED");
"""
    )
    result = _run_node_js(harness)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL FORMAT CHECKS PASSED" in result.stdout


def test_frontend_module_does_not_import_add_extra_js_url() -> None:
    """The Lovelace resource is now the one and only automatic loading
    route; add_extra_js_url must not also be used for the same card, or the
    browser would download fitage-card.js twice."""
    import custom_components.fitage.frontend as frontend_module

    assert not hasattr(frontend_module, "add_extra_js_url")


def test_production_code_never_reads_the_card_file_for_its_version() -> None:
    """CARD_VERSION must be a plain constant, not something derived from
    reading www/fitage-card.js at setup time - Path.read_text/Path.open are
    blocking calls Home Assistant's block_async_io flags when awaited from
    the event loop (custom_components/fitage/frontend.py used to call
    card_path.read_text() directly inside async_register_frontend)."""
    import inspect

    import custom_components.fitage.frontend as frontend_module

    source = inspect.getsource(frontend_module)
    assert "read_text(" not in source
    assert "read_bytes(" not in source
    assert ".open(" not in source
    assert re.search(r"(?<!\.)\bopen\(", source) is None


@run_async
async def test_static_path_registered_once_with_the_bundled_card() -> None:
    hass, _resources = storage_lovelace_data()
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        await async_register_frontend(hass)
    hass.http.async_register_static_paths.assert_awaited_once()
    (configs,), _ = hass.http.async_register_static_paths.call_args
    assert len(configs) == 1
    assert configs[0].url_path == STATIC_URL_PATH
    assert configs[0].path == str(CARD_PATH)


@run_async
async def test_no_existing_resource_creates_exactly_one_module_resource() -> None:
    hass, resources = storage_lovelace_data()
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        await async_register_frontend(hass)
    items = resources.async_items()
    assert len(items) == 1
    assert items[0]["url"] == MODULE_URL
    assert items[0]["type"] == "module"


@run_async
async def test_exact_resource_already_present_is_left_untouched() -> None:
    hass, resources = storage_lovelace_data(
        {"fitage-id": {"id": "fitage-id", "type": "module", "url": MODULE_URL}}
    )
    with patch("homeassistant.helpers.storage.Store.async_delay_save") as delay_save:
        await async_register_frontend(hass)
    delay_save.assert_not_called()
    assert resources.async_items() == [
        {"id": "fitage-id", "type": "module", "url": MODULE_URL}
    ]


@run_async
async def test_older_integrated_version_is_updated_in_place() -> None:
    hass, resources = storage_lovelace_data(
        {
            "fitage-id": {
                "id": "fitage-id",
                "type": "module",
                "url": "/fitage/fitage-card.js?v=0.4.0",
            }
        }
    )
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        await async_register_frontend(hass)
    items = resources.async_items()
    assert len(items) == 1
    assert items[0]["id"] == "fitage-id"
    assert items[0]["url"] == MODULE_URL


@run_async
async def test_resource_updates_from_v0_5_0_to_v0_5_1() -> None:
    """The real-world upgrade this release ships: the previously-registered
    v0.5.0 Lovelace resource must update in place to v0.5.1, not duplicate."""
    hass, resources = storage_lovelace_data(
        {
            "fitage-id": {
                "id": "fitage-id",
                "type": "module",
                "url": "/fitage/fitage-card.js?v=0.5.0",
            }
        }
    )
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        await async_register_frontend(hass)
    items = resources.async_items()
    assert len(items) == 1
    assert items[0]["id"] == "fitage-id"
    assert items[0]["url"] == "/fitage/fitage-card.js?v=0.5.1"
    assert items[0]["url"] == MODULE_URL


@run_async
async def test_old_manual_prototype_resource_is_never_modified() -> None:
    hass, resources = storage_lovelace_data(
        {
            "legacy-id": {
                "id": "legacy-id",
                "type": "module",
                "url": f"{LEGACY_PROTOTYPE_URL_PATH}?v=0.4.0",
            }
        }
    )
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        await async_register_frontend(hass)
    items = {item["id"]: item for item in resources.async_items()}
    assert items["legacy-id"]["url"] == f"{LEGACY_PROTOTYPE_URL_PATH}?v=0.4.0"
    assert any(item["url"] == MODULE_URL for item in items.values())


@run_async
async def test_old_manual_prototype_resource_logs_a_clear_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hass, _resources = storage_lovelace_data(
        {
            "legacy-id": {
                "id": "legacy-id",
                "type": "module",
                "url": f"{LEGACY_PROTOTYPE_URL_PATH}?v=0.4.0",
            }
        }
    )
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        await async_register_frontend(hass)
    assert LEGACY_PROTOTYPE_URL_PATH in caplog.text
    assert "remove" in caplog.text.lower()


@run_async
async def test_unrelated_resources_are_never_touched() -> None:
    hass, resources = storage_lovelace_data(
        {
            "other-id": {
                "id": "other-id",
                "type": "js",
                "url": "/local/some-other-card.js?v=1",
            }
        }
    )
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        await async_register_frontend(hass)
    items = {item["id"]: item for item in resources.async_items()}
    assert items["other-id"] == {
        "id": "other-id",
        "type": "js",
        "url": "/local/some-other-card.js?v=1",
    }
    assert len(items) == 2


@run_async
async def test_multiple_config_entries_do_not_cause_double_registration() -> None:
    """Simulates two FITAGE config entries both triggering setup on one hass."""
    hass, resources = storage_lovelace_data()
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        await async_setup(hass, {})
        await async_setup(hass, {})
    assert len(resources.async_items()) == 1
    hass.http.async_register_static_paths.assert_awaited_once()


@run_async
async def test_config_entry_reload_does_not_cause_double_registration() -> None:
    hass, resources = storage_lovelace_data()
    with patch("homeassistant.helpers.storage.Store.async_delay_save"):
        await async_register_frontend(hass)
        # A reload only re-runs async_setup_entry, never the domain async_setup,
        # but registration must stay idempotent even if it were invoked again.
        await async_register_frontend(hass)
    assert len(resources.async_items()) == 1


@run_async
async def test_yaml_resource_mode_is_handled_safely_without_touching_files(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from homeassistant.components.lovelace import LovelaceData
    from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_YAML
    from homeassistant.components.lovelace.resources import ResourceYAMLCollection

    hass = fake_hass()
    hass.data[LOVELACE_DATA] = LovelaceData(
        resource_mode=MODE_YAML,
        dashboards={},
        resources=ResourceYAMLCollection([]),
        yaml_dashboards={},
    )
    with patch("homeassistant.helpers.storage.Store") as store:
        result = await async_setup(hass, {})
    assert result is True
    store.assert_not_called()
    assert "yaml" in caplog.text.lower()
    assert MODULE_URL in caplog.text


@run_async
async def test_lovelace_not_set_up_does_not_fail_integration_setup() -> None:
    hass = fake_hass()
    result = await async_setup(hass, {})
    assert result is True


@run_async
async def test_resource_registration_failure_does_not_fail_integration_setup(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hass = fake_hass()
    with patch(
        "custom_components.fitage.frontend._async_register_lovelace_resource",
        side_effect=RuntimeError("boom"),
    ):
        result = await async_setup(hass, {})
    assert result is True
    assert "error" in caplog.text.lower() or "not" in caplog.text.lower()
    hass.http.async_register_static_paths.assert_awaited_once()


@run_async
async def test_missing_card_file_logs_a_warning_and_does_not_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hass = fake_hass()
    missing = Path("/nonexistent/fitage-card.js")
    with patch("custom_components.fitage.frontend._card_path", return_value=missing):
        await async_register_frontend(hass)
    assert "not found" in caplog.text
    hass.http.async_register_static_paths.assert_not_awaited()


@run_async
async def test_missing_card_file_does_not_fail_integration_setup() -> None:
    hass = fake_hass()
    missing = Path("/nonexistent/fitage-card.js")
    with patch("custom_components.fitage.frontend._card_path", return_value=missing):
        result = await async_setup(hass, {})
    assert result is True


@run_async
async def test_async_setup_registers_the_frontend_card() -> None:
    hass = fake_hass()
    with patch("custom_components.fitage.async_register_frontend") as register:
        register.return_value = None
        result = await async_setup(hass, {})
    register.assert_called_once_with(hass)
    assert result is True


@run_async
async def test_registration_never_writes_to_storage_directly() -> None:
    """No .storage file is ever read or written by our own code; only the
    already-loaded Home Assistant collection object is used."""
    hass, _resources = storage_lovelace_data()
    with patch("homeassistant.helpers.storage.Store") as store:
        await async_register_frontend(hass)
    store.assert_not_called()
