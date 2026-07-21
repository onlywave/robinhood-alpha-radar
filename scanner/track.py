#!/usr/bin/env python3
"""Tracking del percorso prezzo dei segnali + regole di uscita + paper portfolio.

Modulo di LOGICA PURA (nessuna chiamata di rete): riceve dati già scaricati da
scan.py e aggiorna il registro segnali. Metodologia dalle skill operative:
- signal-postmortem: registro esiti con MFE/MAE, attribuzione onesta,
  nessuna ricalibrazione sotto il campione minimo (20 segnali).
- exit-strategies: piano di uscita a priorità
  hard stop > liquidità > degrado holder > trailing (dopo attivazione) > time stop.

Limiti dichiarati: campionamento ORARIO (le scansioni) — gli esiti paper sono
stime senza slippage/costi, non esecuzioni reali. I path retro-riempiti da
OHLCV GeckoTerminal usano le chiusure orarie e non hanno la liquidità storica
(la regola liquidità non agisce su quei punti).
"""

from datetime import datetime, timezone


def _parse_ts(ts):
    """ISO (anche solo ai minuti) -> datetime UTC aware."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_min(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")


def _decimate(path, max_points):
    """Oltre il tetto: dimezza la risoluzione della metà più vecchia
    (mantiene sempre il primo punto e la parte recente a piena risoluzione)."""
    if len(path) <= max_points:
        return path
    half = len(path) // 2
    old = path[:half]
    kept = [old[0]] + [p for i, p in enumerate(old[1:], 1) if i % 2 == 0]
    return kept + path[half:]


def tracking_open(s, now, tcfg):
    """Il tracking continua finché il segnale è attivo, oppure per
    post_exit_track_hours dopo la cessazione (per misurare il 'se avessi tenuto')."""
    if s.get("active"):
        return True
    ended = _parse_ts(s.get("ended_utc"))
    if ended is None:
        return True
    return (now - ended).total_seconds() / 3600 <= tcfg["post_exit_track_hours"]


def append_path(s, px, liq, now, tcfg):
    """Aggiunge un campione (ts, prezzo, liquidità) e aggiorna MFE/MAE
    incrementali ancorati al prezzo di ingresso. Ritorna True se aggiunto."""
    if px is None or not tracking_open(s, now, tcfg):
        return False
    path = s.setdefault("path", [])
    point = [_iso_min(now), px, round(liq, 0) if liq is not None else None]
    if path and path[-1][0] == point[0]:
        path[-1] = point
    else:
        path.append(point)
    s["path"] = _decimate(path, tcfg["path_max_points"])

    entry = s.get("price_at_signal")
    if entry:
        peak = s.get("peak_px") or entry
        trough = s.get("trough_px") or entry
        if px > peak:
            s["peak_px"], s["peak_utc"] = px, point[0]
        if px < trough:
            s["trough_px"], s["trough_utc"] = px, point[0]
        s.setdefault("peak_px", peak)
        s.setdefault("trough_px", trough)
        s["mfe_pct"] = round(100 * (s["peak_px"] / entry - 1), 1)
        s["mae_pct"] = round(100 * (s["trough_px"] / entry - 1), 1)
    return True


def update_onchain_track(s, holders, top10, now, tcfg):
    """Storicizza holder count e concentrazione top-10; marca il DEGRADO
    (uscita signal-based, skill exit-strategies) quando gli holder calano
    oltre soglia in ~6h o la top-10 sale troppo rispetto al primo campione."""
    if holders is None and top10 is None:
        return
    tr = s.setdefault("onchain_track", [])
    tr.append([_iso_min(now), holders, top10])
    s["onchain_track"] = _decimate(tr, tcfg["path_max_points"])
    if s.get("degraded"):
        return

    reasons = []
    if holders is not None:
        target = now.timestamp() - 6 * 3600
        past = [p for p in tr if p[1] is not None
                and _parse_ts(p[0]).timestamp() <= target]
        if past:
            h6 = past[-1][1]
            if h6 and 100 * (holders - h6) / h6 <= tcfg["holder_drop_6h_pct"]:
                reasons.append(f"holder in calo {100 * (holders - h6) / h6:.1f}%/6h")
    if top10 is not None:
        first_t10 = next((p[2] for p in tr if p[2] is not None), None)
        if first_t10 is not None and top10 - first_t10 >= tcfg["top10_rise_from_signal_pts"]:
            reasons.append(f"concentrazione top-10 +{top10 - first_t10:.1f}pt dal segnale")
    if reasons:
        s["degraded"] = True
        s["degraded_utc"] = _iso_min(now)
        s["degraded_reason"] = "; ".join(reasons)


def replay_paper(s, xcfg):
    """Riesegue il piano di uscita sul percorso campionato. Priorità:
    hard stop > liquidità > degrado holder > trailing (armato oltre soglia)
    > time stop. Stima su chiusure orarie, senza slippage (dichiarato)."""
    entry = s.get("price_at_signal")
    path = s.get("path") or []
    entry_ts = _parse_ts(s.get("first_seen_utc"))
    if not entry or not entry_ts:
        return {"status": "non valutabile", "reason": "prezzo di ingresso assente"}

    liq0 = next((p[2] for p in path if p[2]), None)
    degraded_ts = _parse_ts(s.get("degraded_utc"))
    peak = entry
    armed = False
    last_px, last_ts = None, None

    def closed(reason, px, ts):
        return {"status": "chiuso", "exit_reason": reason,
                "exit_px": px, "exit_utc": _iso_min(ts),
                "hold_hours": round((ts - entry_ts).total_seconds() / 3600, 1),
                "pnl_pct": round(100 * (px / entry - 1), 1),
                "trail_armed": armed}

    for point in path:
        ts = _parse_ts(point[0])
        px, liq = point[1], point[2]
        if px is None or ts is None or ts < entry_ts:
            continue
        last_px, last_ts = px, ts
        peak = max(peak, px)
        gain = 100 * (px / entry - 1)
        if gain <= xcfg["hard_stop_pct"]:
            return closed("hard stop", px, ts)
        if liq is not None and (liq < xcfg["liquidity_floor_usd"]
                                or (liq0 and 100 * (liq / liq0 - 1)
                                    <= xcfg["liquidity_drop_pct"])):
            return closed("liquidità deteriorata", px, ts)
        if degraded_ts and ts >= degraded_ts:
            return closed("degrado holder", px, ts)
        if peak >= entry * (1 + xcfg["trail_activate_gain_pct"] / 100):
            armed = True
        if armed and px <= peak * (1 - xcfg["trail_pct"] / 100):
            return closed("trailing stop", px, ts)
        hours = (ts - entry_ts).total_seconds() / 3600
        if hours >= xcfg["time_stop_hours"] and gain < xcfg["time_stop_min_gain_pct"]:
            return closed("time stop", px, ts)

    if last_px is None:
        return {"status": "non valutabile", "reason": "nessun campione di prezzo"}
    return {"status": "aperto", "pnl_pct": round(100 * (last_px / entry - 1), 1),
            "hold_hours": round((last_ts - entry_ts).total_seconds() / 3600, 1),
            "trail_armed": armed,
            "hard_stop_px": entry * (1 + xcfg["hard_stop_pct"] / 100),
            "trail_stop_px": (peak * (1 - xcfg["trail_pct"] / 100)) if armed else None,
            "peak_px": peak}


def finalize_stale(s, paper, now, tcfg, xcfg):
    """Se il segnale è cessato e la finestra di tracking è chiusa senza che
    alcuna regola sia scattata, chiude amministrativamente all'ultimo prezzo."""
    if paper.get("status") != "aperto" or s.get("active"):
        return paper
    if tracking_open(s, now, tcfg):
        return paper
    path = [p for p in (s.get("path") or []) if p[1] is not None]
    if not path:
        return paper
    last = path[-1]
    entry = s.get("price_at_signal")
    return {"status": "chiuso", "exit_reason": "fine tracking (segnale cessato)",
            "exit_px": last[1], "exit_utc": last[0],
            "hold_hours": paper.get("hold_hours"),
            "pnl_pct": round(100 * (last[1] / entry - 1), 1),
            "trail_armed": paper.get("trail_armed", False)}


