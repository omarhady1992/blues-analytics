/* Blues Analytics – a dependency-light single page app.
 * Data comes from ./data/*.json, produced by `python -m pipeline.update`.
 * Routing uses the URL hash (#/squad, #/player/12 ...) so it works on GitHub Pages.
 */
const $app = document.getElementById("app");
const DB = {};             // loaded JSON
const charts = [];         // live Chart.js instances (destroyed on navigation)
const BLUE = "#034694", GOLD = "#DBA111", RED = "#c0392b", GREY = "#8a94a6";

/* ---------------------------------------------------------------- utilities */
const fmt = (v, d = 2) => v == null || Number.isNaN(v) ? "–" : (Number.isInteger(v) ? String(v) : Number(v).toFixed(d));
const pct = (a, b) => (a == null || !b) ? null : 100 * a / b;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const sum = (rows, k) => { let t = null; for (const r of rows) if (r[k] != null) t = (t || 0) + r[k]; return t; };
const mean = (rows, k) => { const v = rows.map(r => r[k]).filter(x => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
const byId = (arr, key) => Object.fromEntries(arr.map(x => [x[key], x]));
const dateStr = iso => new Date(iso.slice(0, 16)).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
const timeStr = iso => iso.slice(11, 16);
function scoreLine(m) {
  return m.venue === "H" ? `Chelsea ${m.goals_for}–${m.goals_against} ${m.opponent}` : `${m.opponent} ${m.goals_against}–${m.goals_for} Chelsea`;
}
function newChart(el, cfg) { const c = new Chart(el, cfg); charts.push(c); return c; }
Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
Chart.defaults.maintainAspectRatio = false;

/* Aggregate a set of player-match rows into season totals + derived metrics. */
const SUM_COLS = ["started", "minutes", "goals", "assists", "xg", "xa", "shots", "shots_on_target", "chances_created",
  "big_chances_created", "touches", "touches_opp_box", "passes", "passes_accurate", "final_third_entries", "dribbles",
  "dribbles_won", "tackles", "interceptions", "recoveries", "clearances", "blocks", "defensive_actions", "duels_won",
  "duels_lost", "aerials_won", "aerials_lost", "yellow_cards", "red_cards", "saves", "goals_prevented"];
function aggregate(rows) {
  const a = { apps: rows.length };
  for (const k of SUM_COLS) a[k] = sum(rows, k);
  a.rating = mean(rows, "rating");
  a.pass_pct = pct(a.passes_accurate, a.passes);
  a.duel_pct = pct(a.duels_won, (a.duels_won || 0) + (a.duels_lost || 0));
  a.p90 = k => (a[k] == null || !a.minutes) ? null : a[k] * 90 / a.minutes;
  return a;
}

/* Sortable table: cols = [{k, label, fmt?, cls?, html?}] */
function table(cols, rows, { sortKey, asc = false, id = "t" } = {}) {
  const state = { sortKey, asc };
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  function render() {
    const sorted = [...rows];
    if (state.sortKey) {
      const c = cols.find(c => c.k === state.sortKey);
      const val = r => c.sort ? c.sort(r) : r[c.k];
      sorted.sort((a, b) => {
        const x = val(a), y = val(b);
        if (x == null) return 1; if (y == null) return -1;
        return (x > y ? 1 : x < y ? -1 : 0) * (state.asc ? 1 : -1);
      });
    }
    wrap.innerHTML = `<table id="${id}"><thead><tr>${cols.map(c =>
      `<th data-k="${c.k}" class="${c.cls || ""} ${state.sortKey === c.k ? "sorted" + (state.asc ? " asc" : "") : ""}" title="${esc(c.title || "")}">${c.label}</th>`).join("")}</tr></thead>
      <tbody>${sorted.map(r => `<tr>${cols.map(c => `<td class="${c.cls || ""}">${c.html ? c.html(r) : (c.fmt ? c.fmt(r[c.k], r) : fmt(r[c.k]))}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    wrap.querySelectorAll("th").forEach(th => th.onclick = () => {
      const k = th.dataset.k;
      state.asc = state.sortKey === k ? !state.asc : false;
      state.sortKey = k; render();
    });
  }
  render();
  return wrap;
}

/* ---------------------------------------------------------------- pages */
function pageHome() {
  const ms = DB.matches;
  const w = ms.filter(m => m.result === "W").length, d = ms.filter(m => m.result === "D").length, l = ms.length - w - d;
  const gf = ms.reduce((a, m) => a + m.goals_for, 0), ga = ms.reduce((a, m) => a + m.goals_against, 0);
  const xg = ms.reduce((a, m) => a + (m.chelsea_xg || 0), 0), xga = ms.reduce((a, m) => a + (m.opponent_xg || 0), 0);
  const pl = ms.filter(m => m.competition === "Premier League");
  const plPts = pl.reduce((a, m) => a + (m.result === "W" ? 3 : m.result === "D" ? 1 : 0), 0);
  const up = DB.meta.upcoming || [];
  $app.innerHTML = `
    <h1>Chelsea ${DB.meta.season} · Season overview</h1>
    <p class="sub">All competitive men's first-team matches · ${ms.length} played · times in Cairo time</p>
    <div class="grid g4">
      <div class="card kpi"><div class="v">${w}-${d}-${l}</div><div class="l">W-D-L (all comps)</div></div>
      <div class="card kpi"><div class="v">${plPts} pts</div><div class="l">Premier League, ${pl.length} played</div></div>
      <div class="card kpi"><div class="v">${gf}–${ga}</div><div class="l">Goals for – against</div></div>
      <div class="card kpi"><div class="v">${fmt(xg, 1)}–${fmt(xga, 1)}</div><div class="l">xG for – against</div></div>
    </div>
    <div class="grid g2" style="margin-top:1rem">
      <div class="card"><h2 style="margin-top:0">Form (latest last)</h2><div class="form">${ms.map(m =>
        `<a class="badge ${m.result}" href="#/match/${m.match_id}" title="${esc(scoreLine(m))} (${m.competition})">${m.result}</a>`).join("")}</div>
        <h2>Next fixtures</h2>${up.length ? `<div class="list">${up.map(f => `<div class="item" style="display:flex;justify-content:space-between;padding:.35rem 0;border-bottom:1px solid var(--line)">
          <span>${f.venue === "H" ? "vs" : "at"} <strong>${esc(f.opponent)}</strong> <span class="pill">${esc(f.competition)}</span></span>
          <span class="muted">${dateStr(f.kickoff_local)} ${timeStr(f.kickoff_local)}</span></div>`).join("")}</div>` : `<p class="muted">No upcoming fixtures listed.</p>`}
      </div>
      <div class="card"><h2 style="margin-top:0">xG for vs against, match by match</h2><div class="chart-box"><canvas id="cXg"></canvas></div></div>
    </div>
    <div class="grid g2" style="margin-top:1rem">
      <div class="card"><h2 style="margin-top:0">Cumulative goals vs xG</h2><div class="chart-box"><canvas id="cCum"></canvas></div></div>
      <div class="card"><h2 style="margin-top:0">Top contributors (all comps)</h2><div id="top"></div></div>
    </div>`;
  const labels = ms.map(m => `${m.venue === "H" ? "" : "@"}${m.opponent.slice(0, 3).toUpperCase()}`);
  newChart(document.getElementById("cXg"), {
    type: "bar", data: { labels, datasets: [
      { label: "Chelsea xG", data: ms.map(m => m.chelsea_xg), backgroundColor: BLUE },
      { label: "Opponent xG", data: ms.map(m => m.opponent_xg), backgroundColor: RED }] },
    options: { plugins: { tooltip: { callbacks: { title: i => scoreLine(ms[i[0].dataIndex]) } } } }
  });
  let cg = 0, cx = 0, ca = 0, cxa = 0;
  newChart(document.getElementById("cCum"), {
    type: "line", data: { labels, datasets: [
      { label: "Goals", data: ms.map(m => cg += m.goals_for), borderColor: BLUE, backgroundColor: BLUE, tension: .2 },
      { label: "xG", data: ms.map(m => +(cx += m.chelsea_xg || 0).toFixed(2)), borderColor: BLUE, borderDash: [6, 4], tension: .2 },
      { label: "Goals against", data: ms.map(m => ca += m.goals_against), borderColor: RED, backgroundColor: RED, tension: .2 },
      { label: "xG against", data: ms.map(m => +(cxa += m.opponent_xg || 0).toFixed(2)), borderColor: RED, borderDash: [6, 4], tension: .2 }] }
  });
  const agg = squadAggregates(DB.pm).filter(p => p.minutes > 0);
  const top = document.getElementById("top");
  top.appendChild(table([
    { k: "name", label: "Player", cls: "l", html: r => `<a href="#/player/${r.player_id}">${esc(r.name)}</a>` },
    { k: "goals", label: "G" }, { k: "assists", label: "A" }, { k: "xg", label: "xG" }, { k: "xa", label: "xA" },
    { k: "rating", label: "Avg rating" }], agg.sort((a, b) => (b.goals + b.assists) - (a.goals + a.assists)).slice(0, 8), { sortKey: "goals" }));
}

function squadAggregates(rows) {
  const by = {};
  for (const r of rows) (by[r.player_id] ||= []).push(r);
  return Object.entries(by).map(([pid, rs]) => {
    const p = DB.playersById[pid];
    return { player_id: +pid, name: p.name, position: p.position, age: p.age, shirt: p.shirt_number, in_pl_squad: p.in_pl_squad, ...aggregate(rs) };
  });
}

function pageSquad() {
  const comps = [...new Set(DB.matches.map(m => m.competition))];
  $app.innerHTML = `<h1>Squad</h1><p class="sub">Click a column to sort. Per-90 values need minutes, so use the minimum-minutes filter to hide small samples.</p>
    <div class="filters">
      <label>Competition <select id="fComp"><option value="">All</option>${comps.map(c => `<option>${c}</option>`).join("")}</select></label>
      <label>Position <select id="fPos"><option value="">All</option><option>Goalkeeper</option><option>Defender</option><option>Midfielder</option><option>Forward</option></select></label>
      <label>Min. minutes <input id="fMin" type="number" value="0" min="0" step="45" style="width:5rem"></label>
      <label><input id="fSearch" placeholder="Search player" style="width:9rem"></label>
      <span class="seg"><button id="vTot" class="on">Totals</button><button id="vP90">Per 90</button></span>
    </div><div id="tbl"></div>
    <p class="muted" style="font-size:.8rem">Def. actions = tackles + interceptions + recoveries + clearances + blocks. F3 = final-third entries. Ratings: FotMob. Players marked † are not in the current Premier League squad list.</p>`;
  let per90 = false;
  const render = () => {
    const comp = fComp.value, pos = fPos.value, min = +fMin.value || 0, q = fSearch.value.toLowerCase();
    const ids = new Set(DB.matches.filter(m => !comp || m.competition === comp).map(m => m.match_id));
    let rows = squadAggregates(DB.pm.filter(r => ids.has(r.match_id)))
      .filter(r => (!pos || r.position === pos) && r.minutes >= min && r.name.toLowerCase().includes(q));
    const v = k => per90 ? (r => r.p90(k)) : (r => r[k]);
    const m = ["goals", "assists", "xg", "xa", "shots", "chances_created", "final_third_entries", "dribbles_won", "touches_opp_box", "defensive_actions", "duels_won"];
    rows = rows.map(r => { const o = { ...r }; m.forEach(k => o["v_" + k] = v(k)(r)); return o; });
    const lab = { goals: "G", assists: "A", xg: "xG", xa: "xA", shots: "Shots", chances_created: "Chances", final_third_entries: "F3", dribbles_won: "Drb won", touches_opp_box: "Box touches", defensive_actions: "Def. actions", duels_won: "Duels won" };
    const cols = [
      { k: "name", label: "Player", cls: "l", html: r => `<a href="#/player/${r.player_id}">${esc(r.name)}</a>${r.in_pl_squad ? "" : " †"}` },
      { k: "position", label: "Pos", cls: "l", fmt: v => (v || "").slice(0, 3) },
      { k: "age", label: "Age" }, { k: "apps", label: "Apps" }, { k: "started", label: "Starts" }, { k: "minutes", label: "Min" },
      ...m.map(k => ({ k: "v_" + k, label: lab[k] + (per90 ? "/90" : ""), fmt: x => fmt(x, per90 ? 2 : 2) })),
      { k: "pass_pct", label: "Pass %", fmt: x => fmt(x, 1) }, { k: "duel_pct", label: "Duel %", fmt: x => fmt(x, 1) },
      { k: "rating", label: "Rating", fmt: x => fmt(x, 2) }];
    const t = document.getElementById("tbl"); t.innerHTML = "";
    t.appendChild(table(cols, rows, { sortKey: "minutes" }));
  };
  const [fComp, fPos, fMin, fSearch] = ["fComp", "fPos", "fMin", "fSearch"].map(id => document.getElementById(id));
  [fComp, fPos, fMin, fSearch].forEach(el => el.oninput = render);
  vTot.onclick = () => { per90 = false; vTot.classList.add("on"); vP90.classList.remove("on"); render(); };
  vP90.onclick = () => { per90 = true; vP90.classList.add("on"); vTot.classList.remove("on"); if (+fMin.value < 180) fMin.value = 180; render(); };
  render();
}

const RADAR = [
  ["xg", "xG"], ["xa", "xA"], ["shots", "Shots"], ["chances_created", "Chances"], ["dribbles_won", "Dribbles won"],
  ["final_third_entries", "F3 entries"], ["touches_opp_box", "Box touches"], ["defensive_actions", "Def. actions"],
  ["duels_won", "Duels won"], ["pass_pct", "Pass %"]];

function pagePlayer(id) {
  const p = DB.playersById[id];
  if (!p) return notFound();
  const rows = DB.pm.filter(r => r.player_id === +id).sort((a, b) => DB.matchesById[a.match_id].kickoff_local.localeCompare(DB.matchesById[b.match_id].kickoff_local));
  const a = aggregate(rows);
  $app.innerHTML = `<p><a href="#/squad">← Squad</a></p>
    <h1>${p.shirt_number ? `<span class="pill">#${p.shirt_number}</span> ` : ""}${esc(p.name)}</h1>
    <p class="sub">${[p.position, p.nationality, p.age != null ? `age ${p.age}` : null, p.height_cm ? `${p.height_cm} cm` : null, p.preferred_foot ? `${p.preferred_foot}-footed` : null].filter(Boolean).join(" · ")}${p.in_pl_squad ? "" : " · not in the current PL squad list"}</p>
    <div class="grid g4">
      <div class="card kpi"><div class="v">${a.apps}</div><div class="l">Apps (${fmt(a.started)} starts)</div></div>
      <div class="card kpi"><div class="v">${fmt(a.minutes)}</div><div class="l">Minutes</div></div>
      <div class="card kpi"><div class="v">${fmt(a.goals)} + ${fmt(a.assists)}</div><div class="l">Goals + assists</div></div>
      <div class="card kpi"><div class="v">${fmt(a.xg)} / ${fmt(a.xa)}</div><div class="l">xG / xA</div></div>
      <div class="card kpi"><div class="v">${fmt(a.rating)}</div><div class="l">Avg FotMob rating</div></div>
    </div>
    ${rows.length ? `<div class="grid g2" style="margin-top:1rem">
      <div class="card"><h2 style="margin-top:0">Match by match: xG, xA and minutes</h2><div class="chart-box"><canvas id="cPm"></canvas></div></div>
      <div class="card"><h2 style="margin-top:0">Radar vs squad <span class="muted" style="font-size:.8rem">(percentile, per 90)</span></h2><div class="chart-box"><canvas id="cRadar"></canvas></div><p class="muted" id="radarNote" style="font-size:.8rem"></p></div>
    </div>
    <div class="card" style="margin-top:1rem"><h2 style="margin-top:0">Rating and defensive actions</h2><div class="chart-box" style="height:220px"><canvas id="cRat"></canvas></div></div>
    <h2>Match log</h2><div id="log"></div>` : `<p class="muted">No competitive minutes yet this season.</p>`}`;
  if (!rows.length) return;
  const labels = rows.map(r => { const m = DB.matchesById[r.match_id]; return `${m.venue === "H" ? "" : "@"}${m.opponent.slice(0, 3).toUpperCase()}`; });
  newChart(cPm, { data: { labels, datasets: [
    { type: "bar", label: "xG", data: rows.map(r => r.xg), backgroundColor: BLUE, stack: "x" },
    { type: "bar", label: "xA", data: rows.map(r => r.xa), backgroundColor: GOLD, stack: "x" },
    { type: "line", label: "Minutes", data: rows.map(r => r.minutes), borderColor: GREY, yAxisID: "y2", tension: .2 }] },
    options: { scales: { x: { stacked: true }, y: { stacked: true, title: { display: true, text: "xG / xA" } }, y2: { position: "right", min: 0, suggestedMax: 90, grid: { display: false }, title: { display: true, text: "minutes" } } } } });
  newChart(cRat, { data: { labels, datasets: [
    { type: "line", label: "FotMob rating", data: rows.map(r => r.rating), borderColor: BLUE, backgroundColor: BLUE, spanGaps: true },
    { type: "bar", label: "Defensive actions", data: rows.map(r => r.defensive_actions), backgroundColor: "rgba(219,161,17,.55)", yAxisID: "y2" }] },
    options: { scales: { y: { min: 5, max: 10, title: { display: true, text: "rating" } }, y2: { position: "right", min: 0, grid: { display: false } } } } });

  // radar: percentile among squad players with >= 270 minutes, outfield vs outfield
  const pool = squadAggregates(DB.pm).filter(x => x.minutes >= 270 && (p.position === "Goalkeeper") === (x.position === "Goalkeeper"));
  const val = (x, k) => k === "pass_pct" ? x.pass_pct : x.p90(k);
  const me = squadAggregates(rows)[0];
  const pctile = k => { const vs = pool.map(x => val(x, k)).filter(v => v != null); const v = val(me, k); if (v == null || !vs.length) return null; return Math.round(100 * vs.filter(x => x <= v).length / vs.length); };
  newChart(cRadar, { type: "radar", data: { labels: RADAR.map(r => r[1]), datasets: [{ label: p.name, data: RADAR.map(r => pctile(r[0])), backgroundColor: "rgba(3,70,148,.25)", borderColor: BLUE, pointBackgroundColor: BLUE }] },
    options: { scales: { r: { min: 0, max: 100, ticks: { stepSize: 25, display: false } } }, plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `${c.raw}th pct · ${fmt(val(me, RADAR[c.dataIndex][0]))}${RADAR[c.dataIndex][0] === "pass_pct" ? "%" : "/90"}` } } } } });
  radarNote.textContent = `Compared with ${pool.length} ${p.position === "Goalkeeper" ? "goalkeepers" : "outfield players"} with 270+ minutes.` + (me.minutes < 270 ? " Small sample: this player has fewer than 270 minutes." : "");

  document.getElementById("log").appendChild(table([
    { k: "date", label: "Date", cls: "l", sort: r => DB.matchesById[r.match_id].kickoff_local, html: r => dateStr(DB.matchesById[r.match_id].kickoff_local) },
    { k: "match", label: "Match", cls: "l", html: r => { const m = DB.matchesById[r.match_id]; return `<a href="#/match/${m.match_id}">${esc(scoreLine(m))}</a>`; } },
    { k: "started", label: "XI", fmt: v => v ? "✓" : "" }, { k: "minutes", label: "Min" }, { k: "goals", label: "G" }, { k: "assists", label: "A" },
    { k: "xg", label: "xG" }, { k: "xa", label: "xA" }, { k: "shots", label: "Shots" }, { k: "chances_created", label: "Chances" },
    { k: "passes_accurate", label: "Passes", html: r => `${fmt(r.passes_accurate)}/${fmt(r.passes)}` },
    { k: "final_third_entries", label: "F3" }, { k: "dribbles_won", label: "Drb" }, { k: "defensive_actions", label: "Def" },
    { k: "duels_won", label: "Duels W" }, { k: "rating", label: "Rating", fmt: v => fmt(v, 1) }], rows, { sortKey: "date", asc: true }));
}

function pageMatches() {
  $app.innerHTML = `<h1>Matches</h1><p class="sub">Kick-off times in Cairo time.</p><div id="tbl"></div>`;
  document.getElementById("tbl").appendChild(table([
    { k: "kickoff_local", label: "Date", cls: "l", html: r => `${dateStr(r.kickoff_local)} <span class="muted">${timeStr(r.kickoff_local)}</span>` },
    { k: "competition", label: "Comp", cls: "l" },
    { k: "opponent", label: "Match", cls: "l", html: r => `<a href="#/match/${r.match_id}">${esc(scoreLine(r))}</a>` },
    { k: "result", label: "Res", html: r => `<span class="badge ${r.result}">${r.result}</span>` },
    { k: "chelsea_xg", label: "xG" }, { k: "opponent_xg", label: "xGA" },
    { k: "chelsea_shots", label: "Shots" }, { k: "opponent_shots", label: "Shots A" },
    { k: "chelsea_possession", label: "Poss %", fmt: v => fmt(v, 1) },
    { k: "report", label: "Report", html: r => `<a href="#/reports/match/${r.match_id}">Read</a>` }],
    DB.matches, { sortKey: "kickoff_local" }));
}

async function pageMatch(id) {
  const m = DB.matchesById[id];
  if (!m) return notFound();
  const detail = await getJSON(`data/matches/${id}.json`);
  const rows = DB.pm.filter(r => r.match_id === +id).map(r => ({ ...r, name: DB.playersById[r.player_id].name }));
  const home = m.venue === "H";
  $app.innerHTML = `<p><a href="#/matches">← Matches</a></p>
    <div class="card"><div class="muted" style="text-align:center">${esc(m.competition)}${m.round ? ` · Round ${esc(m.round)}` : ""} · ${dateStr(m.kickoff_local)} ${timeStr(m.kickoff_local)} Cairo · ${esc(m.ground || "")}</div>
      <div class="score"><span>${home ? "Chelsea" : esc(m.opponent)}</span><span class="n">${home ? m.goals_for : m.goals_against}–${home ? m.goals_against : m.goals_for}</span><span>${home ? esc(m.opponent) : "Chelsea"}</span></div>
      <div style="text-align:center;margin-top:.4rem"><span class="badge ${m.result}">${m.result}</span> <span class="muted">Formation ${esc(m.formation || "?")} v ${esc(m.opp_formation || "?")}</span> · <a href="#/reports/match/${m.match_id}">Match report →</a></div></div>
    <div class="grid g2" style="margin-top:1rem">
      <div class="card"><h2 style="margin-top:0">Team stats <span class="muted" style="font-size:.8rem">Chelsea (blue) v ${esc(m.opponent)}</span></h2><div id="cmp"></div></div>
      <div class="card"><h2 style="margin-top:0">Shot map</h2><div id="srcSel"></div><div id="pitch"></div>
        <div class="legend"><span class="dot" style="background:${BLUE}"></span>Chelsea (attacking →)<span class="dot" style="background:${RED}"></span>${esc(m.opponent)} (attacking ←) · size = xG · filled = goal</div></div>
    </div>
    <h2>Standout performers</h2><div class="grid g4" id="stand"></div>
    <h2>Chelsea players</h2><div id="tbl"></div>
    <p class="muted" style="font-size:.8rem">Player stats source: ${m.player_stats_source === "premier_league" ? "Opta via premierleague.com (ratings and physical data: FotMob)" : "FotMob"}.</p>`;
  const cmp = [["Possession %", "possession"], ["xG", "xg"], ["Shots", "shots"], ["On target", "shots_on_target"], ["Big chances", "big_chances"],
    ["Box touches", "touches_opp_box"], ["Passes", "passes"], ["Corners", "corners"], ["Tackles", "tackles"], ["Saves", "saves"]];
  document.getElementById("cmp").innerHTML = cmp.map(([lab, k]) => {
    const a = m["chelsea_" + k], b = m["opponent_" + k];
    if (a == null && b == null) return "";
    const t = (a || 0) + (b || 0) || 1;
    return `<div class="cmp"><div class="lab">${lab}</div><div class="va">${fmt(a, k === "possession" ? 1 : 2)}</div><div class="bar"><div class="a" style="width:${100 * (a || 0) / t}%"></div><div class="b" style="width:${100 * (b || 0) / t}%"></div></div><div class="vb">${fmt(b, k === "possession" ? 1 : 2)}</div></div>`;
  }).join("") + (m.xg_understat_for != null ? `<p class="muted" style="font-size:.8rem">Understat xG model: ${fmt(m.xg_understat_for)} v ${fmt(m.xg_understat_against)}</p>` : "");

  const sources = [...new Set(detail.shots.map(s => s.source))];
  let src = sources.includes("understat") ? "understat" : sources[0];
  const drawShots = () => {
    document.getElementById("pitch").innerHTML = shotMap(detail.shots.filter(s => s.source === src));
    document.getElementById("srcSel").innerHTML = sources.length > 1 ? `<span class="seg" style="margin-bottom:.5rem">${sources.map(s => `<button data-s="${s}" class="${s === src ? "on" : ""}">${s === "understat" ? "Understat" : "FotMob"}</button>`).join("")}</span>` : `<p class="muted" style="font-size:.8rem;margin:0 0 .4rem">Source: ${src === "understat" ? "Understat" : "FotMob"}</p>`;
    document.querySelectorAll("#srcSel button").forEach(b => b.onclick = () => { src = b.dataset.s; drawShots(); });
  };
  if (sources.length) drawShots(); else document.getElementById("pitch").innerHTML = `<p class="muted">No shot data.</p>`;

  const best = (k, lab, f = x => fmt(x)) => { const r = rows.filter(r => r[k] != null).sort((a, b) => b[k] - a[k])[0]; return r && r[k] > 0 ? `<div class="card kpi"><div class="l">${lab}</div><div class="v" style="font-size:1.2rem"><a href="#/player/${r.player_id}">${esc(r.name)}</a></div><div class="l">${f(r[k])}</div></div>` : ""; };
  document.getElementById("stand").innerHTML = best("rating", "Top rating (FotMob)", v => fmt(v, 1)) + best("xg", "Most xG", v => `${fmt(v)} xG`) +
    best("chances_created", "Most chances created", v => `${v} chances`) + best("final_third_entries", "Most final-third entries", v => `${v} entries`) +
    best("defensive_actions", "Most defensive actions", v => `${v} actions`) + best("duels_won", "Most duels won", v => `${v} duels`);
  document.getElementById("tbl").appendChild(table([
    { k: "name", label: "Player", cls: "l", html: r => `<a href="#/player/${r.player_id}">${esc(r.name)}</a>` },
    { k: "started", label: "XI", fmt: v => v ? "✓" : "" }, { k: "minutes", label: "Min" }, { k: "goals", label: "G" }, { k: "assists", label: "A" },
    { k: "xg", label: "xG" }, { k: "xa", label: "xA" }, { k: "shots", label: "Shots" }, { k: "chances_created", label: "Chances" },
    { k: "passes_accurate", label: "Passes", html: r => `${fmt(r.passes_accurate)}/${fmt(r.passes)}` },
    { k: "final_third_entries", label: "F3" }, { k: "dribbles_won", label: "Drb" }, { k: "defensive_actions", label: "Def" },
    { k: "duels_won", label: "Duels W" }, { k: "distance_m", label: "Km", fmt: v => v == null ? "–" : (v / 1000).toFixed(1) },
    { k: "rating", label: "Rating", fmt: v => fmt(v, 1) }], rows, { sortKey: "minutes" }));
}

/* Horizontal pitch, 105 x 68. Chelsea shoot towards the right, opponents towards the left. */
function shotMap(shots) {
  const W = 105, H = 68, line = 'stroke="rgba(255,255,255,.8)" stroke-width=".35" fill="none"';
  const pitch = `<rect x="0" y="0" width="${W}" height="${H}" ${line}/><line x1="52.5" y1="0" x2="52.5" y2="${H}" ${line}/>
    <circle cx="52.5" cy="34" r="9.15" ${line}/><rect x="0" y="13.84" width="16.5" height="40.32" ${line}/><rect x="${W - 16.5}" y="13.84" width="16.5" height="40.32" ${line}/>
    <rect x="0" y="24.84" width="5.5" height="18.32" ${line}/><rect x="${W - 5.5}" y="24.84" width="5.5" height="18.32" ${line}/>`;
  const dots = shots.map(s => {
    const ours = s.side === "chelsea";
    const x = ours ? s.x * W : (1 - s.x) * W, y = ours ? s.y * H : (1 - s.y) * H;
    const r = 0.8 + Math.sqrt(s.xg || 0) * 3.2, c = ours ? BLUE : RED, goal = s.result === "Goal";
    return `<circle cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="${r.toFixed(2)}" fill="${goal ? c : "rgba(255,255,255,.75)"}" stroke="${c}" stroke-width=".5"><title>${esc(s.player_name)} ${s.minute}' · xG ${fmt(s.xg)} · ${esc(s.result)}${s.situation ? " · " + esc(s.situation) : ""}</title></circle>`;
  }).join("");
  return `<svg class="pitch" viewBox="-2 -2 ${W + 4} ${H + 4}">${pitch}${dots}</svg>`;
}

/* ---------------------------------------------------------------- reports */
function pageReports(kind) {
  const idx = DB.reports;
  const tab = kind || "match";
  const names = { match: "Match reports", monthly: "Monthly reports", season: "Season review" };
  const items = idx[tab] || [];
  $app.innerHTML = `<h1>Reports</h1><p class="sub">Generated from the data after every match — no opinions, only what the numbers say.</p>
    <div class="tabs">${Object.entries(names).map(([k, v]) => `<a href="#/reports/${k}" class="${k === tab ? "on" : ""}">${v}</a>`).join("")}</div>
    <div class="card list" style="padding:0">${items.map(it => `<a class="item" href="#/reports/${tab}/${it.id}">
      <span>${tab === "match" ? `<span class="badge ${it.result}">${it.result}</span> ` : ""}${esc(it.title)}</span>
      <span class="muted">${tab === "match" ? `${esc(it.competition)} · ${dateStr(it.date)}` : tab === "monthly" ? `${it.matches} matches` : (it.placeholder ? "placeholder" : "")}</span></a>`).join("") || `<p class="muted" style="padding:1rem">Nothing yet.</p>`}</div>`;
}

async function pageReport(kind, id) {
  const r = await fetch(`data/reports/${kind}/${id}.md`, { cache: "no-cache" });
  if (!r.ok) return notFound();
  const md = await r.text();
  $app.innerHTML = `<p><a href="#/reports/${kind}">← ${kind === "match" ? "Match reports" : kind === "monthly" ? "Monthly reports" : "Reports"}</a>${kind === "match" ? ` · <a href="#/match/${id}">Match page & shot map</a>` : ""}</p>
    <article class="report">${marked.parse(md)}</article>`;
}

function pageAbout() {
  $app.innerHTML = `<h1>About</h1><article class="report">
    <p><strong>Blues Analytics</strong> is a hobby project that tracks Chelsea's men's first team match by match: a player database, per-match performance numbers, automatic match reports, monthly reports and (later) a season review.</p>
    <h2>Data sources</h2><ul>${DB.meta.sources.map(s => `<li><strong>${esc(s.name)}</strong> — ${esc(s.used_for)}</li>`).join("")}</ul>
    <p>Different providers measure some things slightly differently (for example each xG model is different). Each page says which source it shows. A dash (–) means the source did not provide that number; it is never treated as zero.</p>
    <h2>Glossary</h2><ul>
      <li><strong>xG</strong> (expected goals): how likely the shots were to be scored. <strong>xA</strong>: the xG of shots a player set up.</li>
      <li><strong>Final-third entries</strong>: passes or carries into the attacking third. <strong>Box touches</strong>: touches in the opposition penalty area.</li>
      <li><strong>Defensive actions</strong>: tackles + interceptions + recoveries + clearances + blocks.</li>
      <li><strong>Per 90</strong>: total ÷ minutes × 90. Small samples can mislead, so use the minimum-minutes filter.</li></ul>
    <p>Last update: ${esc(DB.meta.generated_at)} (Cairo time). Code: <a href="https://github.com/omarhady1992/blues-analytics">github.com/omarhady1992/blues-analytics</a></p></article>`;
}

function notFound() { $app.innerHTML = `<h1>Not found</h1><p><a href="#/">Back to overview</a></p>`; }

/* ---------------------------------------------------------------- router */
async function getJSON(url) { const r = await fetch(url, { cache: "no-cache" }); if (!r.ok) throw new Error(url + " " + r.status); return r.json(); }

async function route() {
  charts.splice(0).forEach(c => c.destroy());
  document.body.classList.remove("nav-open");
  const [page, a, b] = location.hash.replace(/^#\/?/, "").split("/");
  document.querySelectorAll("nav a").forEach(x => x.classList.toggle("active", x.dataset.route === (page || "home") || (x.dataset.route === "matches" && page === "match") || (x.dataset.route === "squad" && page === "player")));
  window.scrollTo(0, 0);
  try {
    if (!page) pageHome();
    else if (page === "squad") pageSquad();
    else if (page === "player") pagePlayer(a);
    else if (page === "matches") pageMatches();
    else if (page === "match") await pageMatch(a);
    else if (page === "reports") b ? await pageReport(a, b) : pageReports(a);
    else if (page === "about") pageAbout();
    else notFound();
  } catch (e) { console.error(e); $app.innerHTML = `<p>Something went wrong: ${esc(e.message)}</p>`; }
}

(async function init() {
  const [meta, matches, players, pm, reports] = await Promise.all(
    ["meta", "matches", "players", "player_matches", "reports/index"].map(n => getJSON(`data/${n}.json`)));
  Object.assign(DB, { meta, matches, players, pm, reports });
  DB.playersById = byId(players, "player_id");
  DB.matchesById = byId(matches, "match_id");
  document.getElementById("updated").textContent = `Data updated ${meta.generated_at} (Cairo time) · ${meta.matches} matches.`;
  window.addEventListener("hashchange", route);
  route();
})();
