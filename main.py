import os
import json
import time
import asyncio
import discord
import requests
import csv
from discord.ext import commands
from discord import app_commands

# ====== Setup ======
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
TORN_API_KEY = "etqdem2Fp1VlhfGB"
GUILD_ID = discord.Object(id=1352710920660582471)  # your server ID

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

TRACK_FOLDER = "tracked"
os.makedirs(TRACK_FOLDER, exist_ok=True)

# ====== Torn API Helpers ======
CACHE = {}
CACHE_DURATION = 60  # seconds

def get_torn_user(name):
    url = f"https://api.torn.com/user/{name}?search=true&selections=basic&key={TORN_API_KEY}"
    res = requests.get(url)
    if res.status_code != 200:
        return None
    data = res.json()
    return data.get("player_id")

def fetch_user_cached(player_id):
    now = time.time()
    if player_id in CACHE and now - CACHE[player_id]['ts'] < CACHE_DURATION:
        return CACHE[player_id]['data']

    url = f"https://api.torn.com/user/{player_id}?selections=basic,stats,personalstats,networth&key={TORN_API_KEY}"
    res = requests.get(url)
    if res.status_code != 200:
        return None

    data = res.json()
    if 'error' in data:
        return None

    CACHE[player_id] = { 'ts': now, 'data': data }
    return data

# ====== on_ready to sync commands ======
@bot.event
async def on_ready():
    try:
        await tree.sync(guild=GUILD_ID)
        print(f"✅ Slash commands synced to server: {GUILD_ID.id}")
    except Exception as e:
        print(f"❌ Command sync failed: {e}")

# ====== Commands ======
@tree.command(name="help", description="Show all commands and usage", guild=GUILD_ID)
async def help_command(interaction: discord.Interaction):
    msg = (
        "\U0001F4D6 **Bot Command Help**\n\n"
        "`/track [names]` — Track stat growth for players.\n"
        "`/trackrole [role]` — Track all users in a role.\n"
        "`/topgrowth` — Show top stat gainers.\n"
        "`/cleartrack [name]` — Delete snapshot.\n"
        "`/exporttrack` — Export all tracked data.\n"
        "`/status` — Ping check.\n"
        "`/help` — Show this help."
    )
    await interaction.response.send_message(msg, ephemeral=True)

@tree.command(name="status", description="Check bot responsiveness", guild=GUILD_ID)
async def status(interaction: discord.Interaction):
    start = time.time()
    await interaction.response.defer(ephemeral=True)
    await asyncio.sleep(0.1)
    latency = (time.time() - start) * 1000
    await interaction.followup.send(f"✅ Ping: `{latency:.2f}ms`", ephemeral=True)

@tree.command(name="track", description="Track Torn player stats", guild=GUILD_ID)
@app_commands.describe(names="Usernames separated by space")
async def track(interaction: discord.Interaction, names: str):
    await interaction.response.defer(ephemeral=True)
    reports = []

    for name in names.split():
        player_id = get_torn_user(name)
        if not player_id:
            reports.append(f"❌ `{name}` — Not found or private")
            continue

        data = fetch_user_cached(player_id)
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
            age = f"{dt // 3600}h" if dt < 86400 else f"{dt // 86400}d"

            diff = {
                "stats": profile["total_stats"] - old["total_stats"],
                "cash": profile["money_earned"] - old["money_earned"],
                "refills": profile["refills"] - old["refills"],
                "drugs": profile["drugs"] - old["drugs"],
                "revives": profile["revives"] - old["revives"],
                "worth": profile["net_worth"] - old["net_worth"]
            }

            msg = (
                f"📈 **{name}** ({age} ago):\n"
                f"• Stats: +{diff['stats'] / 1_000_000:.1f}M\n"
                f"• Worth: +${diff['worth']:,}\n"
                f"• Cash: +${diff['cash']:,}\n"
                f"• Drugs: +{diff['drugs']}, Refills: +{diff['refills']}, Revives: +{diff['revives']}"
            )
        else:
            msg = f"📌 First snapshot for `{name}` saved. Use `/track {name}` again later."

        with open(file_path, "w") as f:
            json.dump(profile, f, indent=2)

        reports.append(msg)

    await interaction.followup.send("\n\n".join(reports), ephemeral=True)

@tree.command(name="trackrole", description="Track all users in a Discord role", guild=GUILD_ID)
@app_commands.describe(role="Discord role to track")
async def track_role(interaction: discord.Interaction, role: discord.Role):
    await interaction.response.defer(ephemeral=True)
    members = [m.display_name for m in role.members if not m.bot]
    if not members:
        await interaction.followup.send("❌ No members found.", ephemeral=True)
        return
    await track(interaction, " ".join(members))

@tree.command(name="cleartrack", description="Delete a user's tracked snapshot", guild=GUILD_ID)
@app_commands.describe(name="Torn username")
async def cleartrack(interaction: discord.Interaction, name: str):
    file_path = os.path.join(TRACK_FOLDER, f"{name.lower()}.json")
    if os.path.exists(file_path):
        os.remove(file_path)
        await interaction.response.send_message(f"🗑️ Snapshot for `{name}` deleted.", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ No snapshot found for `{name}`.", ephemeral=True)

@tree.command(name="exporttrack", description="Export all tracked data to CSV", guild=GUILD_ID)
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

    with open("export.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    await interaction.followup.send(file=discord.File("export.csv"), ephemeral=True)

@tree.command(name="topgrowth", description="Show top stat gainers", guild=GUILD_ID)
async def topgrowth(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    growths = []
    for filename in os.listdir(TRACK_FOLDER):
        with open(os.path.join(TRACK_FOLDER, filename)) as f:
            data = json.load(f)
        growths.append((filename[:-5], data["total_stats"]))
    top = sorted(growths, key=lambda x: x[1], reverse=True)[:10]
    msg = "🏆 **Top Growth**\n\n" + "\n".join([
        f"`{i+1}.` {name} — {stats / 1_000_000:.1f}M"
        for i, (name, stats) in enumerate(top)
    ])
    await interaction.followup.send(msg, ephemeral=True)

# ====== Keep alive web server for Render ======
import aiohttp
from aiohttp import web

async def handle(request):
    return web.Response(text="Bot is running!")

async def start_webserver():
    app = web.Application()
    app.add_routes([web.get("/", handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 10000)))
    await site.start()

# ====== Start bot ======
async def start_all():
    await start_webserver()
    await bot.start(TOKEN)

asyncio.run(start_all())
