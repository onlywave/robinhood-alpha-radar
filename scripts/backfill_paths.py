#!/usr/bin/env python3
"""Backfill UNA TANTUM del percorso prezzo dei segnali già a registro.

Ricostruisce path orario, MFE/MAE e picco/minimo dai candle OHLCV di
GeckoTerminal per i pool dei segnali che non hanno ancora un path (o lo hanno
più corto dello storico disponibile). Onestà del dato:
- prezzo dei punti = CHIUSURA oraria; MFE/MAE però usano HIGH/LOW dei candle
  (più accurati del campionamento orario);
- la liquidità storica NON è disponibile via OHLCV → liq=None (la regola di
  uscita per liquidità non agisce sui punti retro-riempiti, dichiarato);
- pool morti possono avere storico parziale: si retro-riempie il possibile e
  si stampa cosa manca.

Uso: python3 scripts/backfill_paths.py            (aggiorna data/signals.json)
     python3 scripts/backfill_paths.py --dry-run  (mostra senza scrivere)
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scanner"))
from scan import http_json, CONFIG, ROOT  # noqa: E402
import track  # noqa: E402

SIGNALS = os.path.join(ROOT, "data", "signals.json")


def fetch_ohlcv(pool, before_ts=None):
    """Candles orari [ts, o, h, l, c, vol] in ordine crescente."""
    url = (f"https://api.geckoterminal.com/api/v2/networks/"
           f"{CONFIG['primary_chain']['geckoterminal_id']}/pools/{pool}/"
           f"ohlcv/hour?aggregate=1&limit=1000&currency=usd&token=base")
    if before_ts:
        url += f"&before_timestamp={before_ts}"
    d = http_json(url, gt=True)
    lst = (((d or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    return sorted(lst, key=lambda c: c[0])


def backfill(s, tcfg, now):
    entry_ts = datetime.fromisoformat(s["first_seen_utc"])
    end_track = now
    if s.get("ended_utc"):
        ended = datetime.fromisoformat(s["ended_utc"])
        end_track = min(now, ended + timedelta(hours=tcfg["post_exit_track_hours"]))
    candles = fetch_ohlcv(s["pool_address"])
    usable = [c for c in candles
              if entry_ts.timestamp() <= c[0] <= end_track.timestamp()]
    if not usable:
        return 0, "nessun candle utilizzabile (pool senza storico?)"

    path = []
    peak, peak_ts = None, None
    trough, trough_ts = None, None
    for ts, _o, hi, lo, close, _v in usable:
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M")
        path.append([iso, close, None])
        if hi is not None and (peak is None or hi > peak):
            peak, peak_ts = hi, iso
        if lo is not None and lo > 0 and (trough is None or lo < trough):
            trough, trough_ts = lo, iso

    existing = s.get("path") or []
    if len(existing) >= len(path):
        return 0, "path esistente già più ricco: intatto"
    # innesta gli eventuali punti live già raccolti dopo l'ultimo candle
    last_iso = path[-1][0]
    merged = path + [p for p in existing if p[0] > last_iso]
    s["path"] = track._decimate(merged, tcfg["path_max_points"])

    entry = s.get("price_at_signal")
    if entry and peak is not None:
        cur_peak = s.get("peak_px") or entry
        if peak > cur_peak:
            s["peak_px"], s["peak_utc"] = peak, peak_ts
        cur_trough = s.get("trough_px") or entry
        if trough is not None and trough < cur_trough:
            s["trough_px"], s["trough_utc"] = trough, trough_ts
        s["mfe_pct"] = round(100 * ((s.get("peak_px") or entry) / entry - 1), 1)
        s["mae_pct"] = round(100 * ((s.get("trough_px") or entry) / entry - 1), 1)
    s["path_backfilled"] = True
    return len(path), f"{len(path)} candle innestati (high/low per MFE/MAE)"


def main():
    dry = "--dry-run" in sys.argv
    now = datetime.now(timezone.utc)
    tcfg = CONFIG["tracking"]
    xcfg = CONFIG["exit_plan"]
    sig = json.load(open(SIGNALS))
    for s in sig:
        n, msg = backfill(s, tcfg, now)
        paper = track.replay_paper(s, xcfg)
        s["paper"] = track.finalize_stale(s, paper, now, tcfg, xcfg)
        p = s["paper"]
        esito = (f"{p['status']} {p.get('exit_reason') or ''} "
                 f"pnl {p.get('pnl_pct')}%" if p.get("status") != "non valutabile"
                 else "non valutabile")
        print(f"{s['symbol']:9s} {msg:55s} | MFE {s.get('mfe_pct')}% "
              f"MAE {s.get('mae_pct')}% | paper: {esito}")
    book = track.portfolio(sig, xcfg, now)
    st = book["stats"]
    print(f"\nPAPER ($100/segnale): {st['n_signals']} segnali, "
          f"{st['n_closed']} chiusi, win rate {st['win_rate_closed_pct']}%, "
          f"expectancy chiusi {st['expectancy_closed_pct']}% / mtm "
          f"{st['expectancy_mtm_pct']}%, PnL totale ${st['total_pnl_usd']}")
    print(f"VERDETTO: {book['verdict']}")
    if dry:
        print("\n--dry-run: nessuna scrittura")
        return
    with open(SIGNALS, "w") as f:
        json.dump(sig, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"\nScritto {SIGNALS}")


if __name__ == "__main__":
    main()
