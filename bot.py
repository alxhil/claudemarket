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
import datetime
import os
from zoneinfo import ZoneInfo

import discord
from discord.ext import tasks
from dotenv import load_dotenv

import strategy
from facts import NoFactAvailable, get_random_fact
from market import Quote, TickerNotFound, get_quote
from movers import MoversUnavailable, get_movers
from odds import american
from soccer import NoMatchesAvailable, get_upcoming_matches
from stats import StatsPreview, StatsUnavailable, get_stats_preview

load_dotenv()

BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
COMMAND_PREFIX = os.environ.get("COMMAND_PREFIX", "!price")
TRENDERS_COMMAND = os.environ.get("TRENDERS_COMMAND", "!trenders")
FACT_COMMAND = os.environ.get("FACT_COMMAND", "!randomfact")
SOCCER_COMMAND = os.environ.get("SOCCER_COMMAND", "!soccer")
WORLDCUP_COMMAND = os.environ.get("WORLDCUP_COMMAND", "!worldcup")
STATS_COMMAND = os.environ.get("STATS_COMMAND", "!stats")
STRATEGY_COMMAND = os.environ.get("STRATEGY_COMMAND", "!strategy")
HELP_COMMAND = os.environ.get("HELP_COMMAND", "!help")

MARKET_TZ = ZoneInfo("America/New_York")
SIGNAL_WEEKDAY = 4  # Friday
# Shortly after the 4:00pm ET close (Yahoo needs a few minutes to settle).
SIGNAL_TIME = datetime.time(hour=16, minute=15, tzinfo=MARKET_TZ)
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
BRAND_CORAL = 0xD97757

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


def _mover_lines(rows: list) -> str:
    if not rows:
        return "No data"
    out = []
    for m in rows:
        pct = f"{m.change_percent:+.2f}%" if m.change_percent is not None else "n/a"
        price = f"${m.price:,.2f}" if m.price is not None else "n/a"
        name = m.name or ""
        if len(name) > 22:
            name = name[:21] + "…"
        out.append(f"`{pct:>8}`  **{m.symbol}**  {price}  {name}".rstrip())
    return "\n".join(out)


def movers_embed() -> discord.Embed:
    gainers, losers = get_movers(count=5)
    embed = discord.Embed(title="Today's market movers", color=BLUE)
    embed.add_field(name="Top gainers", value=_mover_lines(gainers), inline=False)
    embed.add_field(name="Top losers", value=_mover_lines(losers), inline=False)
    embed.set_footer(text="US markets · data via Yahoo Finance")
    return embed


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


