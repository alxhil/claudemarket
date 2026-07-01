# Discord Market-Price Bot

Type `!price NVDA` in a Discord channel and the bot replies **in that same
channel** with the current price and today's gain/loss. Quotes come from
Yahoo Finance's public endpoint (no API key, covers NASDAQ, NYSE, AMEX,
and more).

The bot reads commands and posts replies over the gateway using its bot
token, so it needs **View Channel**, **Send Messages**, and **Embed Links**
permission in the channels where it's used.

```
!price NVDA
!price AAPL MSFT TSLA      # up to 5 tickers at once
!trenders                 # today's top 5 gainers and losers
!randomfact               # a random trivia fact
!soccer                   # next 3 upcoming US (MLS) matches
!soccer seattle           # filter to one club (name or abbreviation)
!soccer LA Galaxy         # multi-word names work too
!worldcup                 # next 3 upcoming FIFA World Cup matches
!worldcup usa             # filter to one country
!stats seattle            # preview a team's next match (passing, corners, H2H)
!help                     # list all commands
```

## Commands

| Command | What it does | Data source |
|---------|--------------|-------------|
| `!price <TICKER>` | Live price + today's gain/loss (up to 5 tickers) | Yahoo Finance |
| `!trenders` | Today's top 5 stock gainers and top 5 losers | Yahoo Finance |
| `!randomfact` | A random trivia fact | uselessfacts, falls back to catfact.ninja |
| `!soccer` | Next 3 upcoming MLS fixtures (kickoff in ET, venue, moneyline odds) | ESPN + The Odds API |
| `!soccer <team>` | Up to 5 upcoming fixtures for one club (matches name or abbreviation) | ESPN + The Odds API |
| `!worldcup` | Next 3 upcoming FIFA World Cup matches (kickoff in ET, venue, moneyline odds) | ESPN + The Odds API |
| `!worldcup <country>` | Up to 5 upcoming fixtures for one country | ESPN + The Odds API |
| `!stats <team>` | Preview a team's next match: passing %, possession, corners/game (recent-form averages), and the last H2H result | ESPN |
| `!help` | List all commands | — |

### `!stats` details

Finds the team's next fixture (searches World Cup, then MLS), then averages
each side's passing %, possession, and corners over their last 3 games with
recorded stats (ESPN doesn't track season corner totals, so recent per-match
boxscores are averaged instead). Also shows the outcome of the two teams' most
recent prior meeting. Runs several ESPN calls, so it's a touch slower than the
other commands.

### Live odds for `!soccer`

Odds are optional. Set `ODDS_API_KEY` in `.env` with a free key from
[the-odds-api.com](https://the-odds-api.com/) (500 requests/month) and the
`!soccer` embed shows 3-way moneyline (home / draw / away) per match. Without
a key, fixtures still show — the odds line reads "not yet posted." Note that
books post MLS lines roughly 1–2 weeks before kickoff, so matches further out
may have no odds even with a key.

## How it replies

The bot holds a gateway connection (via the **bot token**) to *read*
commands, and posts each reply back into the **same channel** the command
came from. No webhook needed — that's why it needs channel permissions
(View Channel, Send Messages, Embed Links) rather than a webhook URL.

## Setup

1. **Install deps**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create the bot** at <https://discord.com/developers/applications>
   - *New Application* → *Bot* → *Reset Token* → copy the token.
   - Under *Bot*, enable **MESSAGE CONTENT INTENT** (required to read commands).
   - Under *OAuth2 → URL Generator*: scope `bot`, permissions
     *View Channel* + *Send Messages* + *Embed Links*. Open the URL to invite it.

3. **Configure**
   ```bash
   cp .env.example .env
   # edit .env: paste DISCORD_BOT_TOKEN (and optional ODDS_API_KEY)
   ```

4. **Run**
   ```bash
   python bot.py
   ```

## Quick test of the data layer (no Discord needed)

```bash
python market.py NVDA
# NVDA (NasdaqGS): 123.45 USD  +2.10 (+1.73%)
```

## Files

- `bot.py` — gateway listener; replies in the originating channel.
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
