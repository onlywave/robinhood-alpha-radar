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
  "ALPHA BUY ALERT": ["buy", "🚨 ALPHA BUY ALERT"],
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

const MIN_POSITION_USD = 10;
const CAP_KEY = "alpha_radar_capitale_disponibile_usd";

function renderSummary(d) {
  const el = document.getElementById("summary-content");
  const buys = (d.candidates || []).filter((c) => c.classification === "ALPHA BUY ALERT");
  const noTrade = buys.length === 0;
  const w = (d.wallets || [])[0];
  const cap = getCapital();

  // prossimo aggiornamento: la scansione parte al minuto 17 di ogni ora (~+3' di deploy)
  const next = new Date();
  next.setMinutes(20, 0, 0);
  if (new Date().getMinutes() >= 17) next.setHours(next.getHours() + 1);
  const nextStr = next.toLocaleTimeString("it-CH", { hour: "2-digit", minute: "2-digit" });

  const verdict = noTrade
    ? `<div class="verdict notrade">⏸ Adesso: <strong>non comprare nulla</strong></div>
       <p>Nessun token supera oggi tutti i controlli di qualità e sicurezza.
       È normale: la maggior parte dei token nuovi è spazzatura o truffa, e il sistema è
       fatto per scartarli. La mossa giusta è <strong>aspettare</strong> e tenere il capitale liquido.</p>`
    : `<div class="verdict buysig">🚨 Adesso: <strong>${buys.length === 1
         ? "1 segnale d'acquisto attivo" : buys.length + " segnali d'acquisto attivi"}
       — ${buys.map((b) => esc(b.token_symbol)).join(", ")}</strong></div>
       <p>${buys.length === 1 ? "Un token ha" : "Alcuni token hanno"} superato tutti i controlli
       automatici (qualità, sicurezza del contratto, distribuzione, vendibilità).
       <strong>Non è un ordine di acquisto:</strong> scorri alla scheda verde qui sotto,
       leggi i dati, esegui la verifica finale indicata e decidi tu.
       Investi solo ciò che puoi permetterti di perdere del tutto.</p>`;

  el.innerHTML = `<div class="panel hero ${noTrade ? "" : "hero-buy"}">
    <div class="hero-left">
      ${verdict}
      <div class="howto">
        <strong>Come usare questa pagina in 30 secondi</strong>
        <ol>
          <li>Guarda il riquadro qui sopra: dice se oggi c'è qualcosa da fare oppure no.</li>
          <li>Se dice "non comprare nulla" → hai finito, torna più tardi (si aggiorna da sola ogni ora).</li>
          <li>Se c'è un segnale 🚨 → leggi la scheda verde, esegui la verifica finale e decidi con calma.</li>
          <li>Le sezioni sotto mostrano il tuo portafoglio, i token osservati e perché (non) sono segnali.</li>
        </ol>
      </div>
    </div>
    <div class="hero-right">
      <div class="mini"><span class="k">Il tuo portafoglio on-chain</span>
        <span class="v">${w && w.total_value_usd !== null ? fmtUSD(w.total_value_usd, false) : "N/D"}</span></div>
      <div class="mini"><span class="k">Capitale pronto (lo imposti tu)</span>
        <span class="v">${cap !== null ? fmtUSD(cap, false) : "da impostare ↓"}</span></div>
      <div class="mini"><span class="k">Segnali d'acquisto attivi</span>
        <span class="v ${noTrade ? "" : "up"}">${buys.length}</span></div>
      <div class="mini"><span class="k">Token in osservazione</span>
        <span class="v">${(d.candidates || []).length}</span></div>
      <div class="mini"><span class="k">Prossimo aggiornamento</span>
        <span class="v">~${nextStr}</span></div>
    </div>
  </div>`;
}

