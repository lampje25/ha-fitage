const VERSION = "0.5.1";
const STUB_PROFILE = "jouw_profiel";
const METRICS = [
  ["weight", "Gewicht", "weight", "kg"], ["bmi", "BMI", "bmi", ""],
  ["bodyfat", "Lichaamsvet", "bodyfat", "%"], ["water", "Lichaamswater", "hydration", "%"],
  ["muscle", "Spierverhouding", "muscle_ratio", "%"], ["protein", "Eiwit", "protein", "%"],
  ["bone", "Botmassa", ["bone", "bone_mass"], "kg"], ["subfat", "Onderhuids vet", ["subfat", "subcutaneous_fat"], "%"],
  ["fat_free_weight", "Vetvrij gewicht", null, "kg"], ["body_fat_mass", "Vetmassa", null, "kg"],
  ["body_water_mass", "Watermassa", null, "kg"], ["protein_mass", "Eiwitmassa", null, "kg"],
  ["bmr", "Basaal metabolisme", "bmr", "kcal"], ["score", "Gezondheidsscore", null, ""],
].map(([key, title, entity, unit]) => ({ key, title, entity, unit }));
// Longest-key-first so a statistic ID ending in "..._fat_free_weight" is
// matched against the "fat_free_weight" metric key, never mistaken for
// "weight" on account of also ending in "_weight" as a substring.
const METRIC_KEYS_BY_LENGTH = METRICS.map(m => m.key).sort((a, b) => b.length - a.length);
// Maximum decimals shown per metric; trailing zeros within that maximum are
// still dropped because format() always uses minimumFractionDigits: 0.
const PRECISION = {
  weight: 2, bone: 2, fat_free_weight: 2, body_fat_mass: 2, body_water_mass: 2, protein_mass: 2,
  bmi: 1, bodyfat: 1, water: 1, muscle: 1, protein: 1, subfat: 1, score: 1,
  bmr: 0,
};
// The Home Assistant lovelace card type embedded per metric. "statistics-graph"
// is one of Home Assistant's LAZY_LOAD_TYPES (create-element/create-element-base.ts):
// createCardElement() always routes it through _lazyCreate(tag, config), which
// has two branches:
//   - customElements.get(tag) is falsy (not loaded yet this session): returns
//     a plain, un-upgraded element synchronously and only calls
//     customElements.upgrade(element) + element.setConfig(config) later, in a
//     .then() on customElements.whenDefined(tag).
//   - customElements.get(tag) is already truthy: returns
//     document.createElement(tag) - which the browser upgrades immediately,
//     since the definition already exists - and calls element.setConfig(config)
//     synchronously, right away.
// Setting a property (e.g. .hass) on the plain, not-yet-upgraded element from
// the first branch creates an own data property on the instance. Verified
// against the real, locally installed home-assistant-frontend in an actual
// Chromium build: once the class is later applied, that own property is
// *not* correctly replayed through the real accessor - the assigned value is
// silently lost and the property reads back as undefined afterwards.
// createGraphs() below therefore always calls createCardElement() first (so
// the very first use this session actually triggers the lazy import -
// awaiting whenDefined() before ever calling createCardElement would just
// hang forever, since nothing would ever load the module), but never sets
// any property - not even .hass - until after customElements.whenDefined(
// GRAPH_CARD_TAG) has resolved, by which point Home Assistant's own
// upgrade()+setConfig() .then() (registered on that exact promise the
// moment createCardElement() ran) has already applied the real class, so
// every property we set from then on is guaranteed to go through its real
// accessor.
const GRAPH_CARD_TYPE = "statistics-graph";
const GRAPH_CARD_TAG = `hui-${GRAPH_CARD_TYPE}-card`;

