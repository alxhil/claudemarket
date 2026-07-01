"""Discord market bot.

Listens for commands via the gateway and posts replies through an
incoming Discord *webhook* (giving them a custom name/avatar).
Requires a bot token AND a webhook URL.

    !price NVDA
    !price AAPL MSFT TSLA      # up to 5 at once
    !randomfact               # a random trivia fact

Setup: see README.md.
"""

from __future__ import annotations

import os

import aiohttp
import discord
from dotenv import load_dotenv

from facts import NoFactAvailable, get_random_fact
from market import Quote, TickerNotFound, get_quote

load_dotenv()

BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
COMMAND_PREFIX = os.environ.get("COMMAND_PREFIX", "!price")
FACT_COMMAND = os.environ.get("FACT_COMMAND", "!randomfact")
WEBHOOK_USERNAME = os.environ.get("WEBHOOK_USERNAME", "Market Bot")
MAX_TICKERS = 5

GREEN = 0x2ECC71
RED = 0xE74C3C
GREY = 0x95A5A6
BLUE = 0x5865F2

intents = discord.Intents.default()
intents.message_content = True  # required to read command text
client = discord.Client(intents=intents)


def build_embed(q: Quote) -> discord.Embed:
    up = q.change >= 0
    arrow = "📈" if up else "📉"
    sign = "+" if up else ""
    color = GREEN if q.change > 0 else RED if q.change < 0 else GREY

    title = f"{arrow} {q.symbol}"
    if q.name:
        title += f" — {q.name}"

    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="Price", value=f"{q.price:,.2f} {q.currency}", inline=True)
    embed.add_field(
        name="Change",
        value=f"{sign}{q.change:,.2f} ({sign}{q.change_percent:.2f}%)",
        inline=True,
    )
    embed.add_field(name="Prev close", value=f"{q.previous_close:,.2f}", inline=True)
    if q.exchange:
        embed.set_footer(text=f"{q.exchange} • data via Yahoo Finance")
    return embed


def error_embed(symbol: str) -> discord.Embed:
    return discord.Embed(
        title=f"❔ Couldn't find “{symbol}”",
        description="No market data for that ticker. Check the symbol and try again.",
        color=GREY,
    )


def fact_embed() -> discord.Embed:
    fact = get_random_fact()
    embed = discord.Embed(
        title="💡 Random fact",
        description=fact.text,
        color=BLUE,
    )
    embed.set_footer(text=f"via {fact.source}")
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
        f"'{COMMAND_PREFIX} <TICKER>' and '{FACT_COMMAND}'"
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
                    title=f"⚠️ Error fetching {sym.upper()}",
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
                    title="⚠️ No fact right now",
                    description="Couldn't reach the fact service — try again in a moment.",
                    color=GREY,
                )
            ]
        )


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
