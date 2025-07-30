import os
import json
import time
import discord
import requests
import asyncio
import csv
from discord.ext import commands
from discord import app_commands
import aiohttp
from aiohttp import web

# ====== Setup ======
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
TORN_API_KEY = "etqdem2Fp1VlhfGB"
GUILD_ID = 1352710920660582471  # Use raw int

if not TOKEN:
    raise ValueError("DISCORD_BOT_TOKEN is not set in environment variables.")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

TRACK_FOLDER = "tracked"
os.makedirs(TRACK_FOLDER, exist_ok=True)

# ====== Torn API (cached) ======
CACHE = {}
CACHE_DURATION = 60  # seconds

def fetch_user_cached(username, api_key):
    now = time.time()
    if username in CACHE and now - CACHE[username]['ts'] < CACHE_DURATION:
        return CACHE[username]['data']

    url = f"https://api.torn.com/user/{username}?selections=basic,stats,personalstats,networth&key={api_key}"
    res = requests.get(url)
    if res.status_code != 200:
        return None

    data = res.json()
    if 'error' in data:
        return None

    CACHE[username] = { 'ts': now, 'data': data }
    return data

# ====== Slash Command Sync ======
@bot.event
async def on_ready():
    await bot.wait_until_ready()
    try:
        await tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"✅ Slash commands synced to test server: {GUILD_ID}")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")

# ====== Commands ======
@tree.command(name="help", description="Show all commands and usage", guild=discord.Object(id=GUILD_ID))
async def help_command(interaction: discord.Interaction):
    msg = (
        "\U0001F4D6 **Bot Command Help**\n\n"
        "`/track [names]` — Track stat growth for one or more players.\n"
        "`/trackrole [role]` — Track all users in a Discord role.\n"
        "`/topgrowth` — See top stat gainers.\n"
        "`/cleartrack [name]` — Delete snapshot for a player.\n"
        "`/exporttrack` — Export all tracked data to CSV.\n"
        "`/status` — Check if the bot is responsive.\n"
        "`/help` — Show this help message."
    )
    await interaction.response.send_message(msg, ephemeral=True)

@tree.command(name="status", description="Check bot responsiveness", guild=discord.Object(id=GUILD_ID))
async def status(interaction: discord.Interaction):
    start = time.time()
    await interaction.response.defer(ephemeral=True)
    await asyncio.sleep(0.2)
    latency = (time.time() - start) * 1000
    await interaction.followup.send(f"✅ Bot is responsive! Ping: `{latency:.2f}ms`", ephemeral=True)

