import os
import json
import time
import asyncio
import csv
import aiohttp
import discord
import requests
from aiohttp import web
from discord.ext import commands
from discord import app_commands

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
TORN_API_KEY = "etqdem2Fp1VlhfGB"
TEST_GUILD_ID = 1352710920660582471
TRACK_FOLDER = "tracked"
os.makedirs(TRACK_FOLDER, exist_ok=True)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
CACHE = {}
CACHE_DURATION = 60  # seconds

# ========== Torn Lookup ==========

def get_user_id(username):
    url = f"https://api.torn.com/user/?username={username}&key={TORN_API_KEY}"
    try:
        res = requests.get(url, timeout=5)
        data = res.json()
        return data.get("player_id")
    except:
        return None

def fetch_user_data(user_id):
    now = time.time()
    if user_id in CACHE and now - CACHE[user_id]["ts"] < CACHE_DURATION:
        return CACHE[user_id]["data"]

    url = f"https://api.torn.com/user/{user_id}?selections=basic,stats,personalstats,networth&key={TORN_API_KEY}"
    try:
        res = requests.get(url, timeout=5)
        data = res.json()
        if "error" in data:
            return None
        CACHE[user_id] = {"ts": now, "data": data}
        return data
    except:
        return None

# ========== Slash Commands ==========

@tree.command(name="status", description="Check bot responsiveness", guild=discord.Object(id=TEST_GUILD_ID))
async def status(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await asyncio.sleep(0.2)
    latency = bot.latency * 1000
    await interaction.followup.send(f"✅ Bot is responsive! Ping: `{latency:.2f}ms`", ephemeral=True)

@tree.command(name="help", description="Show all commands and usage", guild=discord.Object(id=TEST_GUILD_ID))
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message(
        "**📘 Bot Commands:**\n"
        "`/track [names]` — Track stat growth of players\n"
        "`/trackrole [role]` — Track all users in a role\n"
        "`/cleartrack [name]` — Clear snapshot for a player\n"
        "`/exporttrack` — Export all tracked data\n"
        "`/topgrowth` — Show top stat gainers\n"
        "`/status` — Ping the bot\n"
        "`/help` — Show this help menu",
        ephemeral=True
    )

@tree.command(name="track", description="Track stat growth", guild=discord.Object(id=TEST_GUILD_ID))
@app_commands.describe(names="Space-separated Torn usernames")
async def track(interaction: discord.Interaction, names: str):
    await interaction.response.defer(ephemeral=True)
    reports = []

    for name in names.split():
        user_id = get_user_id(name)
        if not user_id:
            reports.append(f"❌ `{name}` — User not found.")
            continue

        data = fetch_user_data(user_id)
        if not data:
            reports.append(f"❌ `{name}` — No data.")
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

        file_path = os.path.join(TRACK_FOLDER, f"{user_id}.json")

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
                f"📈 **{name}** ({age}):\n"
                f"• Stats: +{diff['stats'] / 1_000_000:.1f}M\n"
                f"• Net Worth: +${diff['worth']:,}\n"
                f"• Cash Earned: +${diff['cash']:,}\n"
                f"• Drugs: +{diff['drugs']}, Refills: +{diff['refills']}, Revives: +{diff['revives']}"
            )
        else:
            msg = f"📌 First snapshot saved for `{name}`. Use `/track {name}` later to see progress."

        with open(file_path, "w") as f:
            json.dump(profile, f, indent=2)

        reports.append(msg)

    await interaction.followup.send("\n\n".join(reports), ephemeral=True)

@tree.command(name="trackrole", description="Track all users in a role", guild=discord.Object(id=TEST_GUILD_ID))
@app_commands.describe(role="Role to track")
async def trackrole(interaction: discord.Interaction, role: discord.Role):
    members = [m.display_name for m in role.members if not m.bot]
    if not members:
        await interaction.response.send_message("❌ No members found.", ephemeral=True)
        return
    await track(interaction, " ".join(members))

@tree.command(name="cleartrack", description="Clear saved data for a player", guild=discord.Object(id=TEST_GUILD_ID))
@app_commands.describe(name="Torn username")
async def cleartrack(interaction: discord.Interaction, name: str):
    user_id = get_user_id(name)
    if not user_id:
        await interaction.response.send_message(f"❌ Could not find `{name}`.", ephemeral=True)
        return
    path = os.path.join(TRACK_FOLDER, f"{user_id}.json")
    if os.path.exists(path):
        os.remove(path)
        await interaction.response.send_message(f"🗑️ Cleared data for `{name}`.", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ No data found for `{name}`.", ephemeral=True)

@tree.command(name="exporttrack", description="Export all tracking data", guild=discord.Object(id=TEST_GUILD_ID))
async def exporttrack(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    rows = []

    for file in os.listdir(TRACK_FOLDER):
        if file.endswith(".json"):
            with open(os.path.join(TRACK_FOLDER, file)) as f:
                data = json.load(f)
            rows.append({
                "user_id": file[:-5],
                **data
            })

    if not rows:
        await interaction.followup.send("⚠️ No data found.", ephemeral=True)
        return

    with open("export.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    await interaction.followup.send(file=discord.File("export.csv"), ephemeral=True)

@tree.command(name="topgrowth", description="Top stat gainers", guild=discord.Object(id=TEST_GUILD_ID))
async def topgrowth(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    records = []

    for file in os.listdir(TRACK_FOLDER):
        with open(os.path.join(TRACK_FOLDER, file)) as f:
            data = json.load(f)
        records.append((file[:-5], data["total_stats"]))

    top = sorted(records, key=lambda x: x[1], reverse=True)[:10]
    text = "\n".join([f"`{i+1}.` ID {uid} — {stats / 1_000_000:.1f}M" for i, (uid, stats) in enumerate(top)])
    await interaction.followup.send("🏆 **Top Growth**\n" + text, ephemeral=True)

# ========== Web Keepalive for Render ==========

async def handle(request):
    return web.Response(text="Bot is alive!")

async def start_webserver():
    app = web.Application()
    app.add_routes([web.get("/", handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port=10000)
    await site.start()

@bot.event
async def on_ready():
    await tree.sync(guild=discord.Object(id=TEST_GUILD_ID))
    print(f"✅ Synced commands to test server: {TEST_GUILD_ID}")

async def run_all():
    await start_webserver()
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(run_all())
