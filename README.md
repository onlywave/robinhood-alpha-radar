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
- **Delta tra scansioni**: entrati / usciti / riclassificati
- **Radar globale**: nuovi pool oltre screening sulle chain secondarie

## Cosa NON fa (per design)

Il sistema **non emette mai BUY ALERT in autonomia**. Le componenti di score che
richiedono verifica manuale o fonti a pagamento valgono N/D e sono dichiarate:
smart money, team proximity, holder growth, deployer history, bundle/sniper,
GitHub activity. La classificazione massima automatica è **HIGH-PRIORITY WATCH**.

Non verifica contract/honeypot/sellability/LP-lock, non analizza wallet,
non esegue transazioni, non dà raccomandazioni. Stato operativo di default:
**NO TRADE**. Nessun segnale è una certezza.

## Classificazioni

| Livello | Significato |
|---|---|
| `HIGH-PRIORITY WATCH` | metriche disponibili eccellenti, trigger mancanti da verificare a mano |
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