class FitageCard extends HTMLElement {
  constructor() {
    super(); this.attachShadow({ mode: "open" }); this.range = "1m";
    this.graphs = new Map(); this.latest = new Map(); this.graphGeneration = 0;
  }
  static getConfigElement() { return document.createElement("fitage-card-editor"); }
  static getStubConfig() { return { profile: STUB_PROFILE }; }
  setConfig(config) {
    if (!config?.profile) throw Error("Geef een FITAGE-profiel op, bijvoorbeeld: profile: jouw_profiel");
    this.config = { title: "FITAGE", display: "graphs", ...config }; this.slug = this.toSlug(config.profile);
    this.statisticPrefix = config.statistic_prefix; this.ready = false; this.error = null; this.hint = null;
    this.initialized = false; this.graphGeneration++; this.graphs.clear(); this.latest.clear();
    this.graphsPending = false;
    if (this.config.profile === STUB_PROFILE) {
      // The default stub/preview config must never resolve a statistic
      // prefix or build a graph - not even by accident. findPrefix() below
      // can otherwise match a *real* profile for this placeholder, either
      // through its single-weight-statistic shortcut or its weight-value
      // proximity heuristic, on an account whose real entities happen to
      // line up - entirely independent of the hass/lazy-load timing this
      // class already guards against. Deciding this here needs no hass at
      // all, no network call, and leaves display: graphs selected in the
      // editor as-is; only the graph *execution* is blocked.
      this.hint = "Kies een FITAGE-profiel in de kaarteditor.";
      this.initialized = true; // nothing left to resolve for this profile
      this.render();
      return;
    }
    this.render();
    // this._hass can still be missing here: Home Assistant's card-picker
    // and editor-preview flows may call setConfig() before hass is ever
    // assigned to a freshly created card. Only start building once both a
    // config *and* a valid hass are known - see set hass() below, the other
    // half of this two-sided gate, for whichever of the two arrives last.
    if (this._hass?.config && !this.initialized && !this.loading) this.initialize();
  }
  set hass(hass) {
    this._hass = hass; const token = this.updateToken(); const changed = token !== this.lastToken;
    // this.graphs only ever holds fully built, already-upgraded graph
    // elements (see createGraphs()), so handing them the new hass directly
    // is always safe and keeps them current even when no tracked metric's
    // last_updated changed (the only trigger for the full refreshMeasurements()
    // rebuild below).
    this.graphs.forEach(g => { g.hass = hass; });
    if (!this.rendered) { this.render(); this.rendered = true; }
    else if (changed && this.ready) this.refreshMeasurements();
    this.lastToken = token;
    if (this.config && this.config.profile !== STUB_PROFILE && this._hass?.config && !this.initialized && !this.loading) {
      this.initialize();
    } else if (this.graphsPending && this.canCreateGraphs(this.graphGeneration)) {
      // Exactly one deferred build resumes here, the first time this card
      // is actually allowed to build one (see canCreateGraphs()); a stub
      // profile can never leave graphsPending true in the first place (see
      // createGraphs() below), but the check is repeated here regardless -
      // this must remain true from every single angle, not just the one
      // that happens to set the flag today.
      this.graphsPending = false; this.createGraphs();
    }
  }
  // The single, synchronous source of truth for whether a statistics-graph
  // sub-card may be created and attached right now. Consulted before every
  // route that can reach createGraphs()/createCardElement()/DOM attachment
  // - the initial call in createGraphs(), the re-checks after each await in
  // it, and the graphsPending resume in set hass() above - so there is
  // exactly one place that can ever say yes.
  canCreateGraphs(generation) {
    return !!(
      this.config &&
      this.config.profile &&
      this.config.profile !== STUB_PROFILE &&
      this._hass?.config &&
      this.config.display !== "compact" &&
      this.ready &&
      this.statisticPrefix &&
      this.isConnected &&
      generation === this.graphGeneration
    );
  }
  getCardSize() { return this.config?.display === "compact" ? Math.max(2, Math.ceil((this.available?.length || 1) / 2)) : Math.max(6, (this.available?.length || 1) * 5); }
  toSlug(v) { return String(v).trim().toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, ""); }
  entityId(m) {
    if(!m?.entity)return null;
    const suffixes=Array.isArray(m.entity)?m.entity:[m.entity];
    return suffixes.map(suffix=>`sensor.${this.slug}_${suffix}`).find(id=>this._hass?.states?.[id]) || `sensor.${this.slug}_${suffixes[0]}`;
  }
  weightEntityId() { return this.config.entity || `sensor.${this.slug}_weight`; }
  statisticId(m) { return `${this.statisticPrefix}_${m.key}`; }
  updateToken() { return METRICS.map(m => this._hass?.states?.[this.entityId(m)]?.last_updated || "").join("|"); }

  async initialize() {
    const generation = this.graphGeneration;
    this.loading = true; this.initialized = true;
    try {
      const metadata = await this.listStatistics();
      // A newer setConfig() (e.g. switching to the stub profile, or to a
      // different real one) may have run while this awaited; never let a
      // superseded run keep going, including into the stub's own hint path.
      if (generation !== this.graphGeneration) return;
      this.ids = new Set(metadata.map(x => x.statistic_id || x.id).filter(Boolean));
      if (!this.statisticPrefix) this.statisticPrefix = await this.findPrefix([...this.ids], metadata);
      if (generation !== this.graphGeneration) return;
      if (!this.statisticPrefix) {
        if (this.config.profile === STUB_PROFILE) { this.hint = "Kies een FITAGE-profiel in de kaarteditor."; this.render(); return; }
        throw Error("Het juiste FITAGE-profiel kon niet betrouwbaar worden gekoppeld.");
      }
      const discovered = METRICS.filter(m => this.ids.has(this.statisticId(m)));
      if (!discovered.length) throw Error("Voor dit profiel zijn geen FITAGE-statistieken gevonden.");
      const selected = Array.isArray(this.config.metrics) ? new Set(this.config.metrics) : null;
      this.available = selected ? discovered.filter(m => selected.has(m.key)) : discovered;
      await this.loadLatest();
      if (generation !== this.graphGeneration) return;
      this.ready = true; this.render();
      if(this.config.display !== "compact")await this.createGraphs();
    } catch (e) { this.error = e.message || String(e); this.render(); }
    finally { this.loading = false; }
  }
  async listStatistics() {
    const r = await this._hass.callWS({ type: "recorder/list_statistic_ids" });
    return Array.isArray(r) ? r : Object.entries(r || {}).map(([statistic_id, v]) => ({ statistic_id, ...(v || {}) }));
  }
  // The metric key a statistic ID actually ends in, picking the longest
  // matching METRICS key first - never a coincidental substring match (e.g.
  // "..._fat_free_weight" must resolve to "fat_free_weight", not "weight").
  metricKeyForStatisticId(id) {
    return METRIC_KEYS_BY_LENGTH.find(key => id.endsWith(`_${key}`)) || null;
  }
  // custom_components/fitage/statistics.py's FitageStatisticsImporter._metadata()
  // names every statistic "FITAGE <account name or nickname> – <metric>" -
  // presentation metadata our own backend writes and controls (not a Home
  // Assistant internal), safe to parse back out here. Collisions between two
  // profiles sharing the same display name get a "(<hex>)" suffix appended
  // there (see configure_profile_names); stripped here since a collision
  // still leaves both candidates equally, ambiguously named once removed -
  // see the caller, which rejects rather than guesses in that case.
  profileFromStatisticName(name) {
    const match = /^FITAGE (.+) – Weight$/.exec(String(name ?? ""));
    if (!match) return null;
    return match[1].replace(/\s*\([0-9a-f]{4,}\)$/i, "").trim();
  }
  async findPrefix(ids, metadata) {
    const weights = ids.filter(id => String(id).startsWith("fitage:") && this.metricKeyForStatisticId(String(id)) === "weight");
    if (!weights.length) return null;
    const metaById = new Map((metadata || []).map(x => [x.statistic_id || x.id, x]));
    // Deterministic first: match this card's profile against the display
    // name our own backend recorded for the statistic, not a value guess.
    const named = weights.filter(id => this.toSlug(this.profileFromStatisticName(metaById.get(id)?.name) || "") === this.slug);
    if (named.length === 1) return named[0].slice(0, -"_weight".length);
    if (named.length > 1) return null; // two profiles named alike: do not guess
    if (weights.length === 1) return weights[0].slice(0, -"_weight".length);
    const current = Number(this._hass.states?.[this.weightEntityId()]?.state);
    if (!Number.isFinite(current)) return null;
    const data = await this.statistics(weights, 400);
    const ranked = weights.map(id => {
      const row = [...(data[id] || [])].reverse().find(x => Number.isFinite(Number(x.state)));
      return row ? { id, d: Math.abs(Number(row.state) - current) } : null;
    }).filter(Boolean).sort((a,b) => a.d-b.d);
    // Exactly one candidate close enough to the live reading counts as a
    // match; two or more equally plausible candidates must never be guessed
    // between - that is exactly the multi-profile ambiguity this guards.
    const plausible = ranked.filter(r => r.d <= 0.11);
    return plausible.length === 1 ? plausible[0].id.slice(0, -"_weight".length) : null;
  }
  async statistics(ids, days) {
    const end = new Date(), start = new Date(end.getTime() - days * 86400000);
    return this._hass.callWS({ type: "recorder/statistics_during_period", start_time: start.toISOString(), end_time: end.toISOString(), statistic_ids: ids, period: "day", types: ["state"] });
  }
  async loadLatest() {
    if (!this.available.length) return;
    const data = await this.statistics(this.available.map(m => this.statisticId(m)), 400);
    this.available.forEach(m => {
      const row = [...(data[this.statisticId(m)] || [])].reverse().find(x => Number.isFinite(Number(x.state)));
      if (row) this.latest.set(m.key, Number(row.state));
    });
  }
  async refreshMeasurements() {
    if (this.refreshing) return; this.refreshing = true;
    try { await this.loadLatest(); this.updateValues(); await this.createGraphs(); }
    finally { this.refreshing = false; }
  }
  get days() { return { "7d":7, "14d":14, "1m":30, "3m":90, "1j":365 }[this.range]; }
  async createGraphs() {
    if (!this.canCreateGraphs(this.graphGeneration)) {
      // Only ever schedule a resume for the one legitimate, temporary
      // reason: a real (non-stub) profile, selected for graphs display,
      // connected, ready, with a resolved prefix - just still missing
      // hass. Every other rejection (compact display, the stub profile,
      // disconnected, not ready or no prefix yet) is not "pending" at all:
      // initialize()/findPrefix() own those paths and call createGraphs()
      // again themselves once they can legitimately do so.
      this.graphsPending = !!(
        this.config?.profile &&
        this.config.profile !== STUB_PROFILE &&
        this.config.display !== "compact" &&
        this.ready &&
        this.statisticPrefix &&
        this.isConnected &&
        !this._hass?.config
      );
      return;
    }
    const helpers = await window.loadCardHelpers();
    // Build the next generation of graph elements off to the side; only
    // this.graphs (and the DOM) get updated once every element in this
    // batch is confirmed configured, and only if a newer call (a period
    // switch, a refresh, an editor-preview reconfigure) has not since
    // superseded this one. This never leaves an unconfigured element
    // reachable from either this.graphs or the connected DOM, and a
    // superseded call's own (never-attached) elements are simply dropped.
    const generation = ++this.graphGeneration;
    const built = new Map();
    for (const m of this.available) {
      // canCreateGraphs() again: a switch to the stub profile, a display
      // change, a disconnect, or a newer generation can all have happened
      // during any of the awaits below (this one included, on the very
      // first iteration) - never create or touch a graph element once any
      // of that invalidated this build.
      if (!this.canCreateGraphs(generation)) return;
      // createCardElement() triggers hui-statistics-graph-card's lazy
      // import when this is the first use this session (Home Assistant's
      // own create-element-base.ts, LAZY_LOAD_TYPES); the element it
      // returns synchronously may not be upgraded/configured yet. Waiting
      // for customElements.whenDefined() *before* touching any property on
      // it - never setting .hass right after creation - is what avoids the
      // pre-upgrade shadowing described in GRAPH_CARD_TAG's comment above.
      const graph = helpers.createCardElement({ type:GRAPH_CARD_TYPE, entities:[this.statisticId(m)], days_to_show:this.days, period:"day", chart_type:"line", stat_types:["state"], hide_legend:true });
      await customElements.whenDefined(GRAPH_CARD_TAG);
      if (!this.canCreateGraphs(generation)) return;
      graph.hass = this._hass;
      if (
        // Validity, not just equality: a stale generation created while
        // hass was briefly missing must never slip through just because
        // both sides of an equality check happened to be undefined.
        !this._hass ||
        !this._hass.config ||
        !(graph instanceof customElements.get(GRAPH_CARD_TAG)) ||
        Object.hasOwn(graph, "hass") ||
        !graph.hass ||
        graph.hass !== this._hass ||
        !graph.hass.config
      ) {
        // Unreachable given the guards above; a thrown error here must
        // surface, never be hidden, since it would mean one of those
        // guarantees itself regressed.
        throw Error("FITAGE: het grafiekelement is niet correct opgewaardeerd, geconfigureerd of van een geldige hass voorzien vóór gebruik.");
      }
      built.set(m.key, graph);
    }
    if (!this.canCreateGraphs(generation)) return;
    this.graphs = built;
    this.graphs.forEach((g,k)=>this.shadowRoot.querySelector(`#graph-${k}`)?.replaceChildren(g));
  }
  values(m) {
    const state = this._hass?.states?.[this.entityId(m)];
    let min=state?.attributes?.normal_min, max=state?.attributes?.normal_max;
    const weight=Number(this._hass?.states?.[this.weightEntityId()]?.state ?? this.latest.get("weight"));
    const percentageMetric={body_fat_mass:"bodyfat",body_water_mass:"water",protein_mass:"protein"}[m.key];
    if(percentageMetric && Number.isFinite(weight) && weight>0){
      const source=METRICS.find(item=>item.key===percentageMetric);
      const percentageState=this._hass?.states?.[this.entityId(source)];
      const percentageMin=Number(percentageState?.attributes?.normal_min);
      const percentageMax=Number(percentageState?.attributes?.normal_max);
      if(Number.isFinite(percentageMin))min=weight*percentageMin/100;
      if(Number.isFinite(percentageMax))max=weight*percentageMax/100;
    }
    if(m.key==="bone" && Number.isFinite(weight) && weight>0){
      if(!Number.isFinite(Number(min)))min=weight*0.03;
      if(!Number.isFinite(Number(max)))max=weight*0.05;
    }
    if(m.key==="bmr")max=undefined;
    return { current: state ? state.state : this.latest.get(m.key), min, max, unit:state?.attributes?.unit_of_measurement ?? m.unit };
  }
  format(v,u,key) {
    if (v === undefined || v === null || typeof v === "boolean" || (typeof v === "string" && v.trim() === "")) return "—";
    const n=Number(v); const digits=PRECISION[key] ?? 1;
    return Number.isFinite(n) ? `${n.toLocaleString("nl-NL",{minimumFractionDigits:0,maximumFractionDigits:digits})}${u?` ${u}`:""}` : "—";
  }
  updateValues() {
    this.available.forEach(m => { const v=this.values(m); ["current","min","max"].forEach(k => { const e=this.shadowRoot.querySelector(`#${k}-${m.key}`); if(e)e.textContent=this.format(v[k],v.unit,m.key); }); });
  }
  async selectRange(r) {
    if(r===this.range)return; this.range=r;
    this.shadowRoot.querySelectorAll("button").forEach(b=>b.classList.toggle("selected",b.dataset.range===r)); await this.createGraphs();
  }
  metricHtml(m) {
    const v=this.values(m), cells=[`<div class="value"><small>Actueel</small><b id="current-${m.key}" class="current">${this.format(v.current,v.unit,m.key)}</b></div>`];
    if(Number.isFinite(Number(v.min)))cells.push(`<div class="value"><small>Min normaal</small><b id="min-${m.key}" class="min">${this.format(v.min,v.unit,m.key)}</b></div>`);
    if(Number.isFinite(Number(v.max)))cells.push(`<div class="value"><small>Max normaal</small><b id="max-${m.key}" class="max">${this.format(v.max,v.unit,m.key)}</b></div>`);
    const graph=this.config.display === "compact" ? "" : `<div class="graph" id="graph-${m.key}">Grafiek laden…</div>`;
    return `<ha-card class="metric"><h2>${m.title}</h2><div class="values" style="--value-columns:${cells.length}">${cells.join("")}</div>${graph}</ha-card>`;
  }
  appearance() {
    const scale={small:0.85,normal:1,large:1.18}[this.config.text_size] || 1;
    const validColor=(value,fallback)=>/^#[0-9a-f]{6}$/i.test(value||"")?value:fallback;
    const custom=this.config.custom_colors===true;
    return `--fitage-text-scale:${scale};--fitage-current-color:${custom?validColor(this.config.current_color,"#ff9800"):"var(--warning-color,#ff9800)"};--fitage-min-color:${custom?validColor(this.config.min_color,"#03a9f4"):"var(--info-color,#03a9f4)"};--fitage-max-color:${custom?validColor(this.config.max_color,"#f44336"):"var(--error-color,#f44336)"};`;
  }
  render() {
    if(!this.config)return; const ranges=["7d","14d","1m","3m","1j"];
    const content = this.ready
      ? (this.available.length
          ? this.available.map(m=>this.metricHtml(m)).join("")
          : `<ha-card><div class="message">Selecteer minimaal één meetwaarde in de kaarteditor.</div></ha-card>`)
      : `<ha-card><div class="message">FITAGE-profiel en statistieken laden…</div></ha-card>`;
    const periods=this.config.display === "compact" ? "" : `<div class="periods">${ranges.map(r=>`<button data-range="${r}" class="${r===this.range?"selected":""}">${r}</button>`).join("")}</div>`;
    this.shadowRoot.innerHTML=`<style>:host{display:block;${this.appearance()}}.top{margin-bottom:12px}.title{padding:14px 16px 12px;font-size:calc(18px * var(--fitage-text-scale));font-weight:600}.periods{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;padding:0 12px 12px}.periods button{min-height:40px;border:1px solid var(--divider-color);border-radius:22px;background:var(--ha-card-background,var(--card-background-color));color:var(--primary-text-color);font:inherit;font-weight:600}.periods button.selected{background:var(--primary-color);color:var(--text-primary-color);border-color:var(--primary-color)}.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.metric{overflow:hidden}.metric h2{padding:14px 16px;margin:0;font-size:calc(17px * var(--fitage-text-scale))}.values{display:grid;grid-template-columns:repeat(var(--value-columns,1),1fr);border-block:1px solid var(--divider-color)}.compact .values{border-bottom:0}.value{text-align:center;padding:12px 3px 9px}.value+.value{border-left:1px solid var(--divider-color)}small{display:block;margin-bottom:4px;font-size:calc(12px * var(--fitage-text-scale))}b{display:block;font-size:calc(21px * var(--fitage-text-scale));white-space:nowrap}.current{color:var(--fitage-current-color)}.min{color:var(--fitage-min-color)}.max{color:var(--fitage-max-color)}.graph{min-height:210px;padding:0;color:var(--secondary-text-color)}.graph>*{--ha-card-border-width:0;--ha-card-box-shadow:none}.message{padding:24px 16px}.error{color:var(--error-color,#f44336)}@media(max-width:1200px){.cards{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:900px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){.cards{grid-template-columns:1fr}.periods{gap:4px;padding-inline:8px}.periods button{min-width:0}}</style><ha-card class="top"><div class="title">${this.config.title} – ${this.config.profile}</div>${periods}</ha-card>${this.error?`<ha-card><div class="message error">${this.error}</div></ha-card>`:this.hint?`<ha-card><div class="message">${this.hint}</div></ha-card>`:`<div class="cards ${this.config.display === "compact" ? "compact" : "graphs"}">${content}</div>`}`;
    this.shadowRoot.querySelectorAll("button").forEach(b=>b.addEventListener("click",()=>this.selectRange(b.dataset.range)));
    this.graphs.forEach((g,k)=>this.shadowRoot.querySelector(`#graph-${k}`)?.replaceChildren(g));
  }
}