def _match_field_value(m) -> str:
    if m.is_live:
        detail = m.status_detail or "Live"
        head = f"LIVE · {detail}"
        if m.venue:
            head += f" · {m.venue}"
        hs = m.home_score if m.home_score is not None else "0"
        as_ = m.away_score if m.away_score is not None else "0"
        return f"{head}\n{m.home} {hs} – {as_} {m.away}"
    header = f"{m.when_str()} · {m.venue}" if m.venue else m.when_str()
    return f"{header}\n{_odds_line(m)}"


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
        embed.add_field(
            name=f"{m.home}  vs  {m.away}",
            value=_match_field_value(m),
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

    if m.is_live:
        detail = m.status_detail or "Live"
        header = (
            f"{preview.league_label} · LIVE {detail} · "
            f"{m.home} {m.home_score} – {m.away_score} {m.away}"
        )
    else:
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


def help_embed() -> discord.Embed:
    commands = [
        (f"{COMMAND_PREFIX} <ticker>", "Live stock price and today's gain/loss (up to 5 tickers)."),
        (TRENDERS_COMMAND, "Today's top 5 stock gainers and losers."),
        (FACT_COMMAND, "A random trivia fact."),
        (f"{SOCCER_COMMAND} [team]", "Upcoming MLS matches with odds; add a club to filter."),
        (f"{WORLDCUP_COMMAND} [team]", "Upcoming FIFA World Cup matches with odds; add a country to filter."),
        (f"{STATS_COMMAND} <team>", "Match preview: passing, possession, corners, and last head-to-head."),
        (f"{STRATEGY_COMMAND} <sub>", "Weekly QQQ trend signal — enable, disable, status, or check."),
        (HELP_COMMAND, "Show this list of commands."),
    ]
    embed = discord.Embed(
        title="ClaudeMarket — commands",
        description="Markets, trivia, and soccer, right in your channel.",
        color=BRAND_CORAL,
    )
    for usage, desc in commands:
        embed.add_field(name=usage, value=desc, inline=False)
    embed.set_footer(text="Data via Yahoo Finance, ESPN, The Odds API")
    return embed


def next_signal_run() -> datetime.datetime:
    now = datetime.datetime.now(MARKET_TZ)
    target = now.replace(
        hour=SIGNAL_TIME.hour, minute=SIGNAL_TIME.minute, second=0, microsecond=0
    )
    days_ahead = (SIGNAL_WEEKDAY - now.weekday()) % 7
    if days_ahead == 0 and now >= target:
        days_ahead = 7
    return target + datetime.timedelta(days=days_ahead)


def signal_embed(sig: strategy.Signal, *, dry_run: bool) -> discord.Embed:
    risk_on = sig.target == strategy.RISK_ASSET
    if sig.action == "HOLD":
        title = f"Hold {sig.target}"
    elif sig.action == "ENTER":
        title = f"Enter {sig.target}"
    else:
        title = f"Switch: sell {sig.previous}, buy {sig.target}"

    if risk_on:
        desc = "Risk-on — QQQ closed at least 1% above its 200-day average."
    elif sig.in_band:
        desc = (
            "QQQ is within 1% of its 200-day average — holding the current "
            "position (hysteresis band)."
        )
    else:
        desc = "Risk-off — QQQ closed more than 1% below its 200-day average."

    embed = discord.Embed(
        title=("[preview] " if dry_run else "") + title,
        description=desc,
        color=GREEN if risk_on else GREY,
    )
    embed.add_field(name="QQQ close", value=f"{sig.close:,.2f}", inline=True)
    embed.add_field(name="200-day SMA", value=f"{sig.sma200:,.2f}", inline=True)
    embed.add_field(name="Distance", value=f"{sig.distance_pct:+.1f}%", inline=True)
    if sig.defensive_scores:
        ranked = sorted(sig.defensive_scores.items(), key=lambda kv: -kv[1])
        embed.add_field(
            name="Defensive momentum (3/6/12-mo blend)",
            value="\n".join(f"{s}  {v:+.2%}" for s, v in ranked)
            + f"\n{strategy.CASH_ASSET} is the fallback if none are positive",
            inline=False,
        )
    footer = f"QQQ trend strategy · close of {sig.as_of} · signal, not financial advice"
    if dry_run:
        footer += " · dry run, state unchanged"
    embed.set_footer(text=footer)
    return embed


async def handle_strategy(channel, arg_str: str = "") -> None:
    sub = arg_str.strip().lower()
    state = strategy.load_state()

    if sub == "enable":
        state["enabled"] = True
        state["channel_id"] = channel.id
        strategy.save_state(state)
        when = next_signal_run().strftime("%A %b %d, %I:%M %p %Z")
        await send(
            channel,
            content=(
                "Weekly strategy signal **enabled** — I'll post the check in this "
                f"channel every Friday after the close. Next check: {when}."
            ),
        )
    elif sub == "disable":
        state["enabled"] = False
        strategy.save_state(state)
        await send(channel, content="Weekly strategy signal **disabled**.")
    elif sub == "status":
        lines = [
            f"Signal: {'**enabled**' if state.get('enabled') else '**disabled**'}",
            f"Position: {state.get('last_target') or '(none committed yet)'}",
            f"Last run: {state.get('last_run') or 'never'}",
        ]
        if state.get("enabled"):
            lines.append(
                "Next check: " + next_signal_run().strftime("%A %b %d, %I:%M %p %Z")
            )
        await send(channel, content="\n".join(lines))
    elif sub == "check":
        try:
            sig = await asyncio.to_thread(strategy.compute_signal, state)
        except Exception as exc:
            print(f"strategy check failed: {exc!r}")
            await send(
                channel,
                embeds=[
                    discord.Embed(
                        title="Strategy check failed",
                        description="Couldn't fetch market data — try again in a moment.",
                        color=GREY,
                    )
                ],
            )
            return
        await send(channel, embeds=[signal_embed(sig, dry_run=True)])
    else:
        await send(
            channel,
            content=f"Usage: `{STRATEGY_COMMAND} enable | disable | status | check`",
        )


@tasks.loop(time=SIGNAL_TIME)
async def weekly_signal() -> None:
    if datetime.datetime.now(MARKET_TZ).weekday() != SIGNAL_WEEKDAY:
        return
    state = strategy.load_state()
    if not state.get("enabled") or not state.get("channel_id"):
        return
    channel = client.get_channel(state["channel_id"])
    if channel is None:
        try:
            channel = await client.fetch_channel(state["channel_id"])
        except discord.HTTPException:
            print("weekly signal: channel unavailable")
            return
    try:
        sig = await asyncio.to_thread(strategy.compute_signal, state)
    except Exception as exc:
        print(f"weekly signal failed: {exc!r}")
        await send(
            channel,
            embeds=[
                discord.Embed(
                    title="Strategy signal failed",
                    description="Couldn't fetch market data. I'll retry next Friday; "
                    f"run `{STRATEGY_COMMAND} check` to preview manually.",
                    color=GREY,
                )
            ],
        )
        return
    strategy.commit(state, sig)
    await send(channel, content=sig.headline(), embeds=[signal_embed(sig, dry_run=False)])


async def send(
    channel: discord.abc.Messageable,
    *,
    embeds: list[discord.Embed] | None = None,
    content: str | None = None,
) -> None:
    # Reply in the channel the command came from (up to 10 embeds per message).
    try:
        await channel.send(content=content or None, embeds=embeds or [])
    except discord.Forbidden:
        name = getattr(channel, "name", getattr(channel, "id", "?"))
        print(f"Forbidden sending in #{name}")
        # Most likely missing 'Embed Links'; try a plain-text heads-up so the
        # failure isn't silent (needs only 'Send Messages').
        try:
            await channel.send(
                "I can't post here — please grant me **Send Messages** and "
                "**Embed Links** permission in this channel."
            )
        except discord.Forbidden:
            pass


@client.event
async def on_ready() -> None:
    print(
        f"Logged in as {client.user} — listening for "
        f"'{COMMAND_PREFIX} <TICKER>', '{TRENDERS_COMMAND}', '{FACT_COMMAND}', "
        f"'{SOCCER_COMMAND}', '{WORLDCUP_COMMAND}', '{STATS_COMMAND}', "
        f"'{STRATEGY_COMMAND}'"
    )
    if not weekly_signal.is_running():
        weekly_signal.start()


async def handle_price(channel, arg_str: str) -> None:
    args = arg_str.split()
    if not args:
        await send(channel, content=f"Usage: `{COMMAND_PREFIX} NVDA` (up to {MAX_TICKERS} tickers).")
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
    await send(channel, embeds=embeds)


async def handle_trenders(channel) -> None:
    try:
        embed = await asyncio.to_thread(movers_embed)
    except MoversUnavailable as exc:
        print(f"movers failed: {exc!r}")
        await send(
            channel,
            embeds=[
                discord.Embed(
                    title="Movers unavailable",
                    description="Couldn't fetch market movers right now — try again in a moment.",
                    color=GREY,
                )
            ],
        )
        return
    await send(channel, embeds=[embed])


async def handle_fact(channel) -> None:
    try:
        await send(channel, embeds=[fact_embed()])
    except NoFactAvailable as exc:
        print(f"fact lookup failed: {exc!r}")
        await send(
            channel,
            embeds=[
                discord.Embed(
                    title="No fact available",
                    description="Couldn't reach the fact service — try again in a moment.",
                    color=GREY,
                )
            ],
        )


async def handle_fixtures(channel, cfg: dict, arg_str: str = "") -> None:
    team = arg_str.strip() or None
    try:
        await send(channel, embeds=[fixtures_embed(cfg, team)])
    except NoMatchesAvailable as exc:
        print(f"{cfg['league']} lookup failed: {exc!r}")
        await send(
            channel,
            embeds=[
                discord.Embed(
                    title="Fixtures unavailable",
                    description="Couldn't reach the fixtures feed — try again in a moment.",
                    color=GREY,
                )
            ],
        )


async def handle_stats(channel, arg_str: str = "") -> None:
    query = arg_str.strip()
    if not query:
        await send(
            channel,
            content=f"Usage: `{STATS_COMMAND} <team>` — preview that team's next match "
            f"(e.g. `{STATS_COMMAND} seattle`).",
        )
        return
    try:
        # ~8 blocking HTTP calls — run off the event loop.
        preview = await asyncio.to_thread(get_stats_preview, query)
    except StatsUnavailable as exc:
        await send(
            channel,
            embeds=[
                discord.Embed(
                    title="No preview available",
                    description=str(exc),
                    color=GREY,
                )
            ],
        )
        return
    except Exception as exc:  # network / feed hiccup
        print(f"stats failed for {query!r}: {exc!r}")
        await send(
            channel,
            embeds=[
                discord.Embed(
                    title="Stats unavailable",
                    description="Couldn't build the preview right now — try again in a moment.",
                    color=GREY,
                )
            ],
        )
        return
    await send(channel, embeds=[stats_embed(preview)])


def matches(content_lower: str, command: str) -> bool:
    # Match the command as a whole word: exact, or followed by a space.
    return content_lower == command or content_lower.startswith(command + " ")


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return

    content = message.content.strip()
    lower = content.lower()
    channel = message.channel

    if matches(lower, HELP_COMMAND.lower()):
        await send(channel, embeds=[help_embed()])
    elif matches(lower, TRENDERS_COMMAND.lower()):
        await handle_trenders(channel)
    elif matches(lower, FACT_COMMAND.lower()):
        await handle_fact(channel)
    elif matches(lower, STRATEGY_COMMAND.lower()):
        await handle_strategy(channel, content[len(STRATEGY_COMMAND):])
    elif matches(lower, STATS_COMMAND.lower()):
        await handle_stats(channel, content[len(STATS_COMMAND):])
    elif matches(lower, WORLDCUP_COMMAND.lower()):
        await handle_fixtures(channel, COMPETITIONS["worldcup"], content[len(WORLDCUP_COMMAND):])
    elif matches(lower, SOCCER_COMMAND.lower()):
        await handle_fixtures(channel, COMPETITIONS["mls"], content[len(SOCCER_COMMAND):])
    elif matches(lower, COMMAND_PREFIX.lower()):
        await handle_price(channel, content[len(COMMAND_PREFIX):])


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit(
            "Missing required env var: DISCORD_BOT_TOKEN"
            "\nCopy .env.example to .env and fill it in."
        )
    client.run(BOT_TOKEN)


if __name__ == "__main__":
    main()
