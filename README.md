# Discord Market-Price Bot

Type `!price NVDA` in a Discord channel and the bot replies — via a
**webhook** — with the current price and today's gain/loss. Quotes come
from Yahoo Finance's public endpoint (no API key, covers NASDAQ, NYSE,
AMEX, and more).

```
!price NVDA
!price AAPL MSFT TSLA      # up to 5 tickers at once
!randomfact               # a random trivia fact
!soccer                   # next 3 upcoming US (MLS) matches
!soccer seattle           # filter to one club (name or abbreviation)
!soccer LA Galaxy         # multi-word names work too
!worldcup                 # next 3 upcoming FIFA World Cup matches
!worldcup usa             # filter to one country
```

## Commands

| Command | What it does | Data source |
|---------|--------------|-------------|
| `!price <TICKER>` | Live price + today's gain/loss (up to 5 tickers) | Yahoo Finance |
| `!randomfact` | A random trivia fact | uselessfacts, falls back to catfact.ninja |
| `!soccer` | Next 3 upcoming MLS fixtures (kickoff in ET, venue, moneyline odds) | ESPN + The Odds API |
| `!soccer <team>` | Up to 5 upcoming fixtures for one club (matches name or abbreviation) | ESPN + The Odds API |
| `!worldcup` | Next 3 upcoming FIFA World Cup matches (kickoff in ET, venue, moneyline odds) | ESPN + The Odds API |
| `!worldcup <country>` | Up to 5 upcoming fixtures for one country | ESPN + The Odds API |

### Live odds for `!soccer`

Odds are optional. Set `ODDS_API_KEY` in `.env` with a free key from
[the-odds-api.com](https://the-odds-api.com/) (500 requests/month) and the
`!soccer` embed shows 3-way moneyline (home / draw / away) per match. Without
a key, fixtures still show — the odds line reads "not yet posted." Note that
books post MLS lines roughly 1–2 weeks before kickoff, so matches further out
may have no odds even with a key.

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
