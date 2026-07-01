# Discord Market-Price Bot

Type `!price NVDA` in a Discord channel and the bot replies — via a
**webhook** — with the current price and today's gain/loss. Quotes come
from Yahoo Finance's public endpoint (no API key, covers NASDAQ, NYSE,
AMEX, and more).

```
!price NVDA
!price AAPL MSFT TSLA      # up to 5 tickers at once
!randomfact               # a random trivia fact
!soccer                   # upcoming US (MLS) matches
```

## Commands

| Command | What it does | Data source |
|---------|--------------|-------------|
| `!price <TICKER>` | Live price + today's gain/loss (up to 5 tickers) | Yahoo Finance |
| `!randomfact` | A random trivia fact | uselessfacts, falls back to catfact.ninja |
| `!soccer` | Next 6 upcoming MLS fixtures (kickoff in ET + venue) | ESPN |

## Why both a bot token *and* a webhook?

A Discord webhook can only **send** messages into a channel — it cannot
**read** what users type. So it alone can't see `!price NVDA`. This bot
uses a lightweight gateway connection (the **bot token**) to *read*
commands, and posts the formatted reply through an **incoming webhook**
(which is what gives the replies their custom name/avatar).

## Setup

1. **Install deps**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create the bot** at <https://discord.com/developers/applications>
   - *New Application* → *Bot* → *Reset Token* → copy the token.
   - Under *Bot*, enable **MESSAGE CONTENT INTENT** (required to read commands).
   - Under *OAuth2 → URL Generator*: scope `bot`, permissions
     *Send Messages* + *Read Message History*. Open the URL to invite it.

3. **Create the webhook** in the target channel
   - *Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL*.

4. **Configure**
   ```bash
   cp .env.example .env
   # edit .env: paste DISCORD_BOT_TOKEN and DISCORD_WEBHOOK_URL
   ```

5. **Run**
   ```bash
   python bot.py
   ```

## Quick test of the data layer (no Discord needed)

```bash
python market.py NVDA
# NVDA (NasdaqGS): 123.45 USD  +2.10 (+1.73%)
```

## Files

- `bot.py` — gateway listener + webhook poster.
- `market.py` — Yahoo Finance quote lookup (importable / runnable standalone).
- `.env.example` — config template.

## Notes

- Prices are real-time-ish (delayed per Yahoo's terms); change % is vs the
  previous regular-session close.
- Works for ETFs, indices (`^GSPC`), FX (`EURUSD=X`), and crypto (`BTC-USD`)
  too, since those are all valid Yahoo symbols.
- Yahoo's endpoint is unofficial; for guaranteed SLAs use a keyed provider
  (Finnhub, Alpha Vantage, Twelve Data) — swap the implementation in
  `market.get_quote`.
