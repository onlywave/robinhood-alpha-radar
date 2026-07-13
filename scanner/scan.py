#!/usr/bin/env python3
"""Robinhood Chain Alpha Radar — scanner orario.

Raccoglie dati pubblici (DefiLlama, GeckoTerminal, DexScreener), applica lo
screening e lo scoring parziale definiti nell'handoff operativo e scrive JSON
statici per il dashboard GitHub Pages.

Zero dipendenze esterne: solo stdlib. Ogni fonte può fallire senza far
fallire lo scan (degradazione dichiarata nel JSON di output).

Principio centrale (handoff): nessun BUY ALERT automatico. Le componenti di
score non verificabili da fonti pubbliche gratuite (smart money, team
proximity, holder growth, deployer, GitHub) sono dichiarate N/D e la
classificazione massima emessa dal sistema è HIGH-PRIORITY WATCH.
"""

import json
import os
import ssl
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Zurich")
except Exception:
    TZ = timezone.utc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = json.load(open(os.path.join(ROOT, "config.json")))

UA = {"User-Agent": "alpha-radar/1.0 (static dashboard; hourly cron)",
      "Accept": "application/json"}
# Blockscout (nginx) rifiuta gli User-Agent non-browser con 503
UA_BROWSER = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36",
              "Accept": "application/json"}

GT_LAST_CALL = [0.0]  # GeckoTerminal: max 30 req/min -> spaziare le chiamate
BS_FAILS = [0]        # circuit-breaker Blockscout (istanza instabile)


def bs_json(url, retries=2):
    """GET Blockscout con circuit-breaker: dopo troppi fallimenti consecutivi
    smette di chiamare (i dati restano N/D invece di bloccare lo scan)."""
    if BS_FAILS[0] >= 8:
        return None
    d = http_json(url, retries=retries, timeout=12, headers=UA_BROWSER)
    if d is None:
        BS_FAILS[0] += 1
    else:
        BS_FAILS[0] = max(0, BS_FAILS[0] - 2)
    return d


def _ssl_context():
    """Contesto SSL: default, con fallback a certifi o al bundle di sistema
    (alcune installazioni Python su macOS non trovano i certificati)."""
    ctx = ssl.create_default_context()
    try:
        ctx.load_default_certs()
        if ctx.cert_store_stats().get("x509_ca", 0) > 0:
            return ctx
    except Exception:
        pass
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for bundle in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"):
        if os.path.exists(bundle):
            return ssl.create_default_context(cafile=bundle)
    return ctx


SSL_CTX = _ssl_context()


def http_json(url, retries=2, timeout=25, gt=False, headers=None):
    """GET JSON con retry. Ritorna None su fallimento (mai eccezioni)."""
    if gt:
        wait = 2.8 - (time.time() - GT_LAST_CALL[0])
        if wait > 0:
            time.sleep(wait)
        GT_LAST_CALL[0] = time.time()
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers or UA)
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                time.sleep(20)  # rate limit: attendere una finestra piena
                continue
            if attempt == retries:
                print(f"[warn] GET fallita {url}: {e}", file=sys.stderr)
                return None
            time.sleep(2 * (attempt + 1))
        except Exception as e:
            if attempt == retries:
                print(f"[warn] GET fallita {url}: {e}", file=sys.stderr)
                return None
            time.sleep(2 * (attempt + 1))
    return None


