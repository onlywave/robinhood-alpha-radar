/* Robinhood Chain Alpha Radar — rendering dashboard (vanilla JS, nessuna dipendenza) */
"use strict";

const fmtUSD = (v, compact = true) => {
  if (v === null || v === undefined || isNaN(v)) return "N/D";
  return new Intl.NumberFormat("it-CH", {
    style: "currency", currency: "USD",
    notation: compact ? "compact" : "standard", maximumFractionDigits: compact ? 1 : 0,
  }).format(v);
};
const fmtN = (v) => (v === null || v === undefined || isNaN(v)) ? "N/D"
  : new Intl.NumberFormat("it-CH", { notation: "compact", maximumFractionDigits: 1 }).format(v);
const fmtPct = (v, digits = 1) => (v === null || v === undefined || isNaN(v)) ? "N/D"
  : `${v > 0 ? "+" : ""}${Number(v).toFixed(digits)}%`;
const fmtAge = (h) => {
  if (h === null || h === undefined) return "N/D";
  if (h < 48) return `${Math.round(h)}h`;
  return `${(h / 24).toFixed(1)}g`;
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const CLASS_BADGE = {
  "HIGH-PRIORITY WATCH": ["hpw", "HIGH-PRIORITY WATCH"],
  "WATCHLIST": ["watch", "WATCHLIST"],
  "WATCHLIST / BENCHMARK": ["watch", "WATCHLIST / BENCHMARK"],
  "ECOSYSTEM WATCH": ["eco", "ECOSYSTEM WATCH"],
  "INFRASTRUCTURE WATCH": ["eco", "INFRASTRUCTURE WATCH"],
  "DISCOVERY": ["disc", "DISCOVERY"],
  "AVOID": ["avoid", "AVOID"],
};
const badge = (cls) => {
  const [c, label] = CLASS_BADGE[cls] || ["disc", cls];
  return `<span class="badge ${c}">${esc(label)}</span>`;
};

function sparkline(points, color, label, fmt) {
  const vals = points.filter((p) => p.v !== null && p.v !== undefined && !isNaN(p.v));
  if (vals.length < 2) return `<div><div class="spark-label">${esc(label)}</div><span class="empty">storico insufficiente (servono ≥2 scansioni)</span></div>`;
  const w = 420, h = 64, pad = 3;
  const min = Math.min(...vals.map((p) => p.v)), max = Math.max(...vals.map((p) => p.v));
  const span = max - min || 1;
  const pts = vals.map((p, i) => {
    const x = pad + (i / (vals.length - 1)) * (w - 2 * pad);
    const y = h - pad - ((p.v - min) / span) * (h - 2 * pad);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const last = vals[vals.length - 1].v;
  return `<div><div class="spark-label">${esc(label)} — ultimo: ${fmt(last)} (min ${fmt(min)} · max ${fmt(max)})</div>
    <svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none">
      <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2"/>
    </svg></div>`;
}

function renderStatus(d) {
  const cs = d.chain_status;
  const el = document.getElementById("status-cards");
  const cards = [
    ["TVL Robinhood Chain", fmtUSD(cs.tvl_usd), "fact"],
    ["Volume DEX 24h", fmtUSD(cs.dex_vol_24h), "fact"],
    ["Volume DEX 7g", fmtUSD(cs.dex_vol_7d), "fact"],
    ["Candidati monitorati", String(d.candidates.length), "inf"],
    ["HIGH-PRIORITY WATCH", String(d.n_hpw), "inf"],
    ["Flow score chain (proxy)", d.bridge_flow_score === null ? "N/D" : `${d.bridge_flow_score}/100`, "est"],
  ];
  el.innerHTML = cards.map(([k, v, t]) =>
    `<div class="card"><div class="k">${k} <span class="tag ${t}">${t === "fact" ? "fatto" : t === "est" ? "stima" : "inferenza"}</span></div><div class="v">${v}</div></div>`).join("");

  document.getElementById("tvl-protocols").innerHTML =
    (cs.top_protocols_tvl || []).map((p) =>
      `<tr><td>${esc(p.name)} <span class="cov">${esc(p.category || "")}</span></td><td class="num">${fmtUSD(p.tvl)}</td></tr>`).join("")
    || `<tr><td class="empty">dato non disponibile</td></tr>`;
  document.getElementById("dex-protocols").innerHTML =
    (cs.dex_protocols || []).map((p) =>
      `<tr><td>${esc(p.name)}</td><td class="num">${fmtUSD(p.vol_24h)}</td></tr>`).join("")
    || `<tr><td class="empty">dato non disponibile</td></tr>`;
}

function renderCandidates(d) {
  const tb = document.querySelector("#cand-table tbody");
  if (!d.candidates.length) {
    tb.innerHTML = `<tr><td colspan="11" class="empty">Nessun candidato supera lo screening minimo in questa scansione.</td></tr>`;
    return;
  }
  tb.innerHTML = d.candidates.map((c) => {
    const link = c.ds_url || `https://www.geckoterminal.com/robinhood/pools/${c.pool_address}`;
    const socials = (c.socials || []).map((s) =>
      `<a href="${esc(s.url)}" target="_blank" rel="noopener">${s.type === "twitter" ? "𝕏" : esc(s.type)}</a>`).join("")
      + (c.websites || []).slice(0, 1).map((w) => `<a href="${esc(w)}" target="_blank" rel="noopener">🌐</a>`).join("");
    const flags = (c.red_flags || []).map((f) => `<span class="flag" title="${esc(f)}">⚠ ${esc(f)}</span>`).join("");
    const chg = c.chg_h24;
    return `<tr>
      <td>${badge(c.classification)}${c.ultra_early ? ' <span class="tag est" title="età < 72h">ultra-early</span>' : ""}</td>
      <td class="tok"><a href="${esc(link)}" target="_blank" rel="noopener">${esc(c.token_symbol || "?")}</a>
        <span class="name">${esc(c.token_name || "")} · ${esc(c.quote_symbol || "")}</span></td>
      <td class="num">${fmtAge(c.age_hours)}</td>
      <td class="num">${fmtUSD(c.liquidity_usd)}</td>
      <td class="num">${fmtUSD(c.vol_h24)}</td>
      <td class="num">${c.vol_liq_ratio ?? "N/D"}</td>
      <td class="num">${fmtN(c.buys_h24 + c.sells_h24)}</td>
      <td class="num">${(c.buy_ratio * 100).toFixed(0)}%</td>
      <td class="num ${chg > 0 ? "up" : chg < 0 ? "down" : ""}">${fmtPct(chg)}</td>
      <td><div class="score-bar"><div class="bar"><div class="fill" style="width:${Math.min(100, c.score_partial)}%"></div></div>
        <span>${c.score_partial}</span></div>
        <span class="cov">copertura ${c.score_coverage_pct}%</span></td>
      <td>${flags}<span class="socials">${socials}</span></td>
    </tr>`;
  }).join("");
}

function renderWatchlist(d) {
  const el = document.getElementById("watch-cards");
  el.innerHTML = d.watchlist.map((w) => {
    const p = w.pair;
    let body;
    if (p) {
      body = `<div class="metrics">
        <span class="k">Prezzo</span><span>${p.price_usd ? "$" + esc(p.price_usd) : "N/D"}</span>
        <span class="k">Market cap</span><span>${fmtUSD(p.mcap)}</span>
        <span class="k">Liquidità</span><span>${fmtUSD(p.liquidity_usd)}</span>
        <span class="k">Volume 24h</span><span>${fmtUSD(p.vol_h24)}</span>
        <span class="k">Txns 24h</span><span>${fmtN(p.txns_h24)}</span>
        <span class="k">Δ 24h</span><span class="${p.chg_h24 > 0 ? "up" : "down"}">${fmtPct(Number(p.chg_h24))}</span>
      </div>
      <a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.symbol)} su DexScreener ↗</a>`;
    } else {
      body = `<p class="empty">${esc(w.no_pair_reason || "nessuna coppia negoziabile individuata")}</p>`;
    }
    const warn = w.warning ? `<div class="warn-box">⚠ ${esc(w.warning)}</div>` : "";
    return `<div class="watch-card">
      <h4>${esc(w.name)} ${badge(w.handoff_state)}</h4>
      ${body}${warn}
      <div class="note">${esc(w.note)}</div>
    </div>`;
  }).join("");
}

function renderDeltas(d) {
  const el = document.getElementById("delta-content");
  const dl = d.deltas || {};
  if (dl.first_run) {
    el.innerHTML = `<span class="empty">Prima scansione registrata: nessun confronto disponibile.</span>`;
    return;
  }
  const list = (items, f) => items && items.length
    ? `<ul>${items.map(f).join("")}</ul>` : `<span class="empty">nessuna</span>`;
  el.innerHTML = `<div class="delta-cols">
    <div><h4>Entrati</h4>${list(dl.entered, (x) => `<li>${esc(x.symbol)} → ${badge(x.classification)}</li>`)}</div>
    <div><h4>Usciti</h4>${list(dl.exited, (x) => `<li>${esc(x.symbol)} (era ${esc(x.was)})</li>`)}</div>
    <div><h4>Riclassificati</h4>${list(dl.reclassified, (x) => `<li>${esc(x.symbol)}: ${esc(x.from)} → ${badge(x.to)}</li>`)}</div>
  </div>`;
}

function renderGlobal(d) {
  const el = document.getElementById("global-content");
  el.innerHTML = (d.global_radar || []).map((g) => {
    const rows = (g.candidates || []).map((c) => {
      const link = c.ds_url || "#";
      return `<tr>
        <td>${badge(c.classification)}</td>
        <td class="tok">${esc(c.token_symbol || "?")} <span class="name">${esc(c.token_name || "")}</span></td>
        <td class="num">${fmtAge(c.age_hours)}</td>
        <td class="num">${fmtUSD(c.liquidity_usd)}</td>
        <td class="num">${fmtUSD(c.vol_h24)}</td>
        <td class="num">${fmtN(c.buys_h24 + c.sells_h24)}</td>
        <td>${(c.red_flags || []).map((f) => `<span class="flag">⚠ ${esc(f)}</span>`).join("")}</td>
      </tr>`;
    }).join("");
    return `<div class="net-block panel">
      <div class="net-head"><h3>${esc(g.network)}</h3>
        <span class="n">${g.new_pools_seen} nuovi pool osservati · ${g.candidates.length} oltre screening</span></div>
      ${rows ? `<table><thead><tr><th>Classe</th><th>Token</th><th>Età</th><th>Liq</th><th>Vol 24h</th><th>Txns</th><th>Note</th></tr></thead><tbody>${rows}</tbody></table>`
             : `<span class="empty">nessun candidato oltre screening in questa scansione</span>`}
    </div>`;
  }).join("");
}

function renderWeights() {
  const weights = [
    ["Smart Money", 25, "nd"], ["Team Proximity", 20, "nd"], ["Liquidity", 15, "est"],
    ["Holder Growth", 10, "nd"], ["Deployer", 10, "nd"], ["Social Velocity", 10, "est"],
    ["GitHub / Developer", 5, "nd"], ["Bridge / Flow", 5, "est"],
  ];
  document.getElementById("weights-table").innerHTML =
    `<tr><th>Componente</th><th>Peso</th><th>Automazione</th></tr>` +
    weights.map(([n, w, t]) =>
      `<tr><td>${n}</td><td class="num">${w}%</td><td><span class="tag ${t}">${t === "nd" ? "N/D — manuale" : "parziale"}</span></td></tr>`).join("");
}

async function main() {
  let d;
  try {
    const r = await fetch(`data/latest.json?cb=${Date.now()}`);
    d = await r.json();
  } catch (e) {
    document.getElementById("generated-at").textContent =
      "ERRORE: dati non disponibili (data/latest.json mancante)";
    return;
  }
  document.getElementById("op-state").textContent = d.operational_state;
  if (d.operational_state !== "NO TRADE") document.getElementById("op-state").classList.add("alert");
  document.getElementById("op-note").textContent = d.operational_note;
  document.getElementById("generated-at").textContent = `ultimo aggiornamento: ${d.generated_at_local}`;

  renderStatus(d);
  renderCandidates(d);
  renderWatchlist(d);
  renderDeltas(d);
  renderGlobal(d);
  renderWeights();

  try {
    const h = await (await fetch(`data/history.json?cb=${Date.now()}`)).json();
    document.getElementById("sparklines").innerHTML =
      sparkline(h.map((p) => ({ v: p.tvl })), "#33d17a", "TVL", fmtUSD) +
      sparkline(h.map((p) => ({ v: p.dex_vol_24h })), "#62a0ea", "Volume DEX 24h", fmtUSD);
  } catch (e) { /* storico opzionale */ }
}

main();