def portfolio(sig, xcfg, now):
    """Pagella aggregata: $stake virtuali su OGNI segnale, esiti con le regole
    di uscita, expectancy e criterio di vita/morte esplicito (skill
    signal-postmortem: campione minimo prima di ogni conclusione)."""
    stake = xcfg["stake_usd"]
    rows = []
    for s in sorted(sig, key=lambda x: x.get("first_seen_utc") or ""):
        p = s.get("paper") or {}
        if p.get("status") not in ("chiuso", "aperto"):
            continue
        rows.append({
            "symbol": s.get("symbol"), "first_seen_local": s.get("first_seen_local"),
            "score_at_signal": s.get("score_at_signal"),
            "status": p["status"], "exit_reason": p.get("exit_reason"),
            "pnl_pct": p.get("pnl_pct"), "hold_hours": p.get("hold_hours"),
            "mfe_pct": s.get("mfe_pct"), "mae_pct": s.get("mae_pct"),
            "pnl_usd": round(stake * (p.get("pnl_pct") or 0) / 100, 2),
            "degraded": bool(s.get("degraded")),
        })
    closed = [r for r in rows if r["status"] == "chiuso"]
    pnls = [r["pnl_pct"] for r in closed if r["pnl_pct"] is not None]
    all_pnls = [r["pnl_pct"] for r in rows if r["pnl_pct"] is not None]
    wins = [x for x in pnls if x > 0]
    losses = [-x for x in pnls if x < 0]

    def _avg(v):
        return round(sum(v) / len(v), 1) if v else None

    equity, cum = [], 0.0
    for r in rows:
        cum += r["pnl_usd"]
        equity.append({"symbol": r["symbol"], "cum_usd": round(cum, 2)})

    n = len(rows)
    exp_closed = _avg(pnls)
    exp_mtm = _avg(all_pnls)
    if n < xcfg["min_sample_recalibration"]:
        verdict = (f"CAMPIONE INSUFFICIENTE ({n}/{xcfg['min_sample_recalibration']}): "
                   "nessuna conclusione statistica, si continua a raccogliere. "
                   "Il radar resta SOLO intelligence.")
    elif n >= xcfg["kill_expectancy_n"] and (exp_mtm or 0) <= 0:
        verdict = (f"KILL-CRITERIO RAGGIUNTO: dopo {n} segnali expectancy "
                   f"{exp_mtm}% ≤ 0 → il radar resta strumento di intelligence, "
                   "nessun capitale reale sui segnali.")
    elif (exp_mtm or 0) > 0:
        verdict = (f"Expectancy positiva ({exp_mtm}%) su {n} segnali: edge "
                   "CANDIDATO (non provato). Prossimo passo: size reale minima "
                   "solo con Kelly frazionario e conferma su altri segnali.")
    else:
        verdict = (f"Expectancy {exp_mtm}% su {n} segnali: nessun edge. "
                   "Continuare in paper.")
    return {
        "generated_utc": now.isoformat(),
        "stake_usd": stake,
        "rules": {
            "hard_stop_pct": xcfg["hard_stop_pct"],
            "liquidity": f"pool < ${xcfg['liquidity_floor_usd']:,} o "
                         f"{xcfg['liquidity_drop_pct']}% dall'ingresso",
            "degrado_holder": "holder −3%/6h o top-10 +8pt dal segnale",
            "trailing": f"{xcfg['trail_pct']}% dal picco, armato oltre "
                        f"+{xcfg['trail_activate_gain_pct']}%",
            "time_stop": f"{xcfg['time_stop_hours']}h se sotto "
                         f"+{xcfg['time_stop_min_gain_pct']}%",
            "nota": "priorità: hard stop > liquidità > degrado > trailing > "
                    "time stop. Stime su campioni orari, senza slippage/costi.",
        },
        "rows": rows,
        "stats": {
            "n_signals": n, "n_closed": len(closed),
            "n_open": n - len(closed),
            "win_rate_closed_pct": round(100 * len(wins) / len(pnls), 0) if pnls else None,
            "expectancy_closed_pct": exp_closed,
            "expectancy_mtm_pct": exp_mtm,
            "profit_factor": round(sum(wins) / sum(losses), 2)
            if wins and losses else None,
            "best_pct": max(all_pnls) if all_pnls else None,
            "worst_pct": min(all_pnls) if all_pnls else None,
            "total_pnl_usd": round(sum(r["pnl_usd"] for r in rows), 2),
        },
        "equity": equity,
        "verdict": verdict,
    }
