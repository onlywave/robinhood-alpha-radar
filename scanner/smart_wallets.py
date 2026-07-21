#!/usr/bin/env python3
"""Smart-wallet layer: profila gli early buyer dei segnali VINCENTI contro
quelli dei PERDENTI e produce la lista dei wallet "provati".

Metodologia (skill copy-trading + wallet-profiling, adattata da Solana a
EVM/Blockscout — dichiarato):
- "early buy" = transfer del token DAL POOL verso un wallet (= acquisto DEX)
  nella finestra prima del primo segnale del radar;
- punteggio differenziale W−L: chi ha comprato presto ≥2 vincitori e più
  vincitori che perdenti. I bot "spray" che comprano tutto si annullano da
  soli (W−L≈0 o negativo) — è il filtro sybil di primo livello;
- i contratti (router/aggregatori) sono esclusi via eth_getCode.

Limiti dichiarati: con pochi token etichettati la lista è indicativa, NON un
segnale operativo; il campione cresce col registro. Nessuna analisi di
funding-chain (resta manuale).
"""

import sys
from datetime import datetime, timezone

TRANSFER_SIG = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
BURN = {"0x0000000000000000000000000000000000000000",
        "0x000000000000000000000000000000000000dead"}


def _parse_ts(ts):
    try:
        dt = datetime.fromisoformat(ts)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def label_tokens(signals, swcfg):
    """VINCITORE = MFE oltre soglia; PERDENTE = esito paper (o MAE) oltre la
    soglia di perdita senza mai essere stato vincitore. Il resto resta
    non etichettato (onestà: niente forzature)."""
    winners, losers = [], []
    for s in signals:
        mfe = s.get("mfe_pct")
        mae = s.get("mae_pct")
        paper = s.get("paper") or {}
        if mfe is not None and mfe >= swcfg["winner_mfe_pct"]:
            winners.append(s)
        elif ((paper.get("status") == "chiuso"
               and (paper.get("pnl_pct") or 0) <= swcfg["loser_pnl_pct"])
              or (mae is not None and mae <= swcfg["loser_pnl_pct"])):
            losers.append(s)
    return winners, losers


class BlockClock:
    """Ricerca binaria blocco<->timestamp con cache (poche chiamate RPC)."""

    def __init__(self, rpc_call, rpc_url):
        self.rpc_call, self.rpc_url, self.cache = rpc_call, rpc_url, {}
        latest = rpc_call("eth_blockNumber", [], rpc_url)
        self.latest = int(latest, 16) if latest else None

    def ts_of(self, n):
        if n in self.cache:
            return self.cache[n]
        blk = self.rpc_call("eth_getBlockByNumber", [hex(n), False], self.rpc_url)
        ts = int(blk["timestamp"], 16) if blk else None
        self.cache[n] = ts
        return ts

    def block_at(self, target_ts):
        """Primo blocco con timestamp >= target."""
        if self.latest is None:
            return None
        lo, hi = 1, self.latest
        while lo < hi:
            mid = (lo + hi) // 2
            ts = self.ts_of(mid)
            if ts is None:
                return None
            if ts < target_ts:
                lo = mid + 1
            else:
                hi = mid
        return lo


def _pad_topic(addr):
    return "0x" + "0" * 24 + addr[2:].lower()