class FitageCardEditor extends HTMLElement {
  setConfig(c){this.config=c;this.render()} set hass(h){this._hass=h}
  dispatch(config){this.dispatchEvent(new CustomEvent("config-changed",{detail:{config},bubbles:true,composed:true}))}
  selected(){return Array.isArray(this.config.metrics)?new Set(this.config.metrics):new Set(METRICS.map(m=>m.key))}
  render(){
    if(!this.config)return;
    const selected=this.selected();
    const custom=this.config.custom_colors===true;
    this.innerHTML=`<style>.field{display:block;margin:0 0 16px}.field input:not([type=checkbox]),.field select{box-sizing:border-box;width:100%;padding:10px}.heading{display:flex;align-items:center;justify-content:space-between;margin:20px 0 8px;font-weight:600}.actions{display:flex;gap:8px}.actions button{padding:6px 10px}.metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 16px}.metric-option,.check{display:flex;align-items:center;gap:8px;min-height:34px}.colors{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:8px}.color input{height:42px;padding:3px!important}.color span{display:block;margin-bottom:4px;font-size:12px}@media(max-width:500px){.metrics,.colors{grid-template-columns:1fr}}</style><label class="field">FITAGE-profiel<br><input id="profile" value="${this.config.profile||""}"></label><label class="field">Titel<br><input id="title" value="${this.config.title||"FITAGE"}"></label><label class="field">Weergave<br><select id="display"><option value="graphs" ${(this.config.display||"graphs")==="graphs"?"selected":""}>Grafieken</option><option value="compact" ${this.config.display==="compact"?"selected":""}>Compact overzicht</option></select></label><div class="heading"><span>Uiterlijk</span></div><label class="field">Tekstgrootte<br><select id="text_size"><option value="small" ${this.config.text_size==="small"?"selected":""}>Klein</option><option value="normal" ${(this.config.text_size||"normal")==="normal"?"selected":""}>Normaal</option><option value="large" ${this.config.text_size==="large"?"selected":""}>Groot</option></select></label><label class="check"><input type="checkbox" id="custom_colors" ${custom?"checked":""}>Eigen kleuren gebruiken</label><div class="colors"><label class="color"><span>Actueel</span><input type="color" id="current_color" value="${this.config.current_color||"#ff9800"}" ${custom?"":"disabled"}></label><label class="color"><span>Minimum</span><input type="color" id="min_color" value="${this.config.min_color||"#03a9f4"}" ${custom?"":"disabled"}></label><label class="color"><span>Maximum</span><input type="color" id="max_color" value="${this.config.max_color||"#f44336"}" ${custom?"":"disabled"}></label></div><div class="heading"><span>Meetwaarden</span><span class="actions"><button type="button" id="all">Alles</button><button type="button" id="none">Geen</button></span></div><div class="metrics">${METRICS.map(m=>`<label class="metric-option"><input type="checkbox" data-metric="${m.key}" ${selected.has(m.key)?"checked":""}>${m.title}</label>`).join("")}</div>`;
    ["profile","title","display","text_size","current_color","min_color","max_color"].forEach(id=>this.querySelector(`#${id}`).addEventListener("change",event=>this.dispatch({...this.config,[id]:event.target.value})));
    this.querySelector("#custom_colors").addEventListener("change",event=>this.dispatch({...this.config,custom_colors:event.target.checked}));
    this.querySelectorAll("[data-metric]").forEach(input=>input.addEventListener("change",()=>{
      const metrics=[...this.querySelectorAll("[data-metric]:checked")].map(item=>item.dataset.metric);
      this.dispatch({...this.config,metrics});
    }));
    this.querySelector("#all").addEventListener("click",()=>{const config={...this.config};delete config.metrics;this.dispatch(config)});
    this.querySelector("#none").addEventListener("click",()=>this.dispatch({...this.config,metrics:[]}));
  }
}
if(!customElements.get("fitage-card"))customElements.define("fitage-card",FitageCard);
if(!customElements.get("fitage-card-editor"))customElements.define("fitage-card-editor",FitageCardEditor);
window.customCards=window.customCards||[];if(!window.customCards.some(c=>c.type==="fitage-card"))window.customCards.push({type:"fitage-card",name:"FITAGE Card",description:"Automatisch profieloverzicht met alle beschikbare grafieken",preview:true});
console.info(`%c FITAGE-CARD %c v${VERSION} `,"color:white;background:#008c95;font-weight:bold","color:#008c95;background:white");
