"""Discord market bot.

Listens for commands via the gateway and posts replies through an
incoming Discord *webhook* (giving them a custom name/avatar).
Requires a bot token AND a webhook URL.

    !price NVDA
    !price AAPL MSFT TSLA      # up to 5 at once
    !randomfact               # a random trivia fact
    !soccer                   # upcoming US (MLS) matches

Setup: see README.md.
"""

from __future__ import annotations

import asyncio
import os

import aiohttp
import discord
from dotenv import load_dotenv

from facts import NoFactAvailable, get_random_fact
from market import Quote, TickerNotFound, get_quote
from odds import american
from soccer import NoMatchesAvailable, get_upcoming_matches
from stats import StatsPreview, StatsUnavailable, get_stats_preview

load_dotenv()

BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
COMMAND_PREFIX = os.environ.get("COMMAND_PREFIX", "!price")
FACT_COMMAND = os.environ.get("FACT_COMMAND", "!randomfact")
SOCCER_COMMAND = os.environ.get("SOCCER_COMMAND", "!soccer")
WORLDCUP_COMMAND = os.environ.get("WORLDCUP_COMMAND", "!worldcup")
STATS_COMMAND = os.environ.get("STATS_COMMAND", "!stats")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")
WEBHOOK_USERNAME = os.environ.get("WEBHOOK_USERNAME", "Market Bot")
MAX_TICKERS = 5
SOCCER_LIMIT = 3
SOCCER_TEAM_LIMIT = 5

GREEN = 0x2ECC71
RED = 0xE74C3C
GREY = 0x95A5A6
BLUE = 0x5865F2
SOCCER_GREEN = 0x1A7F37
WORLDCUP_GOLD = 0xC8A24B

COMPETITIONS = {
    "mls": {
        "title": "Upcoming MLS matches",
        "competition": "Major League Soccer",
        "league": "usa.1",
        "odds_sport": "soccer_usa_mls",
        "color": SOCCER_GREEN,
        "hint": "Try a club name like `Seattle`, `LA Galaxy`, or `Miami`.",
    },
    "worldcup": {
        "title": "Upcoming World Cup matches",
        "competition": "FIFA World Cup",
        "league": "fifa.world",
        "odds_sport": "soccer_fifa_world_cup",
        "color": WORLDCUP_GOLD,
        "hint": "Try a country like `Brazil`, `France`, or `USA`.",
    },
}

intents = discord.Intents.default()
intents.message_content = True  # required to read command text
client = discord.Client(intents=intents)


def build_embed(q: Quote) -> discord.Embed:
    sign = "+" if q.change >= 0 else ""
    color = GREEN if q.change > 0 else RED if q.change < 0 else GREY

    title = q.symbol if not q.name else f"{q.symbol} — {q.name}"

    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="Price", value=f"{q.price:,.2f} {q.currency}", inline=True)
    embed.add_field(
        name="Change",
        value=f"{sign}{q.change:,.2f} ({sign}{q.change_percent:.2f}%)",
        inline=True,
    )
    embed.add_field(name="Prev close", value=f"{q.previous_close:,.2f}", inline=True)
    if q.exchange:
        embed.set_footer(text=f"{q.exchange} · Yahoo Finance")
    return embed


def error_embed(symbol: str) -> discord.Embed:
    return discord.Embed(
        title=f"{symbol} not found",
        description="No market data for that ticker. Check the symbol and try again.",
        color=GREY,
    )


def fact_embed() -> discord.Embed:
    fact = get_random_fact()
    embed = discord.Embed(
        title="Random fact",
        description=fact.text,
        color=BLUE,
    )
    embed.set_footer(text=f"via {fact.source}")
    return embed


def _odds_line(m) -> str:
    if not m.odds:
        return "Odds not yet posted"
    o = m.odds
    book = f"   ({o.book})" if o.book else ""
    return (
        f"{m.home} {american(o.home_ml)}   "
        f"Draw {american(o.draw_ml)}   "
        f"{m.away} {american(o.away_ml)}{book}"
    )


def fixtures_embed(cfg: dict, team: str | None = None) -> discord.Embed:
    limit = SOCCER_TEAM_LIMIT if team else SOCCER_LIMIT
    matches = get_upcoming_matches(
        limit=limit,
        team=team,
        league=cfg["league"],
        odds_sport=cfg["odds_sport"],
        odds_api_key=ODDS_API_KEY,
    )
    embed = discord.Embed(color=cfg["color"])

    if not matches:
        embed.title = cfg["title"]
        if team:
            embed.description = f"No upcoming matches found for **{team}**.\n{cfg['hint']}"
        else:
            embed.description = "No upcoming matches found right now."
        return embed

    if team:
        label = matches[0].team_label(team) or team
        embed.title = f"{label} — upcoming matches"
    else:
        embed.title = cfg["title"]

    for m in matches:
        when = m.when_str()
        header = f"{when} · {m.venue}" if m.venue else when
        embed.add_field(
            name=f"{m.home}  vs  {m.away}",
            value=f"{header}\n{_odds_line(m)}",
            inline=False,
        )

    tail = "odds via The Odds API" if ODDS_API_KEY else "set ODDS_API_KEY for odds"
    embed.set_footer(text=f"{cfg['competition']} · fixtures via ESPN · {tail}")
    return embed


def _form_value(f) -> str:
    if not f.games:
        return "No recent stats available"

    def pct(x):
        return f"{x:.1f}%" if x is not None else "n/a"

    corners = f"{f.corners:.1f}/g" if f.corners is not None else "n/a"
    return (
        f"Passing  {pct(f.pass_pct)}\n"
        f"Possession  {pct(f.possession)}\n"
        f"Corners  {corners}"
    )


