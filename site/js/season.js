/* Season analysis & elite comparison.
 * renderSeason(root, D, opts) draws the whole page into `root` from season_analysis.json (D).
 * Used by the site (#/season-analysis) and by the standalone offline HTML export, so it
 * depends only on Chart.js. opts.onChart(chart) lets the host track charts for cleanup.
 */
(function () {
  const C = { blue: "#034694", gold: "#DBA111", red: "#c0392b", grey: "#8a94a6", cyan: "#2a9fd6", light: "#b9c6dc" };
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fx = (x, dp) => (x == null || Number.isNaN(x) || !Number.isFinite(x)) ? "n/a" : Number(x).toFixed(dp);
  const sg = (x, dp) => x == null ? "n/a" : (x > 0 ? "+" : "") + Number(x).toFixed(dp);
  const num = v => typeof v === "number" ? v : 0;
  const sum = (rs, k) => rs.reduce((a, m) => a + num(m[k]), 0);
  const mean = (rs, k) => { const v = rs.filter(m => typeof m[k] === "number"); return v.length ? sum(v, k) / v.length : null; };
  const per = (rs, k, dp) => fx(sum(rs, k) / rs.length, dp);
  const ABBR = { Fulham: "FUL", Luton: "LUT", Brighton: "BHA", Arsenal: "ARS", Leeds: "LEE", Hull: "HUL", Brentford: "BRE", Bournemouth: "BOU", Everton: "EVE", Tottenham: "TOT", Liverpool: "LIV", "Man United": "MUN", Sunderland: "SUN" };
  const LGN = { PL: "Premier League", LL: "La Liga", SA: "Serie A", BL: "Bundesliga", L1: "Ligue 1" };

  const LINES = {
    attack: [["Goals per match", rs => per(rs, "gf", 2)], ["xG per match", rs => per(rs, "xg", 2)], ["Non-penalty xG per match", rs => per(rs, "npxg", 2)],
      ["Goals minus xG (total)", rs => sg(sum(rs, "gf") - sum(rs, "xg"), 1)], ["Shots per match", rs => per(rs, "sh", 1)], ["Shots on target per match", rs => per(rs, "sot", 1)],
      ["xG per shot", rs => fx(sum(rs, "xg") / sum(rs, "sh"), 3)], ["Big chances per match", rs => per(rs, "bc", 1)], ["Touches in opposition box per match", rs => per(rs, "box", 1)]],
    defence: [["Goals conceded per match", rs => per(rs, "ga", 2)], ["xG conceded per match", rs => per(rs, "xga", 2)], ["Shots conceded per match", rs => per(rs, "osh", 1)],
      ["Shots on target conceded per match", rs => per(rs, "osot", 1)], ["xG per shot conceded", rs => fx(sum(rs, "xga") / sum(rs, "osh"), 3)],
      ["Big chances conceded per match", rs => per(rs, "obc", 1)], ["Clean sheets", rs => `${rs.filter(m => m.ga === 0).length} of ${rs.length}`],
      ["Tackles per match", rs => per(rs, "tkl", 1)], ["Interceptions per match", rs => per(rs, "itc", 1)]],
    buildup: [["Possession % (match average)", rs => fx(mean(rs, "poss"), 1)], ["Pass accuracy % (match average)", rs => fx(mean(rs, "pacc"), 1)],
      ["Long-ball share of passes %", rs => fx(mean(rs, "lbs"), 1)], ["Long-ball accuracy %", rs => fx(mean(rs, "lba"), 1)],
      ["Goalkeeper passes played long %", rs => fx(mean(rs, "gkls"), 1)], ["Goalkeeper long-ball accuracy %", rs => fx(mean(rs, "gkla"), 1)],
      ["Final-third entries per match", rs => fx(mean(rs, "fte"), 1)], ["Line-breaking passes per match (PL only)", rs => fx(mean(rs, "lbp"), 1)]],
    pressing: [["PPDA, Understat (PL rounds 1–8 only)", rs => fx(mean(rs, "ppda"), 2)], ["Opponent PPDA against us, Understat", rs => fx(mean(rs, "oppda"), 2)],
      ["PPDA proxy, FotMob (all matches)", rs => fx(mean(rs, "ppdap"), 2)]],
    setpieces: [["Set-piece goals scored (shot-based)", rs => `${sum(rs, "spg")}`], ["Set-piece xG created", rs => fx(sum(rs, "spxg"), 2)],
      ["Set-piece goals conceded (shot-based)", rs => `${sum(rs, "ospg")}`], ["Set-piece xG conceded", rs => fx(sum(rs, "ospxg"), 2)],
      ["Corners per match", rs => per(rs, "cor", 1)], ["Fouls per match", rs => per(rs, "fo", 1)], ["Yellow cards", rs => `${sum(rs, "yc")}`], ["Red cards", rs => `${sum(rs, "rc")}`]],
  };
  window.SEASON_LINES = LINES;  // reused by exports

  /* Simple sortable table. cols: [{label, get(row)->sortable, show(row)->html, l?:left}] */
  function sortable(el, cols, rows, { sortIdx = null, asc = false, highlight = null } = {}) {
    const st = { i: sortIdx, asc };
    function draw() {
      const rs = [...rows];
      if (st.i != null) rs.sort((a, b) => { const x = cols[st.i].get(a), y = cols[st.i].get(b); if (x == null) return 1; if (y == null) return -1; return (x > y ? 1 : x < y ? -1 : 0) * (st.asc ? 1 : -1); });
      el.innerHTML = `<div class="table-wrap"><table><thead><tr>${cols.map((c, i) => `<th data-i="${i}" class="${c.l ? "l" : ""} ${st.i === i ? "sorted" + (st.asc ? " asc" : "") : ""}">${esc(c.label)}</th>`).join("")}</tr></thead>
        <tbody>${rs.map(r => `<tr class="${highlight && highlight(r) ? "hl" : ""}">${cols.map(c => `<td class="${c.l ? "l" : ""}">${c.show ? c.show(r) : esc(c.get(r))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
      el.querySelectorAll("th").forEach(th => th.onclick = () => { const i = +th.dataset.i; st.asc = st.i === i ? !st.asc : !!cols[i].ascFirst; st.i = i; draw(); });
    }
    draw();
  }
  function staticTable(cols, rows, leftCols = 1) {
    return `<div class="table-wrap"><table><thead><tr>${cols.map((c, i) => `<th class="${i < leftCols ? "l" : ""}" style="cursor:default">${esc(c)}</th>`).join("")}</tr></thead>
      <tbody>${rows.map(r => `<tr>${r.map((v, i) => `<td class="${i < leftCols ? "l" : ""}">${v}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  function seg(name, opts, value) {
    return `<div class="seg" data-seg="${name}">${opts.map(([v, l]) => `<button data-v="${esc(v)}" class="${v === value ? "on" : ""}">${esc(l)}</button>`).join("")}</div>`;
  }

  window.renderSeason = function (root, D, opts = {}) {
    const charts = [];
    const mk = (id, cfg) => { const el = root.querySelector("#" + id); if (!el) return; const c = new Chart(el, cfg); charts.push(c); opts.onChart && opts.onChart(c); };
    const destroyAll = () => charts.splice(0).forEach(c => c.destroy());
    const M = D.metrics, MK = Object.fromEntries(M.map(m => [m.k, m]));
    const fmtM = (k, x) => x == null ? "n/a" : MK[k].signed ? sg(x, MK[k].dp) : Number(x).toFixed(MK[k].dp);
    const T = D.elite, CHE = T.find(t => t.n === "Chelsea");
    const better = (k, a, b) => MK[k].low ? a < b : a > b;
    const rankOf = (k, t) => 1 + T.filter(o => o.v[k] != null && better(k, o.v[k], t.v[k])).length;
    const sortedBy = k => [...T].sort((a, b) => MK[k].low ? a.v[k] - b.v[k] : b.v[k] - a.v[k]);
    const median = k => { const v = T.map(t => t.v[k]).sort((a, b) => a - b); return v[Math.floor(v.length / 2)]; };
    const S = { comp: "All", venue: "All", squad: "Usage", preset: "xG vs xGA", sx: "xg_pm", sy: "xga_pm", grp: "Results", rival: "Arsenal" };
    const toc = [["verdict", "Verdict"], ["results", "Results & form"], ["attack", "Attack"], ["defence", "Defence & goalkeeping"], ["buildup", "Possession & build-up"],
      ["pressing", "Pressing"], ["setpieces", "Set pieces & discipline"], ["squad", "Squad"], ["injuries", "Injuries"], ["scatter", "Elite: scatter"],
      ["table", "Elite: table"], ["ranks", "Where Chelsea rank"], ["radar", "Percentile radar"], ["observations", "Strengths & weaknesses"], ["notes", "Data notes"]];
    const meta = D.meta;
    root.innerHTML = `
    <div class="sa">
      <h1>${esc(D.title)}</h1>
      <p class="sub">${esc(D.summary)}</p>
      <p class="muted small">Chelsea data to ${esc(meta.last_match)} (${meta.n_matches} matches) · elite data ${esc(meta.elite_data_date)} · built ${esc(meta.generated_at)} Cairo time</p>
      <nav class="sa-toc">${toc.map(([id, l]) => `<a href="#sa-${id}" data-jump="${id}">${l}</a>`).join("")}</nav>
      <section id="sa-verdict"><h2>Verdict</h2><p>${esc(D.verdict)}</p>
        <div class="grid g4">${D.kpis.map(k => `<div class="card kpi"><div class="v ${k.tone === "bad" ? "bad" : ""}">${esc(k.value)}</div><div class="l">${esc(k.label)}</div><div class="d">${esc(k.detail || "")}</div></div>`).join("")}</div></section>
      <div class="sa-filters card"><strong>Chelsea filters</strong> ${seg("comp", [["All", "All comps"], ["PL", "Premier League"], ["EFL", "EFL Cup"]], S.comp)}
        ${seg("venue", [["All", "Home + away"], ["H", "Home"], ["A", "Away"]], S.venue)} <span class="muted small">apply to the Chelsea sections, Results to Squad</span></div>
      <div id="sa-chelsea"></div>
      <section id="sa-squad"><h2>Squad</h2>${seg("squad", [["Usage", "Usage"], ["Attack", "Attack"], ["Defence", "Defence"]], S.squad)}<div id="sa-squad-t" style="margin-top:.6rem"></div>
        <div class="grid g2" style="margin-top:1rem"><div class="card"><h3>Goal involvements (all comps)</h3><div class="chart-box"><canvas id="cGA"></canvas></div></div>
        <div class="card"><h3>Minutes by age</h3><div class="chart-box"><canvas id="cAge"></canvas></div></div></div>
        <p id="sa-squad-text"></p></section>
      <section id="sa-injuries"><h2>Injuries and absences</h2><p class="muted small">${esc(D.injuries_asof)}</p>
        <div class="card list" style="padding:0">${D.injuries.map(i => `<div class="item inj"><div><strong>${esc(i.title)}</strong><div class="muted small">${esc(i.detail)}</div></div><span class="pill st-${esc(i.status.toLowerCase())}">${esc(i.status)}</span></div>`).join("")}</div></section>
      <section id="sa-scatter"><h2>Elite comparison: scatter</h2>
        <p class="muted small">League matches only, per match. Elite = ${esc(meta.elite_rule)} (${meta.n_elite} clubs, as of ${esc(meta.elite_data_date)}).</p>
        <div class="filters">${seg("preset", Object.keys(D.presets).map(p => [p, p]), S.preset)}
          <label>X <select id="sa-sx">${M.map(m => `<option value="${m.k}">${esc(m.label)}</option>`).join("")}</select></label>
          <label>Y <select id="sa-sy">${M.map(m => `<option value="${m.k}">${esc(m.label)}</option>`).join("")}</select></label></div>
        <div class="card"><div class="chart-box tall"><canvas id="cSc"></canvas></div></div><p>${esc(D.text.scatter)}</p></section>
      <section id="sa-table"><h2>Elite comparison: table</h2><p class="muted small">Click a column header to sort. Chelsea highlighted.</p>
        ${seg("grp", Object.keys(D.groups).map(g => [g, g]), S.grp)}<div id="sa-elite-t" style="margin-top:.6rem"></div></section>
      <section id="sa-ranks"><h2>Where Chelsea rank</h2><p class="muted small">Rank among the ${meta.n_elite} elite clubs (1 = best; for conceded, fouls and cards, fewer is better).</p><div id="sa-rank-t"></div></section>
      <section id="sa-radar"><h2>Percentile radar</h2><p class="muted small">Percentile among all ${meta.n_big5} clubs in the big five leagues (100 = best; xG conceded inverted so outward is better).</p>
        <div class="filters"><label>Compare with <select id="sa-rival">${T.filter(t => t !== CHE).map(t => `<option ${t.n === S.rival ? "selected" : ""}>${esc(t.n)}</option>`).join("")}</select></label></div>
        <div class="grid g2"><div class="card"><div class="chart-box tall"><canvas id="cRad"></canvas></div></div><div id="sa-rad-t"></div></div></section>
      <section id="sa-observations"><h2>Strengths, weaknesses, observations</h2>
        <div class="grid g2"><div class="card"><h3>Strengths</h3><ul class="pros">${D.strengths.map(s => `<li>${esc(s)}</li>`).join("")}</ul></div>
        <div class="card"><h3>Weaknesses</h3><ul class="cons">${D.weaknesses.map(s => `<li>${esc(s)}</li>`).join("")}</ul></div></div>
        <ol>${D.observations.map(s => `<li>${esc(s)}</li>`).join("")}</ol>
        <div class="callout"><strong>Bottom line.</strong> ${esc(D.bottom_line)}</div></section>
      <section id="sa-notes"><h2>Data notes and sources</h2><ul>${D.notes.map(s => `<li>${esc(s)}</li>`).join("")}</ul>
        <ul>${D.sources.map(s => `<li><a href="${esc(s.href)}" target="_blank" rel="noopener">${esc(s.title)}</a>: ${esc(s.use)}</li>`).join("")}</ul></section>
    </div>`;
    root.querySelectorAll("[data-jump]").forEach(a => a.onclick = e => { e.preventDefault(); const el = root.querySelector("#sa-" + a.dataset.jump); el && el.scrollIntoView({ behavior: "smooth" }); });

    // ---------- Chelsea sections (filtered)
    function drawChelsea() {
      charts.filter(c => c.$sa === "che").forEach(c => c.destroy());
      for (let i = charts.length - 1; i >= 0; i--) if (charts[i].$sa === "che") charts.splice(i, 1);
      const rows = D.matches.filter(m => (S.comp === "All" || m.c === S.comp) && (S.venue === "All" || m.v === S.venue));
      const all = D.matches;
      const label = `${S.comp === "All" ? "All competitions" : S.comp === "PL" ? "Premier League" : "EFL Cup"}${S.venue === "All" ? "" : S.venue === "H" ? ", home" : ", away"}`;
      const w = rows.filter(m => m.r === "W").length, d = rows.filter(m => m.r === "D").length, l = rows.filter(m => m.r === "L").length, pts = 3 * w + d;
      const lt = key => staticTable(["Metric", label, "All matches"], LINES[key].map(([n, f]) => [esc(n), f(rows), f(all)]));
      const res = r => `<span class="badge ${r}">${r}</span>`;
      const gks = D.players.filter(p => p.p === "GK");
      root.querySelector("#sa-chelsea").innerHTML = `
        <section id="sa-results"><h2>Results and form</h2>
          ${staticTable(["Filter", "Played", "W-D-L", "Points (3/1/0)", "Per match", "Goals", "xG for–against"], [[esc(label), rows.length, `${w}-${d}-${l}`, pts, fx(pts / rows.length, 2), `${sum(rows, "gf")}–${sum(rows, "ga")}`, `${fx(sum(rows, "xg"), 1)}–${fx(sum(rows, "xga"), 1)}`]])}
          <div class="grid g2" style="margin-top:1rem"><div class="card"><h3>xG for and against, match by match</h3><div class="chart-box"><canvas id="cXg2"></canvas></div></div>
          <div class="card"><h3>3-match rolling xG</h3><div class="chart-box"><canvas id="cRoll"></canvas></div></div></div>
          <div style="margin-top:1rem">${staticTable(["Date", "Comp", "H/A", "Opponent", "Score", "Res", "xG", "xGA", "Shots", "Poss %"], rows.map(m => [m.d, m.c, m.v, esc(m.o), `${m.gf}–${m.ga}${m.pens ? ` (pens ${m.pens})` : ""}`, res(m.r), fx(m.xg, 2), fx(m.xga, 2), `${m.sh}–${m.osh}`, fx(m.poss, 1)]), 4)}</div>
          <p>${esc(D.text.results)}</p></section>
        <section id="sa-attack"><h2>Attack</h2>${lt("attack")}<p>${esc(D.text.attack)}</p></section>
        <section id="sa-defence"><h2>Defence and goalkeeping</h2>${lt("defence")}
          <div style="margin-top:1rem">${staticTable(["Goalkeeper", "Apps", "Mins", "Goals prevented (FotMob)", "Per 90", "Avg rating"], gks.map(p => [esc(p.n), p.ap, p.mi, sg(p.gp, 2), sg(p.gp / p.mi * 90, 2), fx(p.rt, 2)]))}</div>
          <p>${esc(D.text.defence)}</p></section>
        <section id="sa-buildup"><h2>Possession and build-up</h2>${lt("buildup")}
          <div class="card" style="margin-top:1rem"><h3>Possession and goalkeeper long-ball accuracy</h3><div class="chart-box"><canvas id="cPoss"></canvas></div></div><p>${esc(D.text.buildup)}</p></section>
        <section id="sa-pressing"><h2>Pressing</h2>${lt("pressing")}
          <div class="card" style="margin-top:1rem"><h3>Premier League PPDA, rounds 1–${meta.ppda ? meta.ppda.rounds : "?"} (lower = more aggressive press; Understat)</h3><div class="chart-box tall"><canvas id="cPpda"></canvas></div></div><p>${esc(D.text.pressing)}</p></section>
        <section id="sa-setpieces"><h2>Set pieces and discipline</h2>${lt("setpieces")}<p>${esc(D.text.setpieces)}</p></section>`;
      const labels = rows.map(m => (m.v === "A" ? "@" : "") + (ABBR[m.o] || m.o.slice(0, 3).toUpperCase()));
      const tip = { callbacks: { title: i => { const m = rows[i[0].dataIndex]; return `${m.d} ${m.v === "H" ? "v" : "at"} ${m.o} ${m.gf}–${m.ga} (${m.c})`; } } };
      const roll = k => rows.map((_, i) => { const s = rows.slice(Math.max(0, i - 2), i + 1); return +(sum(s, k) / s.length).toFixed(2); });
      const tag = c => { c.$sa = "che"; };
      [["cXg2", { type: "bar", data: { labels, datasets: [{ label: "xG for", data: rows.map(m => m.xg), backgroundColor: C.blue }, { label: "xG against", data: rows.map(m => m.xga), backgroundColor: C.red }] }, options: { plugins: { tooltip: tip } } }],
       ["cRoll", { type: "line", data: { labels, datasets: [{ label: "xG for, 3-match rolling", data: roll("xg"), borderColor: C.blue, backgroundColor: C.blue + "22", fill: true, tension: .25 }, { label: "xG against, 3-match rolling", data: roll("xga"), borderColor: C.red, tension: .25 }] }, options: { plugins: { tooltip: tip }, scales: { y: { beginAtZero: true } } } }],
       ["cPoss", { type: "line", data: { labels, datasets: [{ label: "Possession %", data: rows.map(m => m.poss), borderColor: C.blue, tension: .25 }, { label: "GK long-ball accuracy %", data: rows.map(m => m.gkla), borderColor: C.gold, tension: .25 }] }, options: { plugins: { tooltip: tip }, scales: { y: { min: 0, max: 100 } } } }],
       ["cPpda", { type: "bar", data: { labels: D.pl_ppda.map(r => r[0]), datasets: [{ label: "PPDA", data: D.pl_ppda.map(r => r[1]), backgroundColor: D.pl_ppda.map(r => r[0] === "Chelsea" ? C.blue : C.light) }] }, options: { indexAxis: "y", plugins: { legend: { display: false } } } }],
      ].forEach(([id, cfg]) => { mk(id, cfg); tag(charts[charts.length - 1]); });
    }

    // ---------- squad
    function drawSquad() {
      const P = D.players, p90 = (p, x) => p.mi ? x / p.mi * 90 : null, avail = D.matches.length * 90;
      const views = {
        Usage: { rows: P, sort: 5, cols: [{ label: "Player", l: 1, get: p => p.n }, { label: "Pos", l: 1, get: p => p.p }, { label: "Age", get: p => p.age, show: p => p.age ?? "n/a", ascFirst: 1 },
          { label: "Apps", get: p => p.ap }, { label: "Starts", get: p => p.st }, { label: "Mins", get: p => p.mi }, { label: "% of mins", get: p => p.mi / avail * 100, show: p => fx(p.mi / avail * 100, 0) }, { label: "Avg rating", get: p => p.rt, show: p => fx(p.rt, 2) }] },
        Attack: { rows: P.filter(p => p.mi >= 270 && p.p !== "GK"), sort: 7, cols: [{ label: "Player", l: 1, get: p => p.n }, { label: "Pos", l: 1, get: p => p.p }, { label: "Mins", get: p => p.mi },
          { label: "G", get: p => p.g }, { label: "A", get: p => p.a }, { label: "xG", get: p => p.xg, show: p => fx(p.xg, 2) }, { label: "xA", get: p => p.xa, show: p => fx(p.xa, 2) },
          { label: "xG+xA /90", get: p => p90(p, p.xg + p.xa), show: p => fx(p90(p, p.xg + p.xa), 2) }, { label: "Key passes", get: p => p.kp }] },
        Defence: { rows: P.filter(p => p.mi >= 270 && p.p !== "GK"), sort: 8, cols: [{ label: "Player", l: 1, get: p => p.n }, { label: "Pos", l: 1, get: p => p.p }, { label: "Mins", get: p => p.mi },
          { label: "Tackles", get: p => p.tkl }, { label: "Interceptions", get: p => p.itc }, { label: "Clearances", get: p => p.clr }, { label: "Recoveries", get: p => p.rec },
          { label: "Duels won %", get: p => p.dw / Math.max(1, p.dw + p.dl) * 100, show: p => fx(p.dw / Math.max(1, p.dw + p.dl) * 100, 0) }, { label: "Tkl+Int /90", get: p => p90(p, p.tkl + p.itc), show: p => fx(p90(p, p.tkl + p.itc), 2) }] },
      };
      const v = views[S.squad];
      sortable(root.querySelector("#sa-squad-t"), v.cols, v.rows, { sortIdx: v.sort });
    }
    function squadCharts() {
      const P = D.players;
      const ga = P.filter(p => p.g + p.a > 0).sort((a, b) => b.g + b.a - (a.g + a.a)).slice(0, 8);
      mk("cGA", { type: "bar", data: { labels: ga.map(p => p.n), datasets: [{ label: "Goals", data: ga.map(p => p.g), backgroundColor: C.blue }, { label: "Assists", data: ga.map(p => p.a), backgroundColor: C.gold }] }, options: { indexAxis: "y", scales: { x: { stacked: true }, y: { stacked: true } } } });
      const bands = [["Under 21", a => a < 21], ["21–25", a => a >= 21 && a <= 25], ["26–29", a => a >= 26 && a <= 29], ["30 and over", a => a >= 30]];
      const aged = P.filter(p => p.age != null);
      mk("cAge", { type: "doughnut", data: { labels: bands.map(b => b[0]), datasets: [{ data: bands.map(b => sum(aged.filter(p => b[1](p.age)), "mi")), backgroundColor: [C.cyan, C.blue, C.gold, C.grey] }] }, options: { plugins: { tooltip: { callbacks: { label: i => `${i.label}: ${i.raw} mins` } } } } });
      const wAge = aged.reduce((a, p) => a + p.age * p.mi, 0) / sum(aged, "mi");
      root.querySelector("#sa-squad-text").textContent = D.text.squad.replace(/^(\d+ players have been used), and/, `$1. The minutes-weighted average age is ${wAge.toFixed(1)}, and`);
    }

    // ---------- elite
    let scatter = null;
    const labelPlugin = { id: "saLabels", afterDatasetsDraw(chart) { const ctx = chart.ctx; ctx.save(); ctx.font = "11px system-ui, sans-serif"; ctx.fillStyle = "#44536a";
      chart.data.datasets.forEach((ds, di) => chart.getDatasetMeta(di).data.forEach((pt, i) => { const r = ds.data[i]; ctx.fillStyle = r.label === "Chelsea" ? C.blue : "#5b6880"; ctx.font = (r.label === "Chelsea" ? "bold 12px" : "11px") + " system-ui, sans-serif"; ctx.fillText(r.label, pt.x + 7, pt.y - 6); })); ctx.restore(); } };
    function drawScatter() {
      root.querySelector("#sa-sx").value = S.sx; root.querySelector("#sa-sy").value = S.sy;
      if (scatter) { scatter.destroy(); charts.splice(charts.indexOf(scatter), 1); }
      const pts = f => T.filter(f).map(t => ({ x: t.v[S.sx], y: t.v[S.sy], label: t.n, lg: LGN[t.lg] }));
      mk("cSc", { type: "scatter", plugins: [labelPlugin], data: { datasets: [
        { label: "Chelsea", data: pts(t => t === CHE), backgroundColor: C.blue, pointRadius: 9 },
        { label: "Premier League elite", data: pts(t => t !== CHE && t.lg === "PL"), backgroundColor: C.gold, pointRadius: 6 },
        { label: "Other big-five elite", data: pts(t => t.lg !== "PL"), backgroundColor: C.cyan, pointRadius: 6 }] },
        options: { layout: { padding: { right: 70, top: 14 } }, scales: { x: { grace: "4%", title: { display: true, text: MK[S.sx].label } }, y: { grace: "6%", title: { display: true, text: MK[S.sy].label } } },
          plugins: { tooltip: { callbacks: { label: i => `${i.raw.label} (${i.raw.lg}): ${fmtM(S.sx, i.raw.x)}, ${fmtM(S.sy, i.raw.y)}` } } } } });
      scatter = charts[charts.length - 1];
    }
    function drawEliteTable() {
      const keys = D.groups[S.grp];
      const cols = [{ label: "Team", l: 1, get: t => t.n }, { label: "League", l: 1, get: t => LGN[t.lg] }, { label: "Pld", get: t => t.mp }, { label: "Pts", get: t => t.pts }]
        .concat(keys.map(k => ({ label: MK[k].short, get: t => t.v[k] == null ? null : (MK[k].low ? -t.v[k] : t.v[k]), show: t => fmtM(k, t.v[k]) })));
      sortable(root.querySelector("#sa-elite-t"), cols, T, { sortIdx: 4, highlight: t => t === CHE });
    }
    function drawRanks() {
      const rows = M.map(m => { const r = rankOf(m.k, CHE), b = sortedBy(m.k)[0];
        return [esc(m.label), fmtM(m.k, CHE.v[m.k]), `<span class="${r <= 4 ? "good" : r >= T.length - 3 ? "bad" : ""}">${r} / ${T.length}</span>`, fmtM(m.k, median(m.k)), `${esc(b.n)} (${fmtM(m.k, b.v[m.k])})`]; });
      root.querySelector("#sa-rank-t").innerHTML = staticTable(["Metric", "Chelsea", "Rank", "Elite median", "Best"], rows);
    }
    let radar = null;
    function drawRadar() {
      if (radar) { radar.destroy(); charts.splice(charts.indexOf(radar), 1); }
      const R = T.find(t => t.n === S.rival), keys = Object.keys(D.radar);
      mk("cRad", { type: "radar", data: { labels: keys.map(k => D.radar[k]), datasets: [
        { label: "Chelsea", data: keys.map(k => CHE.pct[k]), borderColor: C.blue, backgroundColor: C.blue + "33", pointRadius: 3 },
        { label: R.n, data: keys.map(k => R.pct[k]), borderColor: C.gold, backgroundColor: C.gold + "33", pointRadius: 3 }] },
        options: { scales: { r: { min: 0, max: 100, ticks: { stepSize: 25 } } } } });
      radar = charts[charts.length - 1];
      root.querySelector("#sa-rad-t").innerHTML = staticTable(["Axis", "Chelsea", R.n], keys.map(k => [esc(D.radar[k]), CHE.pct[k], R.pct[k]]));
    }

    // ---------- wiring
    root.querySelectorAll("[data-seg]").forEach(g => g.querySelectorAll("button").forEach(b => b.onclick = () => {
      g.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
      const name = g.dataset.seg, v = b.dataset.v; S[name] = v;
      if (name === "comp" || name === "venue") drawChelsea();
      else if (name === "squad") drawSquad();
      else if (name === "preset") { [S.sx, S.sy] = D.presets[v]; drawScatter(); }
      else if (name === "grp") drawEliteTable();
    }));
    root.querySelector("#sa-sx").onchange = e => { S.sx = e.target.value; root.querySelectorAll('[data-seg="preset"] button').forEach(x => x.classList.remove("on")); drawScatter(); };
    root.querySelector("#sa-sy").onchange = e => { S.sy = e.target.value; root.querySelectorAll('[data-seg="preset"] button').forEach(x => x.classList.remove("on")); drawScatter(); };
    root.querySelector("#sa-rival").onchange = e => { S.rival = e.target.value; drawRadar(); };
    drawChelsea(); drawSquad(); squadCharts(); drawScatter(); drawEliteTable(); drawRanks(); drawRadar();
    return { destroy: destroyAll };
  };
})();
