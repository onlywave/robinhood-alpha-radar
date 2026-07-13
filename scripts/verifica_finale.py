#!/usr/bin/env python3
"""Verifica finale manuale di un token su Robinhood Chain (chain-id 4663).

Uso:
    python3 scripts/verifica_finale.py 0xTOKEN [0xPOOL]

Da eseguire SEMPRE prima di agire su un ALPHA BUY ALERT del radar.
Interroga fonti indipendenti (DexScreener, Blockscout, RPC ufficiale,
GoPlus quando supportato) e stampa una checklist PASS/WARN/FAIL.

Questo script NON esegue transazioni, NON è consulenza finanziaria e
NON garantisce l'assenza di honeypot o rug: riduce i rischi noti,
non li azzera. Rischio di perdita totale sempre presente.
"""

import json
import os
import ssl
import sys
import time
import urllib.request

RPC = "https://rpc.mainnet.chain.robinhood.com"
EXPLORER = "https://robinhoodchain.blockscout.com"
DS_CHAIN = "robinhood"
GOPLUS_CHAIN_ID = "4663"
TRANSFER_SIG = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
BURN = {"0x0000000000000000000000000000000000000000",
        "0x000000000000000000000000000000000000dead"}
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36",
      "Accept": "application/json"}


def _ctx():
    ctx = ssl.create_default_context()
    try:
        ctx.load_default_certs()
        if ctx.cert_store_stats().get("x509_ca", 0) > 0:
            return ctx
    except Exception:
        pass
    for b in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"):
        if os.path.exists(b):
            return ssl.create_default_context(cafile=b)
    return ctx


CTX = _ctx()