@tree.command(name="track", description="Track progress of players", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(names="One or more Torn usernames separated by space")
async def track(interaction: discord.Interaction, names: str):
    await interaction.response.defer(ephemeral=True)
    reports = []
    for name in names.split():
        data = fetch_user_cached(name, TORN_API_KEY)
        if not data:
            reports.append(f"❌ `{name}` — No data")
            continue

        profile = {
            "timestamp": int(time.time()),
            "level": data.get("level", 0),
            "total_stats": sum(data.get("battleStats", {}).values()),
            "money_earned": data.get("personalStats", {}).get("money_earned", 0),
            "refills": data.get("personalStats", {}).get("refills", 0),
            "drugs": data.get("personalStats", {}).get("drugs_used", 0),
            "revives": data.get("personalStats", {}).get("revives", 0),
            "net_worth": data.get("networth", {}).get("total", 0)
        }

        file_path = os.path.join(TRACK_FOLDER, f"{name.lower()}.json")
        if os.path.exists(file_path):
            with open(file_path, "r") as f:
                old = json.load(f)

            dt = int(time.time()) - old["timestamp"]
            age = f"{dt // 3600}h ago" if dt < 86400 else f"{dt // 86400}d ago"
            diff = {
                "stats": profile["total_stats"] - old["total_stats"],
                "cash": profile["money_earned"] - old["money_earned"],
                "refills": profile["refills"] - old["refills"],
                "drugs": profile["drugs"] - old["drugs"],
                "revives": profile["revives"] - old["revives"],
                "worth": profile["net_worth"] - old["net_worth"]
            }

            msg = (
                f"\ud83d\udcc8 **{name}** ({age}):\n"
                f"\u2022 Stats: +{diff['stats'] / 1_000_000:.1f}M\n"
                f"\u2022 Net Worth: +${diff['worth']:,}\n"
                f"\u2022 Cash Earned: +${diff['cash']:,}\n"
                f"\u2022 Drugs: +{diff['drugs']}, Refills: +{diff['refills']}, Revives: +{diff['revives']}"
            )
        else:
            msg = f"\ud83d\udd1c First snapshot saved for `{name}`. Use `/track {name}` later to see progress."

        with open(file_path, "w") as f:
            json.dump(profile, f, indent=2)

        reports.append(msg)

    await interaction.followup.send("\n\n".join(reports), ephemeral=True)

@tree.command(name="trackrole", description="Track all users in a Discord role", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(role="Discord role to track")
async def track_role(interaction: discord.Interaction, role: discord.Role):
    await interaction.response.defer(ephemeral=True)
    members = [member.display_name for member in role.members if not member.bot]
    if not members:
        await interaction.followup.send("❌ No members found in that role.", ephemeral=True)
        return
    await track(interaction, " ".join(members))

@tree.command(name="cleartrack", description="Clear snapshot for a player", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(name="Torn username")
async def cleartrack(interaction: discord.Interaction, name: str):
    file_path = os.path.join(TRACK_FOLDER, f"{name.lower()}.json")
    if os.path.exists(file_path):
        os.remove(file_path)
        await interaction.response.send_message(f"\ud83d\uddd1️ Snapshot for `{name}` deleted.", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ No snapshot found for `{name}`.", ephemeral=True)

@tree.command(name="exporttrack", description="Export all tracked data to CSV", guild=discord.Object(id=GUILD_ID))
async def exporttrack(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    rows = []
    for filename in os.listdir(TRACK_FOLDER):
        if filename.endswith(".json"):
            with open(os.path.join(TRACK_FOLDER, filename)) as f:
                data = json.load(f)
            rows.append({
                "name": filename[:-5],
                "level": data["level"],
                "total_stats": data["total_stats"],
                "money_earned": data["money_earned"],
                "refills": data["refills"],
                "drugs": data["drugs"],
                "revives": data["revives"],
                "net_worth": data["net_worth"]
            })

    if not rows:
        await interaction.followup.send("⚠️ No tracked data found.", ephemeral=True)
        return

    csv_file = "export.csv"
    with open(csv_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    await interaction.followup.send(file=discord.File(csv_file), ephemeral=True)

@tree.command(name="topgrowth", description="Top growing players", guild=discord.Object(id=GUILD_ID))
async def topgrowth(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    growths = []
    for filename in os.listdir(TRACK_FOLDER):
        with open(os.path.join(TRACK_FOLDER, filename)) as f:
            data = json.load(f)
        growths.append((filename[:-5], data["total_stats"]))

    top = sorted(growths, key=lambda x: x[1], reverse=True)[:10]
    msg = "\ud83c\udfc6 **Top Growth**\n\n" + "\n".join([
        f"`{i+1}.` {name} — {stats / 1_000_000:.1f}M" for i, (name, stats) in enumerate(top)
    ])
    await interaction.followup.send(msg, ephemeral=True)

# ====== Keep Alive Server ======
async def handle(request):
    return web.Response(text="Bot is running!")

async def start_webserver():
    app = web.Application()
    app.add_routes([web.get("/", handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT"))  # Must exist on Render
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# ====== Run ======
async def start_all():
    await start_webserver()
    try:
        await bot.start(TOKEN)
    except Exception as e:
        print(f"Bot failed to start: {e}")

asyncio.run(start_all())
