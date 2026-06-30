"""Discord market-price bot.

Listens for ``!price <TICKER>`` commands via the gateway and posts the
reply through an incoming Discord *webhook* (giving the replies a custom
name/avatar). Requires a bot token AND a webhook URL.

    !price NVDA
    !price AAPL MSFT TSLA      # up to 5 at once

Setup: see README.md.
"""

from __future__ import annotations

import os

import aiohttp
import discord
from dotenv import load_dotenv

from market import Quote, TickerNotFound, get_quote

load_dotenv()

BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
COMMAND_PREFIX = os.environ.get("COMMAND_PREFIX", "!price")
WEBHOOK_USERNAME = os.environ.get("WEBHOOK_USERNAME", "Market Bot")
MAX_TICKERS = 5

GREEN = 0x2ECC71
RED = 0xE74C3C
GREY = 0x95A5A6

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


async def post(webhook: discord.Webhook, embeds: list[discord.Embed]) -> None:
    # Discord allows up to 10 embeds per message.
    await webhook.send(
        username=WEBHOOK_USERNAME,
        embeds=embeds,
        wait=True,
    )


@client.event
async def on_ready() -> None:
    print(f"Logged in as {client.user} — listening for '{COMMAND_PREFIX} <TICKER>'")


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return

    content = message.content.strip()
    if not content.lower().startswith(COMMAND_PREFIX.lower()):
        return

    args = content[len(COMMAND_PREFIX):].split()
    if not args:
        async with aiohttp.ClientSession() as session:
            webhook = discord.Webhook.from_url(WEBHOOK_URL, session=session)
            await webhook.send(
                username=WEBHOOK_USERNAME,
                content=f"Usage: `{COMMAND_PREFIX} NVDA` (up to {MAX_TICKERS} tickers).",
            )
        return

    symbols = args[:MAX_TICKERS]
    embeds: list[discord.Embed] = []
    for sym in symbols:
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

    async with aiohttp.ClientSession() as session:
        webhook = discord.Webhook.from_url(WEBHOOK_URL, session=session)
        await post(webhook, embeds)


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