def stats_embed(preview: StatsPreview) -> discord.Embed:
    m = preview.match
    embed = discord.Embed(title=f"{m.home}  vs  {m.away}", color=BLUE)

    header = f"{preview.league_label} · {m.when_str()}"
    if m.venue:
        header += f" · {m.venue}"
    embed.description = header

    embed.add_field(name=m.home, value=_form_value(preview.home_form), inline=True)
    embed.add_field(name=m.away, value=_form_value(preview.away_form), inline=True)

    if preview.last_meeting:
        lm = preview.last_meeting
        comp = f"  ({lm.competition})" if lm.competition else ""
        value = f"{lm.date:%b %d, %Y} — {lm.summary}{comp}"
    else:
        value = "No previous meeting on record"
    embed.add_field(name="Last meeting", value=value, inline=False)

    embed.set_footer(text="Team averages over recent games · data via ESPN")
    return embed


async def send(*, embeds: list[discord.Embed] | None = None, content: str | None = None) -> None:
    # Discord allows up to 10 embeds per message.
    async with aiohttp.ClientSession() as session:
        webhook = discord.Webhook.from_url(WEBHOOK_URL, session=session)
        await webhook.send(
            username=WEBHOOK_USERNAME,
            embeds=embeds or [],
            content=content or "",
            wait=True,
        )


@client.event
async def on_ready() -> None:
    print(
        f"Logged in as {client.user} — listening for "
        f"'{COMMAND_PREFIX} <TICKER>', '{FACT_COMMAND}', "
        f"'{SOCCER_COMMAND}', '{WORLDCUP_COMMAND}', '{STATS_COMMAND}'"
    )


async def handle_price(arg_str: str) -> None:
    args = arg_str.split()
    if not args:
        await send(content=f"Usage: `{COMMAND_PREFIX} NVDA` (up to {MAX_TICKERS} tickers).")
        return

    embeds: list[discord.Embed] = []
    for sym in args[:MAX_TICKERS]:
        try:
            embeds.append(build_embed(get_quote(sym)))
        except TickerNotFound:
            embeds.append(error_embed(sym.upper()))
        except Exception as exc:  # network / Yahoo hiccup
            print(f"lookup failed for {sym}: {exc!r}")
            embeds.append(
                discord.Embed(
                    title=f"Error fetching {sym.upper()}",
                    description="The market data service is unavailable right now.",
                    color=GREY,
                )
            )
    await send(embeds=embeds)


async def handle_fact() -> None:
    try:
        await send(embeds=[fact_embed()])
    except NoFactAvailable as exc:
        print(f"fact lookup failed: {exc!r}")
        await send(
            embeds=[
                discord.Embed(
                    title="No fact available",
                    description="Couldn't reach the fact service — try again in a moment.",
                    color=GREY,
                )
            ]
        )


async def handle_fixtures(cfg: dict, arg_str: str = "") -> None:
    team = arg_str.strip() or None
    try:
        await send(embeds=[fixtures_embed(cfg, team)])
    except NoMatchesAvailable as exc:
        print(f"{cfg['league']} lookup failed: {exc!r}")
        await send(
            embeds=[
                discord.Embed(
                    title="Fixtures unavailable",
                    description="Couldn't reach the fixtures feed — try again in a moment.",
                    color=GREY,
                )
            ]
        )


async def handle_stats(arg_str: str = "") -> None:
    query = arg_str.strip()
    if not query:
        await send(
            content=f"Usage: `{STATS_COMMAND} <team>` — preview that team's next match "
            f"(e.g. `{STATS_COMMAND} seattle`)."
        )
        return
    try:
        # ~8 blocking HTTP calls — run off the event loop.
        preview = await asyncio.to_thread(get_stats_preview, query)
    except StatsUnavailable as exc:
        await send(
            embeds=[
                discord.Embed(
                    title="No preview available",
                    description=str(exc),
                    color=GREY,
                )
            ]
        )
        return
    except Exception as exc:  # network / feed hiccup
        print(f"stats failed for {query!r}: {exc!r}")
        await send(
            embeds=[
                discord.Embed(
                    title="Stats unavailable",
                    description="Couldn't build the preview right now — try again in a moment.",
                    color=GREY,
                )
            ]
        )
        return
    await send(embeds=[stats_embed(preview)])


def matches(content_lower: str, command: str) -> bool:
    # Match the command as a whole word: exact, or followed by a space.
    return content_lower == command or content_lower.startswith(command + " ")


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return

    content = message.content.strip()
    lower = content.lower()

    if matches(lower, FACT_COMMAND.lower()):
        await handle_fact()
    elif matches(lower, STATS_COMMAND.lower()):
        await handle_stats(content[len(STATS_COMMAND):])
    elif matches(lower, WORLDCUP_COMMAND.lower()):
        await handle_fixtures(COMPETITIONS["worldcup"], content[len(WORLDCUP_COMMAND):])
    elif matches(lower, SOCCER_COMMAND.lower()):
        await handle_fixtures(COMPETITIONS["mls"], content[len(SOCCER_COMMAND):])
    elif matches(lower, COMMAND_PREFIX.lower()):
        await handle_price(content[len(COMMAND_PREFIX):])


def main() -> None:
    missing = [
        name
        for name, val in (
            ("DISCORD_BOT_TOKEN", BOT_TOKEN),
            ("DISCORD_WEBHOOK_URL", WEBHOOK_URL),
        )
        if not val
    ]
    if missing:
        raise SystemExit(
            "Missing required env vars: "
            + ", ".join(missing)
            + "\nCopy .env.example to .env and fill them in."
        )
    client.run(BOT_TOKEN)


if __name__ == "__main__":
    main()