def early_buyers(sig, clock, rpc_call, rpc_url, swcfg):
    """Compratori dal pool nella finestra pre-segnale. Ritorna lista di
    (address, block) ordinata per blocco, o None se la fonte fallisce."""
    token = sig.get("token_address")
    pool = (sig.get("pool_address") or "").lower()
    t1 = _parse_ts(sig.get("first_seen_utc"))
    if not token or not pool or not t1:
        return None
    t0 = t1.timestamp() - swcfg["early_window_hours"] * 3600
    b0, b1 = clock.block_at(int(t0)), clock.block_at(int(t1.timestamp()))
    if b0 is None or b1 is None or b1 < b0:
        return None

    def get_logs(lo, hi, depth=0):
        res = rpc_call("eth_getLogs", [{"fromBlock": hex(lo), "toBlock": hex(hi),
                                        "address": token,
                                        "topics": [TRANSFER_SIG, _pad_topic(pool)]}],
                       rpc_url)
        if res is not None:
            return res
        if depth >= 4 or hi <= lo:
            return None
        mid = (lo + hi) // 2
        a = get_logs(lo, mid, depth + 1)
        b = get_logs(mid + 1, hi, depth + 1)
        if a is None or b is None:
            return None
        return a + b

    logs = get_logs(b0, b1)
    if logs is None:
        return None
    out, seen = [], set()
    for l in sorted(logs, key=lambda x: int(x["blockNumber"], 16)):
        to = ("0x" + l["topics"][2][-40:]).lower()
        if to in BURN or to == token.lower() or to == pool or to in seen:
            continue
        seen.add(to)
        out.append((to, int(l["blockNumber"], 16)))
        if len(out) >= swcfg["max_early_buyers_per_token"]:
            break
    return out


def build(signals, cfg, rpc_call, now):
    """Costruisce il profilo smart-wallet dall'intero registro segnali."""
    swcfg = cfg["smart_wallets"]
    rpc_url = cfg["primary_chain"]["rpc"]
    winners, losers = label_tokens(signals, swcfg)
    clock = BlockClock(rpc_call, rpc_url)

    ledger = {}   # addr -> {"w": set(sym), "l": set(sym)}
    skipped = []
    for group, key in ((winners, "w"), (losers, "l")):
        for s in group:
            buyers = early_buyers(s, clock, rpc_call, rpc_url, swcfg)
            if buyers is None:
                skipped.append(s.get("symbol"))
                continue
            for addr, _blk in buyers:
                ledger.setdefault(addr, {"w": set(), "l": set()})[key].add(
                    s.get("symbol"))

    # qualificati: >= min_winners vincitori e punteggio differenziale positivo
    qualified = []
    for addr, d in ledger.items():
        score = len(d["w"]) - len(d["l"])
        if len(d["w"]) >= swcfg["min_winners_bought"] and score >= 1:
            qualified.append({"address": addr, "winners": len(d["w"]),
                              "losers": len(d["l"]), "score": score,
                              "tokens_won": sorted(d["w"])})
    # esclusione contratti (router/aggregatori) — solo sui qualificati
    human = []
    for q in qualified:
        code = rpc_call("eth_getCode", [q["address"], "latest"], rpc_url)
        if code and code not in ("0x", "0x0"):
            continue
        human.append(q)
    human.sort(key=lambda q: (-q["score"], -q["winners"]))

    return {
        "built_utc": now.isoformat(),
        "early_window_hours": swcfg["early_window_hours"],
        "tokens": {"winners": [s.get("symbol") for s in winners],
                   "losers": [s.get("symbol") for s in losers],
                   "skipped": skipped},
        "n_early_wallets_seen": len(ledger),
        "wallets": human[:200],
        "method_notes": ("early buy = transfer dal pool nella finestra "
                         f"{swcfg['early_window_hours']}h pre-segnale; "
                         "punteggio W−L (i bot spray si annullano); contratti "
                         "esclusi via eth_getCode. Lista indicativa finché i "
                         "token etichettati sono pochi."),
    }


if __name__ == "__main__":
    # esecuzione manuale: python3 scanner/smart_wallets.py
    import json
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from scan import rpc_call as _rpc, ROOT
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    sig = json.load(open(os.path.join(ROOT, "data", "signals.json")))
    out = build(sig, cfg, _rpc, datetime.now(timezone.utc))
    path = os.path.join(ROOT, "data", "smart_wallets.json")
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"OK {path}: {len(out['wallets'])} smart-wallet qualificati "
          f"(su {out['n_early_wallets_seen']} early wallet osservati)")
