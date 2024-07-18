import os
import discord
from dotenv import load_dotenv
from pymongo import MongoClient, errors
import asyncio
import re
from datetime import datetime

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')

# Connect to MongoDB with error handling
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client['voices']
    logs_collection = db['logs']
    client.server_info()  # Force connection on a request as the connect=True parameter of MongoClient seems to be useless here
except errors.ServerSelectionTimeoutError as err:
    print(f"MongoDB connection error: {err}")
    exit(1)

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True

bot = discord.Client(intents=intents)
queue = asyncio.Queue()

def sanitize_nickname(nickname):
    return re.sub(r'[^a-zA-Z0-9-_]', '', nickname)[:32]

async def log_event(event_type, guild, **kwargs):
    log_entry = {
        "event": event_type,
        "guild": guild.name,
        "guild_id": guild.id,
        "timestamp": datetime.now(),
    }
    log_entry.update(kwargs)
    logs_collection.insert_one(log_entry)
    # Uncomment the following line to enable printing to the terminal
    # print(f"Logged event: {log_entry}")

async def update_status():
    await bot.wait_until_ready()
    while not bot.is_closed():
        server_count = len(bot.guilds)
        await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"over {server_count} servers"))
        await asyncio.sleep(600)  # Update every 10 minutes

@bot.event
async def on_ready():
    for guild in bot.guilds:
        await queue.put(ensure_voices_category_and_channel(guild))
    bot.loop.create_task(process_queue())
    bot.loop.create_task(update_status())

@bot.event
async def on_guild_join(guild):
    await queue.put(ensure_voices_category_and_channel(guild))

async def process_queue():
    while True:
        task = await queue.get()
        await task
        await asyncio.sleep(1)

async def ensure_voices_category_and_channel(guild):
    try:
        bot_member = guild.get_member(bot.user.id)
        if bot_member and bot_member.guild_permissions.manage_channels:
            voices_category = discord.utils.get(guild.categories, name="VOICES")
            if not voices_category:
                voices_category = await guild.create_category("VOICES")
                await log_event("category_created", guild, category="VOICES")
            if not discord.utils.get(voices_category.channels, name="➕︱voice"):
                await voices_category.create_voice_channel("➕︱voice")
                await log_event("channel_created", guild, channel="➕︱voice")
    except (discord.Forbidden, discord.HTTPException) as e:
        await log_event("error", guild, error=str(e))

@bot.event
async def on_voice_state_update(member, before, after):
    if after.channel and after.channel.name == "➕︱voice":
        voices_category = discord.utils.get(member.guild.categories, name="VOICES")
        if voices_category:
            sanitized_nickname = sanitize_nickname(member.nick or member.name)
            user_channel = discord.utils.get(voices_category.channels, name=sanitized_nickname)
            if user_channel:
                await member.move_to(user_channel)
                await log_event("user_moved", member.guild, member=member.nick or member.name, channel=user_channel.name)
            else:
                await queue.put(create_and_move_to_channel(member, voices_category, sanitized_nickname))
    if before.channel and before.channel != after.channel:
        if before.channel.name != "➕︱voice" and before.channel.category and before.channel.category.name == "VOICES":
            if len(before.channel.members) == 0:
                await queue.put(delete_channel(before.channel))

async def create_and_move_to_channel(member, category, channel_name):
    try:
        new_channel = await category.create_voice_channel(channel_name)
        await member.move_to(new_channel)
        await log_event("channel_created", category.guild, member=member.nick or member.name, channel=channel_name)
    except (discord.Forbidden, discord.HTTPException) as e:
        await log_event("error", category.guild, error=str(e))
        if isinstance(e, discord.HTTPException) and e.status == 429:
            await asyncio.sleep(int(e.response.headers['Retry-After']) / 1000)
            await create_and_move_to_channel(member, category, channel_name)

async def delete_channel(channel):
    try:
        await channel.delete()
        await log_event("channel_deleted", channel.guild, channel=channel.name)
    except (discord.Forbidden, discord.HTTPException) as e:
        await log_event("error", channel.guild, error=str(e))
        if isinstance(e, discord.HTTPException) and e.status == 429:
            await asyncio.sleep(int(e.response.headers['Retry-After']) / 1000)
            await delete_channel(channel)

bot.run(TOKEN)