function renderBuyAlerts(d) {
  const el = document.getElementById("buy-content");
  const buys = (d.candidates || []).filter((c) => c.classification === "ALPHA BUY ALERT");
  if (!buys.length) {
    el.innerHTML = `<div class="panel"><span class="empty">Nessun BUY ALERT attivo in questa
      scansione — stato <strong>NO TRADE</strong>. I gate richiesti (score ≥85, copertura ≥60%,
      contratto verificato, owner rinunciato, top-10 ≤30%, sellability empirica) non sono tutti
      soddisfatti da alcun candidato: il dettaglio di cosa manca è nella tabella candidati.</span></div>`;
    return;
  }
  el.innerHTML = buys.map((c) => {
    const oc = c.onchain || {};
    const link = c.ds_url || `https://www.geckoterminal.com/robinhood/pools/${c.pool_address}`;
    return `<div class="panel buy-panel">
      <h3>🚨 ${esc(c.token_symbol)} <span class="name">${esc(c.token_name || "")}</span>
        — score ${c.score_norm}/100 (copertura ${c.score_coverage_pct}%)</h3>
      <div class="cards">
        <div class="card"><div class="k">Contract <span class="tag fact">verificato</span></div>
          <div class="d mono-sm">${esc(c.token_address)}</div></div>
        <div class="card"><div class="k">Mercato</div>
          <div class="d">liq ${fmtUSD(c.liquidity_usd)} · vol24 ${fmtUSD(c.vol_h24)} ·
          ${fmtN(c.buys_h24 + c.sells_h24)} txns · buy ${(c.buy_ratio * 100).toFixed(0)}% ·
          età ${fmtAge(c.age_hours)}</div></div>
        <div class="card"><div class="k">Distribuzione</div>
          <div class="d">${fmtN(oc.holders_count)} holder
          ${oc.holders_growth_pct_1h !== null && oc.holders_growth_pct_1h !== undefined ? `(${fmtPct(oc.holders_growth_pct_1h, 2)}/h)` : ""} ·
          top-10 adj ${oc.top10_adjusted_pct ?? "N/D"}% ·
          deployer ${oc.creator_share_pct !== null && oc.creator_share_pct !== undefined ? oc.creator_share_pct + "%" : "fuori top-50 (<1%)"}</div></div>
        <div class="card"><div class="k">Sicurezza</div>
          <div class="d">owner: ${esc(oc.owner_status || "N/D")} ·
          contratto ${oc.contract_verified ? "verificato ✓" : "NON verificato"} ·
          ${c.sells_h24} vendite reali/24h</div></div>
      </div>
      ${(c.cautions || []).map((x) => `<div class="warn-box">⚠ ${esc(x)}</div>`).join("")}
      <div class="warn-box">🔬 <strong>Verifica finale obbligatoria prima di agire:</strong>
        <code>python3 scripts/verifica_finale.py ${esc(c.token_address)}</code> —
        controlla slippage, proxy, distribuzione, venditori distinti on-chain e GoPlus.
        Restano manuali: LP lock, bundle/sniper, team. Segnale automatico fallibile,
        non consulenza; rischio di perdita totale presente. Size prudenziale e
        invalidazione definita PRIMA dell'ingresso.</div>
      <a href="${esc(link)}" target="_blank" rel="noopener">grafico e pool ↗</a>
    </div>`;
  }).join("");
}

function getCapital() {
  const v = parseFloat(localStorage.getItem(CAP_KEY));
  return isNaN(v) ? null : v;
}