def get(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=25, context=CTX) as r:
                return json.loads(r.read().decode())
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params}).encode()
    try:
        req = urllib.request.Request(
            RPC, data=body, headers={**UA, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=25, context=CTX) as r:
            return json.loads(r.read().decode()).get("result")
    except Exception:
        return None


RESULTS = []


def check(name, status, detail):
    icon = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌", "N/D": "❔"}[status]
    RESULTS.append(status)
    print(f"  {icon} [{status}] {name}: {detail}")


def main():
    if len(sys.argv) < 2 or not sys.argv[1].startswith("0x"):
        print(__doc__)
        sys.exit(1)
    token = sys.argv[1].lower()
    pool_hint = sys.argv[2].lower() if len(sys.argv) > 2 else None
    print(f"\n═══ VERIFICA FINALE — {token} ═══\n")

    # ---------------- 1. Mercato (DexScreener)
    print("— Mercato (DexScreener)")
    d = get(f"https://api.dexscreener.com/tokens/v1/{DS_CHAIN}/{token}")
    pair = None
    if d:
        pairs = sorted(d, key=lambda p: (p.get("liquidity") or {}).get("usd", 0),
                       reverse=True)
        if pairs:
            pair = pairs[0]
    if not pair:
        check("coppia DEX", "FAIL", "nessuna coppia trovata su DexScreener")
    else:
        liq = (pair.get("liquidity") or {}).get("usd", 0)
        v24 = (pair.get("volume") or {}).get("h24", 0)
        tx = (pair.get("txns") or {}).get("h24", {})
        buys, sells = tx.get("buys", 0), tx.get("sells", 0)
        h1 = (pair.get("txns") or {}).get("h1", {})
        pool = (pair.get("pairAddress") or pool_hint or "").lower()
        print(f"  pair: {pair.get('baseToken', {}).get('symbol')}/"
              f"{pair.get('quoteToken', {}).get('symbol')} su {pair.get('dexId')}"
              f" | prezzo ${pair.get('priceUsd')} | mcap {pair.get('marketCap')}")
        check("liquidità", "PASS" if liq >= 150000 else
              ("WARN" if liq >= 50000 else "FAIL"), f"${liq:,.0f}")
        check("volume 24h", "PASS" if v24 > 100000 else "WARN", f"${v24:,.0f}")
        vl = v24 / liq if liq else 0
        check("volume/liquidità", "PASS" if vl < 15 else
              ("WARN" if vl < 25 else "FAIL"),
              f"{vl:.1f}x" + (" (possibile wash)" if vl >= 15 else ""))
        check("vendite ultime 24h", "PASS" if sells >= 50 else
              ("WARN" if sells >= 10 else "FAIL"),
              f"{sells} sell / {buys} buy (sellability empirica)")
        check("vendite ultima ora", "PASS" if h1.get("sells", 0) > 0 else "WARN",
              f"{h1.get('sells', 0)} sell / {h1.get('buys', 0)} buy")
        for size in (500, 1000, 2500):
            impact = 100 * size / (liq / 2) if liq else 999
            lvl = "PASS" if impact < 1 else ("WARN" if impact < 3 else "FAIL")
            check(f"slippage stimato ordine ${size}", lvl, f"~{impact:.2f}%")

    # ---------------- 2. Contratto (Blockscout + RPC)
    print("\n— Contratto (Blockscout + RPC)")
    sc = get(f"{EXPLORER}/api/v2/smart-contracts/{token}")
    verified = bool(sc and (sc.get("is_verified") or sc.get("source_code")))
    check("codice verificato", "PASS" if verified else "FAIL",
          "sorgente pubblicato su Blockscout" if verified
          else "NON verificato: rischio non valutabile")
    if sc:
        lang = sc.get("language")
        proxy = sc.get("proxy_type")
        if proxy and proxy != "unknown":
            check("proxy", "WARN", f"tipo {proxy}: logica aggiornabile — "
                  "verificare admin/timelock")
        else:
            check("proxy", "PASS", "nessun proxy dichiarato")
        print(f"  linguaggio: {lang} | nome: {sc.get('name')}")
    ores = rpc("eth_call", [{"to": token, "data": "0x8da5cb5b"}, "latest"])
    if ores in (None, "0x"):
        check("owner()", "WARN", "funzione owner assente o non leggibile "
              "(controllare ruoli custom nel sorgente)")
    else:
        owner = "0x" + ores[-40:]
        if int(owner, 16) == 0:
            check("owner()", "PASS", "rinunciato (0x0)")
        else:
            check("owner()", "FAIL", f"ATTIVO: {owner} — può detenere "
                  "privilegi (mint/pause/tax/blacklist)")
    sup = rpc("eth_call", [{"to": token, "data": "0x18160ddd"}, "latest"])
    if sup and sup != "0x":
        print(f"  totalSupply attuale: {int(sup, 16) / 1e18:,.0f} "
              f"(confrontare con supply dichiarata)")

    # ---------------- 3. Distribuzione holder (Blockscout)
    print("\n— Distribuzione holder (Blockscout)")
    tk = get(f"{EXPLORER}/api/v2/tokens/{token}")
    supply = float(tk.get("total_supply") or 0) if tk else 0
    if tk:
        hc = tk.get("holders_count") or tk.get("holders")
        check("numero holder", "PASS" if hc and int(float(hc)) >= 300 else "WARN",
              str(hc))
    hl = get(f"{EXPLORER}/api/v2/tokens/{token}/holders")
    if hl and supply:
        info = get(f"{EXPLORER}/api/v2/addresses/{token}")
        creator = ((info or {}).get("creator_address_hash") or "").lower()
        shares, labels = [], []
        for it in hl.get("items", []):
            a = it.get("address") or {}
            h = (a.get("hash") or "").lower()
            nm = a.get("name") or ""
            if h in BURN or h == token:
                continue
            pct = 100 * float(it.get("value") or 0) / supply
            if a.get("is_contract") and ("pool" in nm.lower() or h == pool_hint):
                labels.append(f"    (escluso pool {nm or h[:10]}: {pct:.1f}%)")
                continue
            tag = " ← DEPLOYER" if h == creator else ""
            if len(shares) < 10:
                labels.append(f"    top{len(shares) + 1}: {h[:12]}… {pct:.2f}%{tag}")
            shares.append((pct, h == creator))
        top10 = sum(p for p, _ in shares[:10])
        for line in labels:
            print(line)
        check("top-10 aggiustata", "PASS" if top10 <= 25 else
              ("WARN" if top10 <= 35 else "FAIL"), f"{top10:.1f}%")
        cs = sum(p for p, isc in shares if isc)
        check("quota deployer", "PASS" if cs < 5 else
              ("WARN" if cs < 15 else "FAIL"), f"{cs:.2f}%")
    else:
        check("holder list", "N/D", "Blockscout non disponibile ora: riprovare")

    # ---------------- 4. Venditori reali distinti (RPC, ultime ~24h)
    print("\n— Sellability on-chain (RPC)")
    if pair:
        pool = (pair.get("pairAddress") or "").lower()
        latest_bn = rpc("eth_blockNumber", [])
        if latest_bn and pool:
            frm = max(0, int(latest_bn, 16) - 350000)  # ~24h di blocchi
            pool_pad = "0x" + "0" * 24 + pool[2:]
            logs = rpc("eth_getLogs", [{
                "fromBlock": hex(frm), "toBlock": "latest",
                "address": token,
                "topics": [TRANSFER_SIG, None, pool_pad]}])
            if logs is None:
                check("venditori distinti", "N/D", "eth_getLogs non disponibile")
            else:
                sellers = {("0x" + l["topics"][1][-40:]) for l in logs}
                sellers -= {pool, token}
                check("venditori distinti ~24h",
                      "PASS" if len(sellers) >= 25 else
                      ("WARN" if len(sellers) >= 5 else "FAIL"),
                      f"{len(sellers)} wallet diversi hanno venduto nel pool "
                      "(prova empirica, non garanzia)")

    # ---------------- 5. GoPlus security (se la chain è supportata)
    print("\n— GoPlus token security")
    gp = get(f"https://api.gopluslabs.io/api/v1/token_security/"
             f"{GOPLUS_CHAIN_ID}?contract_addresses={token}")
    res = (gp or {}).get("result") or {}
    if not res:
        check("GoPlus", "N/D", f"chain {GOPLUS_CHAIN_ID} non ancora supportata "
              f"({(gp or {}).get('message', 'nessuna risposta')})")
    else:
        t = res.get(token, {})
        for field, label in [("is_honeypot", "honeypot"),
                             ("is_mintable", "mintable"),
                             ("can_take_back_ownership", "ownership recuperabile"),
                             ("is_blacklisted", "blacklist"),
                             ("buy_tax", "buy tax"), ("sell_tax", "sell tax")]:
            v = t.get(field)
            if v is None:
                continue
            bad = str(v) not in ("0", "", "0.0")
            check(f"GoPlus {label}", "FAIL" if bad else "PASS", str(v))

    # ---------------- verdetto
    print("\n═══ VERDETTO ═══")
    fails = RESULTS.count("FAIL")
    warns = RESULTS.count("WARN")
    nds = RESULTS.count("N/D")
    print(f"  PASS {RESULTS.count('PASS')} | WARN {warns} | FAIL {fails} | N/D {nds}")
    if fails:
        print("  ⛔ FAIL presenti: NON procedere finché ogni FAIL non è chiarito.")
    elif warns or nds:
        print("  ⚠️  Nessun FAIL, ma WARN/N-D da valutare a mano (leggere il "
              "sorgente, controllare LP lock e social).")
    else:
        print("  ✅ Checklist superata. Restano NON verificati da questo script: "
              "LP lock/burn, cluster di wallet, bundle/sniper, team.")
    print("  Size prudenziale, invalidazione definita PRIMA dell'ingresso, "
          "nessuna certezza: il rischio di perdita totale resta.\n")


if __name__ == "__main__":
    main()
