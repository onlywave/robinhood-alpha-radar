# 📡 Robinhood Chain — Alpha Radar

Dashboard statico di **intelligence early-stage** sulla Robinhood Chain (chain-id 4663)
e sugli ecosistemi crypto emergenti (Solana, Base, HyperEVM, Monad, MegaETH, Sui, Berachain).

Aggiornato **ogni ora** da GitHub Actions e pubblicato su GitHub Pages. Nessun server,
nessuna API key: solo fonti pubbliche gratuite.

## Cosa fa

- **Stato della chain**: TVL, volume DEX 24h/7g, protocolli principali (DefiLlama)
- **Discovery candidati**: nuovi pool e pool in trend su Robinhood Chain (GeckoTerminal),
  arricchiti con socials/website (DexScreener)
- **Screening automatico** (handoff §9): liquidità minima, transazioni, rapporto
  volume/liquidità (anti-wash), coerenza liquidità/market-cap, flusso buy/sell
- **Score parziale** con i pesi dell'handoff §7 e **copertura dati dichiarata**
- **Watchlist handoff**: CASHCAT, 4663 (benchmark), LIT/Lighter, Arcus
- **Portafoglio wallet monitorato**: posizioni on-chain con prezzi e allocazione,
  operazioni ricostruite dagli eventi Transfer (supporta smart account EIP-7702),
  campo "capitale pronto da investire" salvato solo nel browser (localStorage).
  Fonte primaria Blockscout con fallback completo su RPC ufficiale
  (`balanceOf`, `symbol()`, `eth_getLogs`)
- **Delta tra scansioni**: entrati / usciti / riclassificati
- **Radar globale**: nuovi pool oltre screening sulle chain secondarie

## BUY ALERT automatici (v2) e loro limiti

Lo score è **rinormalizzato sulla copertura dati reale**. Componenti lette
on-chain (Blockscout + RPC ufficiale): verifica contratto, owner()/renounce,
deployer e sua quota, holder count e crescita, concentrazione top-10 aggiustata
(esclusi pool/burn/contratto), sellability empirica (vendite reali osservate).
Smart money = proxy di qualità della distribuzione (non analisi wallet-level);
team proximity e GitHub restano N/D ed esclusi dalla rinormalizzazione
(copertura massima ~80%).

Un candidato diventa **ALPHA BUY ALERT** solo superando TUTTI i gate:
score ≥85, copertura ≥60%, liquidità ≥$150k, contratto verificato, owner
rinunciato/assente, top-10 aggiustata ≤30%, ≥300 holder, ≥50 vendite reali/24h,
flusso non unidirezionale, età 24h–30g, nessuna red flag. Per ogni candidato
sotto soglia il campo `buy_missing` elenca esattamente cosa manca.

**Un BUY ALERT è un segnale automatico fallibile, non una raccomandazione.**
Prima di qualunque decisione va eseguita la verifica finale:

```bash
python3 scripts/verifica_finale.py 0xTOKEN
```

che controlla slippage stimato, proxy/upgradeability, distribuzione holder con
etichette, quota deployer, venditori distinti on-chain (~24h) e GoPlus (quando
la chain sarà supportata). Restano manuali: LP lock/burn, bundle/sniper
forensics, cluster di wallet, team, catalizzatori. Il sistema non esegue
transazioni. Rischio di perdita totale sempre presente.

## Classificazioni

| Livello | Significato |
|---|---|
| `ALPHA BUY ALERT` | tutti i gate automatici superati — richiede comunque verifica finale manuale |
| `HIGH-PRIORITY WATCH` | score ≥70 e metriche forti, uno o più gate BUY mancanti |
| `WATCHLIST` | oltre screening, dati insufficienti o rischio elevato |
| `DISCOVERY` | oltre soglie minime, solo lista grezza |
| `AVOID` | red flag automatica materiale (wash-like, pump su liquidità esigua) |

## Architettura

```
scanner/scan.py    # Python stdlib-only: fetch → screening → scoring → JSON
site/              # dashboard statico (vanilla JS)
site/data/         # output locale di test (non versionato)
.github/workflows/scan-and-deploy.yml  # cron orario → build → GitHub Pages
```

Lo storico tra le esecuzioni viene recuperato dal sito pubblicato
(`data/history.json`), quindi il repo non accumula commit di dati.

## Esecuzione locale

```bash
python3 scanner/scan.py          # scrive site/data/
cd site && python3 -m http.server 8080
# → http://localhost:8080
```

## Fonti

[DefiLlama](https://defillama.com) · [GeckoTerminal](https://www.geckoterminal.com) ·
[DexScreener](https://dexscreener.com) — API pubbliche, rate-limit rispettati.

## Disclaimer

Strumento di discovery (Livello 1–2 del flusso decisionale dell'handoff): produce
liste grezze e watchlist, mai decisioni operative. I token early-stage comportano
rischio di perdita totale. Niente in questo repository costituisce consulenza
finanziaria.