def fnum(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- chain status

def fetch_chain_status():
    """TVL, volume DEX e protocolli principali della chain primaria (fatti)."""
    name = CONFIG["primary_chain"]["defillama_name"]
    status = {"tvl_usd": None, "dex_vol_24h": None, "dex_vol_7d": None,
              "dex_protocols": [], "top_protocols_tvl": [], "source_errors": []}

    chains = http_json("https://api.llama.fi/v2/chains")
    if chains:
        hit = next((c for c in chains if c.get("name") == name), None)
        if hit:
            status["tvl_usd"] = fnum(hit.get("tvl"), None)
    else:
        status["source_errors"].append("defillama:/v2/chains")

    q = urllib.parse.quote(name)
    dexs = http_json(f"https://api.llama.fi/overview/dexs/{q}"
                     "?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true")
    if dexs:
        status["dex_vol_24h"] = fnum(dexs.get("total24h"), None)
        status["dex_vol_7d"] = fnum(dexs.get("total7d"), None)
        protos = sorted(dexs.get("protocols", []),
                        key=lambda p: fnum(p.get("total24h")), reverse=True)
        status["dex_protocols"] = [
            {"name": p.get("name"), "vol_24h": fnum(p.get("total24h"), None)}
            for p in protos[:12]]
    else:
        status["source_errors"].append("defillama:/overview/dexs")

    protocols = http_json("https://api.llama.fi/protocols")
    if protocols:
        on_chain = [p for p in protocols if name in (p.get("chains") or [])]
        top = sorted(on_chain,
                     key=lambda p: fnum((p.get("chainTvls") or {}).get(name)),
                     reverse=True)[:12]
        status["top_protocols_tvl"] = [
            {"name": p.get("name"), "category": p.get("category"),
             "tvl": fnum((p.get("chainTvls") or {}).get(name), None)}
            for p in top]
    else:
        status["source_errors"].append("defillama:/protocols")
    return status


# ------------------------------------------------------------- pool discovery

MAJORS = {"WETH", "ETH", "USDC", "USDT", "DAI", "WBTC", "CBBTC", "SOL", "WSOL",
          "SUI", "WBERA", "BERA", "WHYPE", "HYPE", "WMON", "MON", "USDE",
          "USDC.E", "USDT0", "FDUSD", "USDS", "WSTETH", "STETH", "HOOD"}


def gt_pools(network, endpoint, pages=1):
    """Pool da GeckoTerminal con token inclusi. endpoint: new_pools|trending_pools|pools."""
    out, included = [], {}
    for page in range(1, pages + 1):
        d = http_json(
            f"https://api.geckoterminal.com/api/v2/networks/{network}/{endpoint}"
            f"?page={page}&include=base_token%2Cquote_token", gt=True)
        if not d:
            break
        for inc in d.get("included", []):
            included[inc["id"]] = inc.get("attributes", {})
        out.extend(d.get("data", []))
    return out, included


def normalize_pool(pool, included, network_label):
    a = pool.get("attributes", {})
    rel = pool.get("relationships", {})
    base_id = ((rel.get("base_token") or {}).get("data") or {}).get("id", "")
    quote_id = ((rel.get("quote_token") or {}).get("data") or {}).get("id", "")
    base = included.get(base_id, {})
    quote = included.get(quote_id, {})
    tx = a.get("transactions") or {}
    h24 = tx.get("h24") or {}
    vol = a.get("volume_usd") or {}
    chg = a.get("price_change_percentage") or {}
    created = a.get("pool_created_at")
    age_h = None
    if created:
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        except ValueError:
            pass
    return {
        "network": network_label,
        "pool_address": a.get("address"),
        "pool_name": a.get("name"),
        "token_address": base.get("address"),
        "token_symbol": base.get("symbol"),
        "token_name": base.get("name"),
        "quote_symbol": quote.get("symbol"),
        "price_usd": fnum(a.get("base_token_price_usd"), None),
        "liquidity_usd": fnum(a.get("reserve_in_usd")),
        "vol_h1": fnum(vol.get("h1")),
        "vol_h24": fnum(vol.get("h24")),
        "buys_h24": int(fnum(h24.get("buys"))),
        "sells_h24": int(fnum(h24.get("sells"))),
        "chg_h1": fnum(chg.get("h1"), None),
        "chg_h24": fnum(chg.get("h24"), None),
        "market_cap_usd": fnum(a.get("market_cap_usd"), None) or None,
        "fdv_usd": fnum(a.get("fdv_usd"), None) or None,
        "pool_created_at": created,
        "age_hours": round(age_h, 1) if age_h is not None else None,
    }


def dedupe_best_pool(cands):
    """Un candidato per token: tiene il pool con liquidità massima e somma i volumi."""
    by_token = {}
    for c in cands:
        k = (c["network"], (c.get("token_address") or c.get("pool_address") or "").lower())
        cur = by_token.get(k)
        if cur is None:
            by_token[k] = dict(c)
        else:
            cur["vol_h24"] += c["vol_h24"]
            cur["buys_h24"] += c["buys_h24"]
            cur["sells_h24"] += c["sells_h24"]
            if c["liquidity_usd"] > cur["liquidity_usd"]:
                keep_vol = (cur["vol_h24"], cur["buys_h24"], cur["sells_h24"])
                cur.update(c)
                cur["vol_h24"], cur["buys_h24"], cur["sells_h24"] = keep_vol
    return list(by_token.values())


def enrich_dexscreener(cands, chain_id):
    """Aggiunge socials/website/pair-url da DexScreener (batch max 30 token)."""
    addrs = [c["token_address"] for c in cands if c.get("token_address")][:30]
    if not addrs:
        return
    d = http_json(f"https://api.dexscreener.com/tokens/v1/{chain_id}/{','.join(addrs)}")
    if not d:
        return
    best = {}
    for p in d:
        ta = (p.get("baseToken") or {}).get("address", "").lower()
        liq = fnum((p.get("liquidity") or {}).get("usd"))
        if ta and (ta not in best or liq > best[ta][0]):
            best[ta] = (liq, p)
    for c in cands:
        ta = (c.get("token_address") or "").lower()
        if ta in best:
            p = best[ta][1]
            info = p.get("info") or {}
            c["ds_url"] = p.get("url")
            c["websites"] = [w.get("url") for w in info.get("websites", []) if w.get("url")]
            c["socials"] = [{"type": s.get("type"), "url": s.get("url")}
                            for s in info.get("socials", []) if s.get("url")]


# ------------------------------------------------- enrichment on-chain (L2/L3)

BURN_ADDRS = {"0x0000000000000000000000000000000000000000",
              "0x000000000000000000000000000000000000dead"}


def enrich_onchain(cands, prev_by_token):
    """Arricchisce i top candidati con dati Blockscout/RPC: holder count e
    crescita, concentrazione top-10 aggiustata (esclusi pool/burn/contratto),
    verifica del contratto, owner()/renounce, deployer e sua quota.

    Ogni dato mancante resta None (dichiarato N/D, mai inventato)."""
    pc = CONFIG["primary_chain"]
    explorer = pc["explorer"].rstrip("/")
    rpc = pc["rpc"]
    for c in cands[:CONFIG.get("onchain_enrich_top", 10)]:
        ta = (c.get("token_address") or "").lower()
        if not ta:
            continue
        oc = {"holders_count": None, "holders_growth_pct_1h": None,
              "top10_adjusted_pct": None, "contract_verified": None,
              "owner_status": None, "creator": None,
              "creator_share_pct": None, "total_supply": None}
        time.sleep(0.4)  # gentile con Blockscout

        tk = bs_json(f"{explorer}/api/v2/tokens/{ta}", retries=3)
        if tk and isinstance(tk, dict):
            oc["holders_count"] = int(fnum(tk.get("holders_count")
                                           or tk.get("holders"), 0)) or None
            oc["total_supply"] = fnum(tk.get("total_supply"), None)

        info = bs_json(f"{explorer}/api/v2/addresses/{ta}", retries=2)
        if info and isinstance(info, dict):
            oc["creator"] = info.get("creator_address_hash")

        sc = bs_json(f"{explorer}/api/v2/smart-contracts/{ta}", retries=2)
        if sc and isinstance(sc, dict):
            oc["contract_verified"] = bool(sc.get("is_verified")
                                           or sc.get("source_code")
                                           or sc.get("abi"))
        elif sc is not None:
            oc["contract_verified"] = False

        # owner(): 0x0 = renounced; assente = nessuna funzione owner
        ores = eth_call(ta, "0x8da5cb5b", rpc)
        if ores is None:
            oc["owner_status"] = None          # RPC non ha risposto
        elif ores in ("0x", "0x0"):
            oc["owner_status"] = "assente"     # il contratto non espone owner()
        else:
            owner = "0x" + ores[-40:]
            oc["owner_status"] = ("renounced" if int(owner, 16) == 0
                                  else f"attivo:{owner}")

        holders = bs_json(f"{explorer}/api/v2/tokens/{ta}/holders", retries=3)
        if holders and isinstance(holders, dict) and oc["total_supply"]:
            pool = (c.get("pool_address") or "").lower()
            creator = (oc["creator"] or "").lower()
            shares = []
            for it in holders.get("items", []):
                a = it.get("address") or {}
                h = (a.get("hash") or "").lower()
                name = (a.get("name") or "")
                if h in BURN_ADDRS or h == ta or h == pool:
                    continue
                if a.get("is_contract") and "pool" in name.lower():
                    continue
                share = 100 * fnum(it.get("value")) / oc["total_supply"]
                if h == creator:
                    oc["creator_share_pct"] = round(share, 2)
                shares.append(share)
            if shares:
                oc["top10_adjusted_pct"] = round(sum(shares[:10]), 1)

        prev_oc = (prev_by_token.get(ta) or {}).get("onchain") or {}
        prev_h = prev_oc.get("holders_count")
        if oc["holders_count"] and prev_h:
            oc["holders_growth_pct_1h"] = round(
                100 * (oc["holders_count"] - prev_h) / prev_h, 2)
        c["onchain"] = oc


# ------------------------------------------------------- screening & scoring

def screen_and_score(c, scr, weights, bridge_flow_score):
    """Applica filtri handoff §9 e score parziale §7. Ritorna il candidato arricchito."""
    flags, cautions, notes = [], [], []
    liq = c["liquidity_usd"]
    vol = c["vol_h24"]
    tx24 = c["buys_h24"] + c["sells_h24"]
    mcap = c.get("market_cap_usd") or c.get("fdv_usd")

    if (c.get("token_symbol") or "").upper() in MAJORS:
        return None
    if liq < scr["min_liquidity_usd"]:
        return None  # sotto soglia minima: resta in discovery grezza, non mostrato
    if tx24 < scr["min_txns_h24"]:
        return None

    vol_liq = vol / liq if liq > 0 else 0
    buy_ratio = c["buys_h24"] / tx24 if tx24 > 0 else 0.5

    if vol_liq > scr["wash_vol_liq_ratio"]:
        flags.append(f"volume/liquidità anomalo ({vol_liq:.0f}x): possibile wash trading")
    if mcap and liq / mcap < scr["min_liq_mcap_ratio"]:
        flags.append(f"liquidità sottile vs market cap ({liq / mcap:.1%})")
    if tx24 > 100 and (buy_ratio > scr["extreme_buy_ratio"] or buy_ratio < 1 - scr["extreme_buy_ratio"]):
        flags.append(f"flusso unidirezionale estremo (buy ratio {buy_ratio:.0%})")
    if c.get("chg_h24") is not None and c["chg_h24"] > 1000 and liq < 50000:
        flags.append("pump estremo su liquidità esigua")

    age_h = c.get("age_hours")
    ultra_early = age_h is not None and age_h <= scr["ultra_early_hours"]
    early = age_h is not None and age_h <= scr["max_age_days_early"] * 24

    # --- Liquidity Score (componente automatizzabile, 0-100) — stima
    if liq >= scr["strong_liquidity_usd"]:
        liq_score = 90
    elif liq >= scr["watch_liquidity_usd"]:
        liq_score = 70
    elif liq >= 75000:
        liq_score = 55
    elif liq >= scr["min_liquidity_usd"]:
        liq_score = 35
    else:
        liq_score = 10
    if mcap and 0.02 <= liq / mcap <= 0.5:
        liq_score = min(100, liq_score + 10)

    # --- Social presence (proxy parziale della Social Velocity — stima debole)
    n_soc = len(c.get("socials", [])) + len(c.get("websites", []))
    social_score = min(100, n_soc * 30) if n_soc else None  # None = N/D

    # --- proxy on-chain (solo candidati arricchiti; altrimenti N/D)
    oc = c.get("onchain") or {}
    smart_money = holder_growth = deployer = None

    if oc.get("holders_count") is not None and oc.get("top10_adjusted_pct") is not None:
        # proxy "qualità della distribuzione/accumulo" (stima, non wallet-level)
        top10 = oc["top10_adjusted_pct"]
        s = 50
        if top10 <= 15:
            s += 25
        elif top10 <= 25:
            s += 15
        elif top10 > 50:
            s -= 35
        elif top10 > 35:
            s -= 15
        g = oc.get("holders_growth_pct_1h")
        if g is not None:
            s += 15 if g > 1 else (5 if g > 0 else -15)
        if 0.45 <= buy_ratio <= 0.70 and c["sells_h24"] >= 30:
            s += 10  # flusso bilanciato con vendite reali = mercato sano
        smart_money = max(0, min(100, s))

    if oc.get("holders_count") is not None:
        h = oc["holders_count"]
        holder_growth = 20 if h < 100 else 40 if h < 300 else \
            60 if h < 1000 else 75 if h < 3000 else 85
        g = oc.get("holders_growth_pct_1h")
        if g is not None:
            holder_growth = max(0, min(100, holder_growth
                                       + (15 if g > 1 else 5 if g > 0 else -20)))

    if oc.get("creator") is not None or oc.get("owner_status") is not None:
        deployer = 50
        cs = oc.get("creator_share_pct")
        if cs is not None:
            deployer += 20 if cs < 2 else (10 if cs < 5 else
                                           (-30 if cs > 20 else 0))
        ost = oc.get("owner_status")
        if ost in ("renounced", "assente"):
            deployer += 20
        elif ost and ost.startswith("attivo"):
            deployer -= 10
            cautions.append("owner attivo sul contratto (privilegi amministrativi "
                            "possibili — verificare)")
        if oc.get("contract_verified") is False:
            deployer -= 25
        deployer = max(0, min(100, deployer))

    components = {
        "smart_money": smart_money, "team_proximity": None,
        "holder_growth": holder_growth, "deployer": deployer,
        "github_dev": None, "liquidity": liq_score,
        "social_velocity": social_score, "bridge_flow": bridge_flow_score,
    }
    score, coverage = 0.0, 0.0
    for k, w in weights.items():
        v = components.get(k)
        if v is not None:
            score += w * v / 100.0
            coverage += w
    norm = round(100 * score / coverage, 1) if coverage else 0.0
    c["score_partial"] = round(score, 1)       # assoluto (compat storico)
    c["score_norm"] = norm                     # rinormalizzato sulla copertura
    c["score_coverage_pct"] = coverage
    c["score_components"] = components
    c["vol_liq_ratio"] = round(vol_liq, 2)
    c["buy_ratio"] = round(buy_ratio, 3)
    c["ultra_early"] = ultra_early

    # --- gate BUY ALERT: ogni requisito mancante viene elencato, mai taciuto
    ba = CONFIG["buy_alert"]
    missing = []
    if norm < ba["min_norm_score"]:
        missing.append(f"score {norm} < {ba['min_norm_score']}")
    if coverage < ba["min_coverage_pct"]:
        missing.append(f"copertura dati {coverage}% < {ba['min_coverage_pct']}%")
    if liq < ba["min_liquidity_usd"]:
        missing.append(f"liquidità ${liq:,.0f} < ${ba['min_liquidity_usd']:,}")
    if oc.get("contract_verified") is not True:
        missing.append("contratto non verificato (o verifica non disponibile)")
    if oc.get("owner_status") not in ("renounced", "assente"):
        missing.append("owner non rinunciato")
    t10 = oc.get("top10_adjusted_pct")
    if t10 is None or t10 > ba["max_top10_adjusted_pct"]:
        missing.append(f"top-10 aggiustata {t10}% oltre "
                       f"{ba['max_top10_adjusted_pct']}% (o N/D)")
    hc = oc.get("holders_count")
    if hc is None or hc < ba["min_holders"]:
        missing.append(f"holders {hc} < {ba['min_holders']} (o N/D)")
    if c["sells_h24"] < ba["min_sells_h24"]:
        missing.append(f"vendite reali 24h {c['sells_h24']} < "
                       f"{ba['min_sells_h24']} (sellability empirica)")
    if buy_ratio > ba["max_buy_ratio"]:
        missing.append(f"buy ratio {buy_ratio:.0%} troppo unidirezionale")
    if age_h is None or age_h < ba["min_age_hours"]:
        missing.append(f"età < {ba['min_age_hours']}h: dati insufficienti")
    if age_h is not None and age_h > ba["max_age_days"] * 24:
        missing.append(f"età > {ba['max_age_days']}g: non più early")
    if c.get("chg_h24") is not None and c["chg_h24"] < ba["max_chg24_drop_pct"]:
        missing.append(f"crollo in corso ({c['chg_h24']:.0f}%/24h)")
    if flags:
        missing.append("red flag presenti")
    c["buy_missing"] = missing
    c["red_flags"] = flags
    c["cautions"] = cautions

    material = [f for f in flags if "wash" in f or "pump" in f]
    if material:
        c["classification"] = "AVOID"
    elif not missing:
        c["classification"] = "ALPHA BUY ALERT"
    elif (norm >= 70 and coverage >= 40 and not flags
          and early and liq >= scr["watch_liquidity_usd"]
          and tx24 >= scr["hpw_txns_h24"]):
        c["classification"] = "HIGH-PRIORITY WATCH"
    elif early or liq >= scr["watch_liquidity_usd"]:
        c["classification"] = "WATCHLIST"
    else:
        c["classification"] = "DISCOVERY"
    notes.append("Team proximity e GitHub restano N/D (esclusi dalla "
                 "rinormalizzazione); smart money = proxy di distribuzione, "
                 "non analisi wallet-level.")
    c["notes"] = notes
    return c


# ------------------------------------------------------------------- wallet

TRANSFER_SIG = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def rpc_call(method, params, rpc_url, timeout=25):
    """JSON-RPC POST. Ritorna result o None."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1,
                       "method": method, "params": params}).encode()
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                rpc_url, data=body,
                headers={**UA, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
                d = json.loads(r.read().decode())
                if "error" in d:
                    print(f"[warn] RPC {method}: {d['error']}", file=sys.stderr)
                    return None
                return d.get("result")
        except Exception as e:
            if attempt == 2:
                print(f"[warn] RPC {method} fallita: {e}", file=sys.stderr)
                return None
            time.sleep(2)
    return None


def eth_call(to, data, rpc):
    return rpc_call("eth_call", [{"to": to, "data": data}, "latest"], rpc)


def decode_abi_string(hexres):
    """Decodifica il risultato di symbol(): stringa ABI o bytes32."""
    if not hexres or hexres == "0x":
        return None
    h = hexres[2:]
    try:
        if len(h) == 64:  # bytes32
            return bytes.fromhex(h).rstrip(b"\x00").decode("utf-8", "replace") or None
        length = int(h[64:128], 16)
        return bytes.fromhex(h[128:128 + length * 2]).decode("utf-8", "replace")
    except (ValueError, IndexError):
        return None


def rpc_token_meta(taddr, rpc):
    """(symbol, decimals) via eth_call — fallback quando Blockscout è giù."""
    sym = decode_abi_string(eth_call(taddr, "0x95d89b41", rpc)) or "?"
    decres = eth_call(taddr, "0x313ce567", rpc)
    try:
        dec = int(decres, 16) if decres and decres != "0x" else 18
    except ValueError:
        dec = 18
    return sym, dec


def fetch_wallet(wcfg):
    """Posizioni + operazioni del wallet.

    Fonte primaria Blockscout (dà anche i prezzi); l'istanza della chain è
    però instabile (500 intermittenti), quindi ogni pezzo ha un fallback
    on-chain via RPC ufficiale: balanceOf per i saldi, symbol()/decimals()
    per i metadati, eth_getBalance per il nativo.

    Il wallet può essere uno smart account EIP-7702: le transazioni classiche
    non partono dall'indirizzo, quindi le operazioni si ricostruiscono dagli
    eventi Transfer ERC-20 (entrambe le direzioni).
    """
    pc = CONFIG["primary_chain"]
    addr = wcfg["address"]
    explorer = pc["explorer"].rstrip("/")
    rpc = pc["rpc"]
    out = {"address": addr, "label": wcfg.get("label", "Wallet"),
           "explorer_url": f"{explorer}/address/{addr}",
           "native_eth": None, "eth_price_usd": None,
           "positions": [], "operations": [],
           "total_value_usd": None, "unpriced_positions": 0,
           "source_errors": []}

    # --- operazioni PRIMA (servono anche come fallback per le posizioni):
    #     eventi Transfer da/verso il wallet (fatto on-chain)
    padded = "0x" + "0" * 24 + addr[2:].lower()
    logs_in = rpc_call("eth_getLogs", [{"fromBlock": "0x0", "toBlock": "latest",
                                        "topics": [TRANSFER_SIG, None, padded]}], rpc)
    logs_out = rpc_call("eth_getLogs", [{"fromBlock": "0x0", "toBlock": "latest",
                                         "topics": [TRANSFER_SIG, padded]}], rpc)
    if logs_in is None and logs_out is None:
        out["source_errors"].append("rpc:eth_getLogs")
    all_logs = (logs_in or []) + (logs_out or [])
    touched_tokens = {l["address"].lower() for l in all_logs}

    # --- info indirizzo + saldo nativo (fatto)
    info = bs_json(f"{explorer}/api/v2/addresses/{addr}", retries=3)
    if info and isinstance(info, dict):
        out["native_eth"] = int(info.get("coin_balance") or 0) / 1e18
        out["eth_price_usd"] = fnum(info.get("exchange_rate"), None)
        out["is_smart_account"] = bool(info.get("is_contract"))
        impl = info.get("implementations") or []
        if impl:
            out["account_type"] = impl[0].get("name")
    else:
        out["source_errors"].append("blockscout:addresses(fallback rpc)")
        bal = rpc_call("eth_getBalance", [addr, "latest"], rpc)
        if bal:
            out["native_eth"] = int(bal, 16) / 1e18
        eth_px = http_json("https://coins.llama.fi/prices/current/coingecko:ethereum")
        out["eth_price_usd"] = fnum(((eth_px or {}).get("coins") or {})
                                    .get("coingecko:ethereum", {}).get("price"), None)

    # --- posizioni token (fatto; prezzo = stima)
    balances = bs_json(f"{explorer}/api/v2/addresses/{addr}/token-balances", retries=3)
    token_meta = {}  # addr_lower -> (symbol, decimals)
    positions = []
    if isinstance(balances, list):
        for t in balances:
            tok = t.get("token") or {}
            taddr = (tok.get("address_hash") or tok.get("address") or "").lower()
            dec = int(tok.get("decimals") or 18)
            qty = int(t.get("value") or 0) / 10 ** dec
            token_meta[taddr] = (tok.get("symbol") or "?", dec)
            positions.append({
                "symbol": tok.get("symbol") or "?",
                "name": tok.get("name"),
                "token_address": taddr,
                "qty": qty,
                "price_usd": fnum(tok.get("exchange_rate"), None),
                "price_source": "blockscout" if tok.get("exchange_rate") else None,
                "explorer_url": f"{explorer}/token/{taddr}",
            })
    else:
        # fallback on-chain: i token mai toccati dal wallet non possono avere
        # saldo; balanceOf sui token visti negli eventi Transfer
        out["source_errors"].append("blockscout:token-balances(fallback rpc)")
        for taddr in sorted(touched_tokens):
            balres = eth_call(taddr, "0x70a08231" + padded[2:], rpc)
            try:
                raw = int(balres, 16) if balres and balres != "0x" else 0
            except ValueError:
                raw = 0
            if raw == 0:
                continue
            sym, dec = rpc_token_meta(taddr, rpc)
            token_meta[taddr] = (sym, dec)
            positions.append({
                "symbol": sym, "name": None, "token_address": taddr,
                "qty": raw / 10 ** dec, "price_usd": None, "price_source": None,
                "explorer_url": f"{explorer}/token/{taddr}",
            })

    # --- prezzi mancanti via DexScreener (stima; segnala liquidità esigua)
    missing = [p["token_address"] for p in positions if p["price_usd"] is None]
    if missing:
        d = http_json(f"https://api.dexscreener.com/tokens/v1/"
                      f"{pc['dexscreener_id']}/{','.join(missing[:30])}")
        best = {}
        for pair in d or []:
            ta = ((pair.get("baseToken") or {}).get("address") or "").lower()
            liq = fnum((pair.get("liquidity") or {}).get("usd"))
            if ta and (ta not in best or liq > best[ta][0]):
                best[ta] = (liq, fnum(pair.get("priceUsd"), None))
        for p in positions:
            hit = best.get(p["token_address"])
            if p["price_usd"] is None and hit and hit[1]:
                p["price_usd"] = hit[1]
                p["price_source"] = "dexscreener"
                if hit[0] < CONFIG["screening"]["min_liquidity_usd"]:
                    p["price_warning"] = ("prezzo indicativo: liquidità del pool "
                                          f"esigua (${hit[0]:,.0f})")

    for p in positions:
        p["value_usd"] = (p["qty"] * p["price_usd"]
                          if p["price_usd"] is not None else None)
    priced = [p for p in positions if p["value_usd"] is not None]
    total = sum(p["value_usd"] for p in priced)
    if out["native_eth"] and out["eth_price_usd"]:
        total += out["native_eth"] * out["eth_price_usd"]
    out["total_value_usd"] = round(total, 2)
    out["unpriced_positions"] = len(positions) - len(priced)
    for p in priced:
        p["alloc_pct"] = round(100 * p["value_usd"] / total, 1) if total else None
    positions.sort(key=lambda p: -(p["value_usd"] or 0))
    out["positions"] = positions

    # --- operazioni: dagli eventi Transfer già recuperati
    events = [(l, "IN") for l in logs_in or []] + [(l, "OUT") for l in logs_out or []]
    events.sort(key=lambda e: int(e[0]["blockNumber"], 16), reverse=True)
    events = events[:25]

    # metadata token non in bilancio (usciti del tutto): Blockscout, poi RPC
    for l, _ in events:
        ta = l["address"].lower()
        if ta not in token_meta:
            tk = bs_json(f"{explorer}/api/v2/tokens/{ta}")
            if tk and isinstance(tk, dict) and tk.get("symbol"):
                token_meta[ta] = (tk.get("symbol"),
                                  int(tk.get("decimals") or 18))
            else:
                token_meta[ta] = rpc_token_meta(ta, rpc)

    block_ts = {}  # cache: blocco -> timestamp
    for l, _ in events:
        bn = l["blockNumber"]
        if bn not in block_ts:
            blk = rpc_call("eth_getBlockByNumber", [bn, False], rpc)
            block_ts[bn] = int(blk["timestamp"], 16) if blk else None

    price_by_addr = {p["token_address"]: p["price_usd"] for p in positions}
    for l, direction in events:
        ta = l["address"].lower()
        sym, dec = token_meta.get(ta, ("?", 18))
        qty = (int(l["data"], 16) / 10 ** dec) if l.get("data") not in (None, "0x") else 0
        other_topic = l["topics"][1] if direction == "IN" else l["topics"][2]
        counterparty = "0x" + other_topic[-40:]
        ts = block_ts.get(l["blockNumber"])
        price = price_by_addr.get(ta)
        out["operations"].append({
            "ts": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else None,
            "ts_local": (datetime.fromtimestamp(ts, tz=TZ).strftime("%d/%m/%Y %H:%M")
                         if ts else "N/D"),
            "direction": direction,
            "symbol": sym,
            "qty": qty,
            "value_usd_now": round(qty * price, 2) if price else None,
            "counterparty": counterparty,
            "tx_hash": l.get("transactionHash"),
            "tx_url": f"{explorer}/tx/{l.get('transactionHash')}",
        })

    # coppie IN+OUT nella stessa transazione = swap
    by_tx = {}
    for o in out["operations"]:
        by_tx.setdefault(o["tx_hash"], set()).add(o["direction"])
    for o in out["operations"]:
        o["is_swap"] = by_tx.get(o["tx_hash"]) == {"IN", "OUT"}
    return out


# ------------------------------------------------------------------ watchlist

def fetch_watchlist():
    out = []
    for w in CONFIG["watchlist"]:
        entry = {"name": w["name"], "handoff_state": w["handoff_state"],
                 "note": w["note"], "pair": None}
        d = http_json("https://api.dexscreener.com/latest/dex/search?q="
                      + urllib.parse.quote(w["query"]))
        pairs = (d or {}).get("pairs") or []
        want = {s.upper() for s in w.get("match_symbols", [])}

        def is_match(p):
            # solo simbolo esatto: il match sul nome produce falsi positivi
            # (es. meme che citano "lighter" nel nome) — handoff: non confondere
            # token simili con asset ufficialmente negoziabili
            sym = ((p.get("baseToken") or {}).get("symbol") or "").upper()
            return sym in want

        scoped = [p for p in pairs if p.get("chainId") == w["chain"] and is_match(p)]
        scoped.sort(key=lambda p: fnum((p.get("liquidity") or {}).get("usd")), reverse=True)
        if scoped:
            p = scoped[0]
            tx = (p.get("txns") or {}).get("h24") or {}
            entry["pair"] = {
                "symbol": (p.get("baseToken") or {}).get("symbol"),
                "token_address": (p.get("baseToken") or {}).get("address"),
                "dex": p.get("dexId"),
                "price_usd": p.get("priceUsd"),
                "liquidity_usd": fnum((p.get("liquidity") or {}).get("usd"), None),
                "vol_h24": fnum((p.get("volume") or {}).get("h24"), None),
                "chg_h24": (p.get("priceChange") or {}).get("h24"),
                "txns_h24": int(fnum(tx.get("buys")) + fnum(tx.get("sells"))),
                "mcap": p.get("marketCap"), "fdv": p.get("fdv"),
                "url": p.get("url"),
                "created_at": p.get("pairCreatedAt"),
            }
            liq = entry["pair"]["liquidity_usd"] or 0
            if liq < CONFIG["screening"]["min_liquidity_usd"]:
                entry["warning"] = (
                    "Coppia a liquidità esigua: possibile token non ufficiale o "
                    "copia. Il ticker corrisponde ma il contract NON è verificato "
                    "— non usare come conferma dell'esistenza di un token ufficiale.")
        else:
            entry["no_pair_reason"] = ("nessuna coppia con simbolo corrispondente "
                                       f"trovata su chain '{w['chain']}' "
                                       f"(query '{w['query']}')")
        out.append(entry)
    return out


# ------------------------------------------------------------ storico e delta

def load_previous(out_dir):
    """Carica lo stato precedente: prima dal sito pubblicato, poi da disco."""
    base = ""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if repo and "/" in repo:
        owner, name = repo.split("/", 1)
        base = f"https://{owner}.github.io/{name}"
    elif CONFIG.get("site_url"):
        base = CONFIG["site_url"].rstrip("/")
    prev, hist = None, []
    if base:
        prev = http_json(f"{base}/data/latest.json?cb={int(time.time())}")
        hist = http_json(f"{base}/data/history.json?cb={int(time.time())}") or []
    if prev is None:
        try:
            prev = json.load(open(os.path.join(out_dir, "latest.json")))
        except Exception:
            prev = None
    if not hist:
        try:
            hist = json.load(open(os.path.join(out_dir, "history.json")))
        except Exception:
            hist = []
    return prev, hist


def compute_deltas(current, previous):
    if not previous:
        return {"first_run": True, "entered": [], "exited": [], "reclassified": []}
    def keyset(cands):
        return {(c.get("token_address") or c.get("pool_address")): c for c in cands}
    cur, prv = keyset(current), keyset(previous.get("candidates", []))
    entered = [{"symbol": cur[k]["token_symbol"], "classification": cur[k]["classification"]}
               for k in cur.keys() - prv.keys()]
    exited = [{"symbol": prv[k]["token_symbol"], "was": prv[k]["classification"]}
              for k in prv.keys() - cur.keys()]
    recls = []
    for k in cur.keys() & prv.keys():
        if cur[k]["classification"] != prv[k]["classification"]:
            recls.append({"symbol": cur[k]["token_symbol"],
                          "from": prv[k]["classification"],
                          "to": cur[k]["classification"]})
    return {"first_run": False, "entered": entered, "exited": exited,
            "reclassified": recls}


# ------------------------------------------------------------------------ main

def main():
    out_dir = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else \
        os.path.join(ROOT, "site", "data")
    os.makedirs(out_dir, exist_ok=True)
    now = datetime.now(timezone.utc)
    scr = CONFIG["screening"]
    weights = CONFIG["score_weights"]

    print("[1/6] Stato chain (DefiLlama)…")
    status = fetch_chain_status()

    # proxy Bridge/Flow a livello chain: accelerazione del volume DEX (stima)
    bridge_flow = None
    if status["dex_vol_24h"] and status["dex_vol_7d"]:
        ratio = status["dex_vol_24h"] * 7 / status["dex_vol_7d"]
        bridge_flow = max(0, min(100, round(50 * ratio)))

    print("[2/6] Pool Robinhood Chain (GeckoTerminal)…")
    gt_id = CONFIG["primary_chain"]["geckoterminal_id"]
    pools, inc = gt_pools(gt_id, "new_pools", pages=2)
    tpools, tinc = gt_pools(gt_id, "trending_pools")
    inc.update(tinc)
    raw = [normalize_pool(p, inc, "robinhood") for p in pools + tpools]
    cands = dedupe_best_pool(raw)

    print("[3/6] Arricchimento DexScreener + on-chain (Blockscout/RPC)…")
    cands_pass = [c for c in cands
                  if c["liquidity_usd"] >= scr["min_liquidity_usd"]
                  and c["buys_h24"] + c["sells_h24"] >= scr["min_txns_h24"]]
    cands_pass.sort(key=lambda c: c["liquidity_usd"], reverse=True)
    enrich_dexscreener(cands_pass, CONFIG["primary_chain"]["dexscreener_id"])

    previous, history = load_previous(out_dir)
    prev_by_token = {(p.get("token_address") or "").lower(): p
                     for p in (previous or {}).get("candidates", [])}
    enrich_onchain(cands_pass, prev_by_token)

    screened = []
    for c in cands_pass:
        s = screen_and_score(c, scr, weights, bridge_flow)
        if s:
            screened.append(s)
    order = {"ALPHA BUY ALERT": -1, "HIGH-PRIORITY WATCH": 0, "WATCHLIST": 1,
             "DISCOVERY": 2, "AVOID": 3}
    screened.sort(key=lambda c: (order.get(c["classification"], 9),
                                 -c.get("score_norm", 0)))
    screened = screened[:CONFIG["max_candidates_shown"]]
    buys = [c for c in screened if c["classification"] == "ALPHA BUY ALERT"]

    print("[4/7] Watchlist handoff (DexScreener)…")
    watchlist = fetch_watchlist()

    print("[5/7] Wallet monitorati (Blockscout + RPC)…")
    wallets = [fetch_wallet(w) for w in CONFIG.get("wallets", [])]

    print("[6/7] Radar globale chain secondarie (GeckoTerminal)…")
    global_radar = []
    for net in CONFIG["secondary_networks"]:
        npools, ninc = gt_pools(net["geckoterminal_id"], "new_pools")
        nraw = [normalize_pool(p, ninc, net["label"]) for p in npools]
        ncands = dedupe_best_pool(nraw)
        kept = []
        for c in ncands:
            s = screen_and_score(c, scr, weights, bridge_flow)
            if s and s["classification"] in ("HIGH-PRIORITY WATCH", "WATCHLIST"):
                kept.append(s)
        kept.sort(key=lambda c: -c["score_partial"])
        global_radar.append({"network": net["label"],
                             "new_pools_seen": len(npools),
                             "candidates": kept[:5]})

    print("[7/7] Delta e storico…")
    deltas = compute_deltas(screened, previous)

    history.append({
        "ts": now.isoformat(),
        "tvl": status["tvl_usd"],
        "dex_vol_24h": status["dex_vol_24h"],
        "n_candidates": len(screened),
        "n_hpw": sum(1 for c in screened if c["classification"] == "HIGH-PRIORITY WATCH"),
        "n_buy": len(buys),
        "buy_symbols": [c["token_symbol"] for c in buys],
        "wallet_value": wallets[0]["total_value_usd"] if wallets else None,
    })
    history = history[-CONFIG["history_max_points"]:]

    n_hpw = sum(1 for c in screened if c["classification"] == "HIGH-PRIORITY WATCH")
    if buys:
        op_state = "ALPHA BUY ALERT"
        op_note = (f"{len(buys)} candidato/i superano tutti i gate automatici "
                   f"({', '.join(c['token_symbol'] or '?' for c in buys)}). "
                   "Segnale automatico, NON consulenza: eseguire lo script di "
                   "verifica finale (scripts/verifica_finale.py) prima di "
                   "qualunque decisione. Rischio di perdita totale presente.")
    else:
        op_state = "NO TRADE"
        op_note = (
            "Nessun candidato supera tutti i gate BUY automatici (score "
            "rinormalizzato ≥85, copertura ≥60%, contratto verificato, owner "
            "rinunciato, concentrazione e sellability nei limiti). Per ogni "
            "candidato la colonna Segnali elenca cosa manca.")
    latest = {
        "generated_at_utc": now.isoformat(),
        "generated_at_local": datetime.now(TZ).strftime("%d/%m/%Y %H:%M %Z"),
        "operational_state": op_state,
        "operational_note": op_note,
        "chain_status": status,
        "bridge_flow_score": bridge_flow,
        "candidates": screened,
        "n_hpw": n_hpw,
        "n_buy": len(buys),
        "watchlist": watchlist,
        "wallets": wallets,
        "global_radar": global_radar,
        "deltas": deltas,
    }

    with open(os.path.join(out_dir, "latest.json"), "w") as f:
        json.dump(latest, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "history.json"), "w") as f:
        json.dump(history, f)
    print(f"OK: {len(screened)} candidati ({n_hpw} HPW), "
          f"{len(watchlist)} watchlist, output in {out_dir}")


if __name__ == "__main__":
    main()
