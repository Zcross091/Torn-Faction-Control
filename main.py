import os
import json
import time
import discord
import requests
import asyncio
import csv
from discord.ext import commands
from discord import app_commands

# === Environment ===
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
TORN_API_KEY = "etqdem2Fp1VlhfGB"
GUILD_ID = 1352710920660582471  # your server

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

TRACK_FOLDER = "tracked"
os.makedirs(TRACK_FOLDER, exist_ok=True)

CACHE = {}
CACHE_DURATION = 60  # seconds

# === Fetch Torn User ===
def get_torn_user(name):
    url = f"https://api.torn.com/user/?selections=search&key={TORN_API_KEY}&search={name}"
    res = requests.get(url)
    if res.status_code != 200:
        return None
    data = res.json()
    return data.get("playerID")

def fetch_user_cached(user_id):
    now = time.time()
    if user_id in CACHE and now - CACHE[user_id]['ts'] < CACHE_DURATION:
        return CACHE[user_id]['data']

    url = f"https://api.torn.com/user/{user_id}?selections=basic,stats,personalstats,networth&key={TORN_API_KEY}"
    res = requests.get(url)
    if res.status_code != 200:
        return None

    data = res.json()
    if 'error' in data:
        return None

    CACHE[user_id] = {'ts': now, 'data': data}
    return data

# === Sync Slash Commands ===
@bot.event
async def on_ready():
    await bot.wait_until_ready()
    try:
        guild = discord.Object(id=GUILD_ID)
        await tree.sync(guild=guild)
        print(f"✅ Synced commands to guild {GUILD_ID}")
    except Exception as e:
        print(f"❌ Sync failed: {e}")

# === /help ===
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
    )
    await interaction.response.send_message(msg, ephemeral=True)

# === /status ===
@tree.command(name="status", description="Check if bot is responsive", guild=discord.Object(id=GUILD_ID))
async def status(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await asyncio.sleep(0.2)
    await interaction.followup.send("✅ Bot is online and responsive.", ephemeral=True)

# === /track ===
@tree.command(name="track", description="Track player progress", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(names="Torn usernames separated by space")
async def track(interaction: discord.Interaction, names: str):
    await interaction.response.defer(ephemeral=True)
    reports = []

    for name in names.split():
        user_id = get_torn_user(name)
        if not user_id:
            reports.append(f"❌ `{name}` not found")
            continue

        data = fetch_user_cached(user_id)
        if not data:
            reports.append(f"❌ `{name}` — API error")
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

        filename = os.path.join(TRACK_FOLDER, f"{user_id}.json")
        if os.path.exists(filename):
            with open(filename, "r") as f:
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
                f"📈 **{data['name']}** ({age}):\n"
                f"• Stats: +{diff['stats'] / 1_000_000:.1f}M\n"
                f"• Net Worth: +${diff['worth']:,}\n"
                f"• Cash Earned: +${diff['cash']:,}\n"
                f"• Drugs: +{diff['drugs']}, Refills: +{diff['refills']}, Revives: +{diff['revives']}"
            )
        else:
            msg = f"📌 First snapshot saved for `{data['name']}`."

        with open(filename, "w") as f:
            json.dump(profile, f, indent=2)
        reports.append(msg)

    await interaction.followup.send("\n\n".join(reports), ephemeral=True)

# === /trackrole ===
@tree.command(name="trackrole", description="Track all users in a Discord role", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(role="Role to track")
async def trackrole(interaction: discord.Interaction, role: discord.Role):
    await interaction.response.defer(ephemeral=True)
    names = [m.display_name for m in role.members if not m.bot]
    if not names:
        await interaction.followup.send("❌ No valid users found.", ephemeral=True)
        return
    await track(interaction, " ".join(names))

# === /cleartrack ===
@tree.command(name="cleartrack", description="Delete snapshot", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(name="Torn username")
async def cleartrack(interaction: discord.Interaction, name: str):
    user_id = get_torn_user(name)
    if not user_id:
        await interaction.response.send_message("❌ Username not found.", ephemeral=True)
        return
    path = os.path.join(TRACK_FOLDER, f"{user_id}.json")
    if os.path.exists(path):
        os.remove(path)
        await interaction.response.send_message("🗑️ Snapshot deleted.", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ No snapshot found.", ephemeral=True)

# === /exporttrack ===
@tree.command(name="exporttrack", description="Export tracking to CSV", guild=discord.Object(id=GUILD_ID))
async def exporttrack(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    rows = []
    for filename in os.listdir(TRACK_FOLDER):
        if filename.endswith(".json"):
            with open(os.path.join(TRACK_FOLDER, filename)) as f:
                data = json.load(f)
            rows.append({
                "user_id": filename[:-5],
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

# === /topgrowth ===
@tree.command(name="topgrowth", description="Show top growth", guild=discord.Object(id=GUILD_ID))
async def topgrowth(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    growths = []
    for filename in os.listdir(TRACK_FOLDER):
        with open(os.path.join(TRACK_FOLDER, filename)) as f:
            data = json.load(f)
        growths.append((filename[:-5], data["total_stats"]))
    top = sorted(growths, key=lambda x: x[1], reverse=True)[:10]
    msg = "**🏆 Top Growth**\n" + "\n".join([f"{i+1}. {uid} — {stats / 1_000_000:.1f}M" for i, (uid, stats) in enumerate(top)])
    await interaction.followup.send(msg, ephemeral=True)

# === Web Server (Render) ===
import aiohttp
from aiohttp import web

async def handle(request):
    return web.Response(text="Bot is alive!")

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    await start_webserver()
    await bot.start(TOKEN)

asyncio.run(main())