function renderWallets(d) {
  const el = document.getElementById("wallet-content");
  if (!d.wallets || !d.wallets.length) {
    el.innerHTML = `<p class="empty">Nessun wallet configurato.</p>`;
    return;
  }
  el.innerHTML = d.wallets.map((w, wi) => {
    const cap = getCapital();
    const total = w.total_value_usd;
    const power = (total !== null && cap !== null) ? total + cap : null;
    const shown = w.positions.filter((p) => p.value_usd !== null && p.value_usd >= MIN_POSITION_USD);
    const hidden = w.positions.length - shown.length;
    const nativeRow = (w.native_eth !== null && w.native_eth > 0)
      ? `<tr><td class="tok">ETH <span class="name">nativo</span></td>
           <td class="num">${w.native_eth.toFixed(6)}</td>
           <td class="num">${fmtUSD(w.eth_price_usd)}</td>
           <td class="num">${fmtUSD(w.native_eth * (w.eth_price_usd || 0))}</td>
           <td></td><td><span class="tag fact">fatto</span></td></tr>` : "";
    const posRows = shown.map((p) => {
      return `<tr>
        <td class="tok"><a href="${esc(p.explorer_url)}" target="_blank" rel="noopener">${esc(p.symbol)}</a>
          <span class="name">${esc(p.name || "")}</span></td>
        <td class="num">${new Intl.NumberFormat("it-CH", { maximumFractionDigits: 4 }).format(p.qty)}</td>
        <td class="num">${p.price_usd !== null ? "$" + p.price_usd.toPrecision(4) : "N/D"}</td>
        <td class="num">${p.value_usd !== null ? fmtUSD(p.value_usd, false) : "N/D"}</td>
        <td class="num">${p.alloc_pct !== null && p.alloc_pct !== undefined
          ? `<div class="score-bar"><div class="bar"><div class="fill" style="width:${p.alloc_pct}%"></div></div><span>${p.alloc_pct}%</span></div>` : ""}</td>
        <td><span class="tag ${p.price_source ? "est" : "nd"}">${p.price_source || "N/D"}</span>
          ${p.price_warning ? `<span class="flag" title="${esc(p.price_warning)}">⚠ liq. esigua</span>` : ""}</td>
      </tr>`;
    }).join("");
    // operazioni: solo quelle rilevanti (>$10), tenendo intere le coppie swap
    const txMax = {};
    (w.operations || []).forEach((o) => {
      txMax[o.tx_hash] = Math.max(txMax[o.tx_hash] || 0, o.value_usd_now || 0);
    });
    const opsShown = (w.operations || []).filter((o) => (txMax[o.tx_hash] || 0) >= MIN_POSITION_USD);
    const opsHidden = (w.operations || []).length - opsShown.length;
    const opRows = opsShown.map((o) => `<tr>
      <td class="num">${esc(o.ts_local)}</td>
      <td><span class="badge ${o.direction === "IN" ? "hpw" : "avoid"}">${o.direction}</span>
        ${o.is_swap ? '<span class="tag inf">swap</span>' : ""}</td>
      <td class="tok">${esc(o.symbol)}</td>
      <td class="num">${new Intl.NumberFormat("it-CH", { maximumFractionDigits: 4 }).format(o.qty)}</td>
      <td class="num">${o.value_usd_now !== null ? fmtUSD(o.value_usd_now, false) : "N/D"}</td>
      <td class="num"><a href="${esc(o.tx_url)}" target="_blank" rel="noopener" class="mono">${esc((o.counterparty || "").slice(0, 10))}… ↗</a></td>
    </tr>`).join("");
    const errs = (w.source_errors || []).length
      ? `<div class="warn-box">⚠ Fonti parzialmente indisponibili in questa scansione: ${w.source_errors.join(", ")} — riprova automatica alla prossima ora.</div>` : "";
    return `<div class="panel">
      <h3>${esc(w.label)} · <a href="${esc(w.explorer_url)}" target="_blank" rel="noopener" class="mono">${esc(w.address.slice(0, 8))}…${esc(w.address.slice(-6))} ↗</a>
        ${w.account_type ? `<span class="tag inf" title="smart account">${esc(w.account_type)}</span>` : ""}</h3>
      ${errs}
      <div class="cards">
        <div class="card"><div class="k">Valore posizioni on-chain <span class="tag est">stima</span></div>
          <div class="v">${total !== null ? fmtUSD(total, false) : "N/D"}</div>
          <div class="d">${shown.length} posizioni rilevanti${hidden ? ` · ${hidden} sotto $${MIN_POSITION_USD} o senza prezzo (non mostrate)` : ""}</div></div>
        <div class="card capital-card"><div class="k">Capitale pronto da investire</div>
          <div class="v"><input id="cap-input-${wi}" type="number" min="0" step="100"
            placeholder="es. 10000" value="${cap !== null ? cap : ""}"> USD</div>
          <div class="d"><button id="cap-save-${wi}">Salva</button>
            <span class="cov">solo nel tuo browser (localStorage), non pubblicato</span></div></div>
        <div class="card"><div class="k">Capitale operativo totale <span class="tag inf">inferenza</span></div>
          <div class="v" id="power-${wi}">${power !== null ? fmtUSD(power, false) : "imposta il capitale →"}</div>
          <div class="d">posizioni + capitale disponibile</div></div>
      </div>
      <h3 style="margin-top:16px">Posizioni attuali <span class="tag fact">saldi on-chain</span></h3>
      <div class="table-wrap"><table>
        <thead><tr><th>Asset</th><th>Quantità</th><th>Prezzo</th><th>Valore</th><th>Allocazione</th><th>Fonte prezzo</th></tr></thead>
        <tbody>${nativeRow}${posRows || `<tr><td colspan="6" class="empty">nessuna posizione sopra $${MIN_POSITION_USD}</td></tr>`}</tbody>
      </table></div>
      ${(w.position_assessments || []).length ? `
      <h3 style="margin-top:16px">Valutazione delle posizioni
        <span class="tag inf">stessi criteri dello screening, ricontrollati ogni ora</span></h3>
      ${w.position_assessments.map((a) => `<div class="assess ${a.classification === "AVOID" ? "assess-bad" : ""}">
        <div class="assess-head">${badge(a.classification)}
          <strong>${esc(a.symbol)}</strong>
          <span class="cov">${a.value_usd !== undefined ? fmtUSD(a.value_usd, false) : ""}</span>
          ${a.score_norm !== undefined && a.score_norm !== null
            ? `<span class="cov">score ${a.score_norm}/100 (copertura ${a.coverage_pct}%)</span>` : ""}
          ${a.holders_count ? `<span class="cov">${fmtN(a.holders_count)} holder · top-10 ${a.top10_adjusted_pct ?? "N/D"}% ·
            ${a.contract_verified === true ? "contratto ✓" : a.contract_verified === false ? "contratto NON verificato" : "verifica N/D"} ·
            owner ${esc(a.owner_status || "N/D")}</span>` : ""}
        </div>
        <p class="assess-comment">${esc(a.comment)}</p>
      </div>`).join("")}` : ""}
      <h3 style="margin-top:16px">Operazioni recenti <span class="tag fact">eventi Transfer on-chain</span></h3>
      <div class="table-wrap"><table>
        <thead><tr><th>Data (Zurich)</th><th>Dir</th><th>Asset</th><th>Quantità</th><th>Valore attuale</th><th>Controparte / tx</th></tr></thead>
        <tbody>${opRows || '<tr><td colspan="6" class="empty">nessuna operazione rilevante (o dati non disponibili in questa scansione)</td></tr>'}</tbody>
      </table></div>
      ${opsHidden ? `<p class="cov" style="margin:6px 0 0">${opsHidden} operazioni minori (airdrop/dust sotto $${MIN_POSITION_USD}) non mostrate.</p>` : ""}
    </div>`;
  }).join("");

  d.wallets.forEach((w, wi) => {
    const btn = document.getElementById(`cap-save-${wi}`);
    if (!btn) return;
    btn.addEventListener("click", () => {
      const v = parseFloat(document.getElementById(`cap-input-${wi}`).value);
      if (isNaN(v) || v < 0) { localStorage.removeItem(CAP_KEY); }
      else { localStorage.setItem(CAP_KEY, String(v)); }
      renderWallets(d);  // ridisegna con il nuovo capitale
      renderSummary(d);  // aggiorna anche il riquadro in sintesi
    });
  });
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
    const flags = (c.red_flags || []).map((f) => `<span class="flag" title="${esc(f)}">⚠ ${esc(f)}</span>`).join("")
      + (c.cautions || []).map((f) => `<span class="caution" title="${esc(f)}">△ ${esc(f.split(" (")[0])}</span>`).join("");
    const missing = (c.buy_missing || []);
    const missingHtml = c.classification !== "ALPHA BUY ALERT" && missing.length
      ? `<span class="cov" title="${esc(missing.join("\n"))}">manca per BUY: ${missing.length} req.</span>` : "";
    const oc = c.onchain || {};
    const onchain = c.onchain
      ? `<span class="oc-line">${fmtN(oc.holders_count)} hold${oc.holders_growth_pct_1h !== null && oc.holders_growth_pct_1h !== undefined ? ` <span class="${oc.holders_growth_pct_1h >= 0 ? "up" : "down"}">${fmtPct(oc.holders_growth_pct_1h, 1)}/h</span>` : ""}</span>
         <span class="oc-line">top10 ${oc.top10_adjusted_pct ?? "N/D"}%</span>
         <span class="oc-line">${oc.contract_verified === true ? "✓ verif." : oc.contract_verified === false ? "✗ non verif." : "verif. N/D"} · ${oc.owner_status ? (oc.owner_status.startsWith("attivo") ? "owner attivo" : "owner " + esc(oc.owner_status)) : "owner N/D"}</span>`
      : `<span class="cov">non arricchito</span>`;
    const score = c.score_norm ?? c.score_partial;
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
      <td class="oc-cell">${onchain}</td>
      <td><div class="score-bar"><div class="bar"><div class="fill" style="width:${Math.min(100, score)}%"></div></div>
        <span>${score}</span></div>
        <span class="cov">copertura ${c.score_coverage_pct}%</span></td>
      <td>${flags}${missingHtml}<span class="socials">${socials}</span></td>
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

const fmtPx = (v) => (v === null || v === undefined) ? "N/D"
  : "$" + Number(v).toPrecision(4);

function signalRow(s) {
  const chg = s.change_pct;
  return `<tr>
    <td class="num">${esc(s.first_seen_local || (s.first_seen_utc || "").slice(0, 16))}</td>
    <td class="tok"><a href="${esc(s.ds_url || "#")}" target="_blank" rel="noopener">${esc(s.symbol)}</a></td>
    <td class="num">${s.score_at_signal ?? "N/D"}</td>
    <td class="num">${fmtPx(s.price_at_signal)}</td>
    <td class="num" data-pxnow="${esc(s.token_address)}">${fmtPx(s.price_now)}</td>
    <td class="num ${chg > 0 ? "up" : chg < 0 ? "down" : ""}" data-chg="${esc(s.token_address)}"
      data-base="${s.price_at_signal ?? ""}">${fmtPct(chg, 1)}</td>
    <td>${s.active
      ? `<span class="badge hpw">ATTIVO</span>${s.reactivations ? ` <span class="cov">riattivato ×${s.reactivations}</span>` : ""}`
      : `<span class="badge disc">cessato</span> <span class="cov">${esc((s.ended_utc || "").slice(0, 16).replace("T", " "))}</span>`}</td>
  </tr>`;
}

async function renderSignals() {
  const tb = document.querySelector("#signals-table tbody");
  let sig = [];
  try {
    sig = await (await fetch(`data/signals.json?cb=${Date.now()}`)).json();
  } catch (e) { /* registro non ancora pubblicato */ }
  if (!sig.length) {
    tb.innerHTML = `<tr><td colspan="7" class="empty">Nessun segnale registrato finora.
      Il registro parte dal primo ALPHA BUY ALERT emesso.</td></tr>`;
    return;
  }
  tb.innerHTML = sig.map(signalRow).join("");

  // aggiornamento prezzi LIVE a ogni apertura pagina (DexScreener, best-effort)
  try {
    const addrs = sig.map((s) => s.token_address);
    for (let i = 0; i < addrs.length; i += 30) {
      const chunk = addrs.slice(i, i + 30);
      const pairs = await (await fetch(
        `https://api.dexscreener.com/tokens/v1/robinhood/${chunk.join(",")}`)).json();
      const best = {};
      for (const p of pairs || []) {
        const ta = (p.baseToken?.address || "").toLowerCase();
        const liq = p.liquidity?.usd || 0;
        if (ta && (!best[ta] || liq > best[ta].liq)) best[ta] = { liq, px: parseFloat(p.priceUsd) };
      }
      for (const [ta, v] of Object.entries(best)) {
        if (!v.px) continue;
        const pxCell = document.querySelector(`[data-pxnow="${ta}"]`);
        const chgCell = document.querySelector(`[data-chg="${ta}"]`);
        if (pxCell) pxCell.textContent = fmtPx(v.px) + " ⚡";
        if (chgCell && chgCell.dataset.base) {
          const chg = 100 * (v.px / parseFloat(chgCell.dataset.base) - 1);
          chgCell.textContent = fmtPct(chg, 1);
          chgCell.className = `num ${chg > 0 ? "up" : chg < 0 ? "down" : ""}`;
        }
      }
    }
  } catch (e) { /* si resta sui prezzi dell'ultima scansione */ }
}

function renderWeights() {
  const weights = [
    ["Smart Money", 25, "est", "proxy distribuzione"],
    ["Team Proximity", 20, "nd", "N/D — manuale"],
    ["Liquidity", 15, "fact", "auto"],
    ["Holder Growth", 10, "fact", "auto (Blockscout)"],
    ["Deployer", 10, "fact", "auto (parziale)"],
    ["Social Velocity", 10, "est", "proxy debole"],
    ["GitHub / Developer", 5, "nd", "N/D — manuale"],
    ["Bridge / Flow", 5, "est", "proxy chain"],
  ];
  document.getElementById("weights-table").innerHTML =
    `<tr><th>Componente</th><th>Peso</th><th>Automazione</th></tr>` +
    weights.map(([n, w, t, label]) =>
      `<tr><td>${n}</td><td class="num">${w}%</td><td><span class="tag ${t}">${label}</span></td></tr>`).join("");
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
  document.getElementById("generated-at").textContent = `ultimo aggiornamento: ${d.generated_at_local}`;

  renderSummary(d);
  renderStatus(d);
  renderBuyAlerts(d);
  renderSignals();
  renderWallets(d);
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
