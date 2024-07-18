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
db_available = True
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client['voices']
    logs_collection = db['logs']
    client.server_info()
    print("Connected to MongoDB successfully.")
except errors.ServerSelectionTimeoutError as err:
    print(f"MongoDB connection error: {err}")
    db_available = False

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True

bot = discord.Client(intents=intents)
queue = asyncio.Queue()
created_channels = {}

TRIGGER_CHANNEL_NAME = "➕︱voices"

def sanitize_nickname(nickname):
    return re.sub(r'[^a-zA-Z0-9-_]', '', nickname)[:32]

async def log_event(event_type, guild, **kwargs):
    if db_available:
        logs_collection.insert_one({
            "event": event_type,
            "guild": guild.name,
            "guild_id": guild.id,
            "timestamp": datetime.now(),
            **kwargs
        })
    # Uncomment the following line to enable logging to terminal
    # print(f"Logged event: {event_type}, Details: {kwargs}")

async def update_status():
    await bot.wait_until_ready()
    while not bot.is_closed():
        status = f"over {len(bot.guilds)} servers" if db_available else "log database sleep"
        await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=status))
        await asyncio.sleep(600)

@bot.event
async def on_ready():
    for guild in bot.guilds:
        await queue.put(ensure_trigger_channel(guild))
    bot.loop.create_task(process_queue())
    bot.loop.create_task(update_status())
    print(f'Logged in as {bot.user}')

@bot.event
async def on_guild_join(guild):
    await queue.put(ensure_trigger_channel(guild))

async def process_queue():
    while True:
        task = await queue.get()
        try:
            await task
        except discord.DiscordServerError as e:
            await log_event("error", task.guild, error=str(e))
        await asyncio.sleep(1)

async def ensure_trigger_channel(guild):
    trigger_channel = discord.utils.get(guild.voice_channels, name=TRIGGER_CHANNEL_NAME)
    if not trigger_channel:
        try:
            trigger_channel = await guild.create_voice_channel(TRIGGER_CHANNEL_NAME)
            await log_event("trigger_channel_created", guild, channel=TRIGGER_CHANNEL_NAME)
            await trigger_channel.edit(position=0)
        except discord.Forbidden:
            await log_event("error", guild, error="Missing permissions to create the trigger channel")
        except discord.HTTPException as e:
            await log_event("error", guild, error=f"HTTPException: {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    if after.channel and after.channel.name == TRIGGER_CHANNEL_NAME:
        await handle_new_voice_channel(member, after.channel)
    if before.channel and before.channel != after.channel:
        await check_empty_channel(before.channel)

async def handle_new_voice_channel(member, after_channel):
    category = after_channel.category if after_channel else None
    if category:
        sanitized_name = sanitize_nickname(member.nick or member.name)
        user_channel = discord.utils.get(category.voice_channels, name=sanitized_name)
        if user_channel:
            await member.move_to(user_channel)
            await log_event("user_moved", member.guild, member=member.nick or member.name, channel=user_channel.name)
        else:
            await queue.put(create_and_move_to_channel(member, category, sanitized_name))

async def create_and_move_to_channel(member, category, channel_name):
    try:
        new_channel = await category.create_voice_channel(channel_name)
        created_channels[new_channel.id] = {
            "guild_id": member.guild.id,
            "channel_id": new_channel.id
        }
        await member.move_to(new_channel)
        await log_event("channel_created", member.guild, member=member.nick or member.name, channel=channel_name, channel_id=new_channel.id)
    except (discord.Forbidden, discord.HTTPException) as e:
        await log_event("error", member.guild, error=str(e))
        if isinstance(e, discord.HTTPException) and e.status == 429:
            await asyncio.sleep(int(e.response.headers['Retry-After']) / 1000)
            await create_and_move_to_channel(member, category, channel_name)

async def check_empty_channel(channel):
    if isinstance(channel, discord.VoiceChannel) and len(channel.members) == 0:
        if channel.id in created_channels:
            await delete_empty_channel(channel)

async def delete_empty_channel(channel):
    try:
        await channel.delete()
        await log_event("channel_deleted", channel.guild, channel=channel.name)
    except (discord.Forbidden, discord.HTTPException) as e:
        await log_event("error", channel.guild, error=str(e))
        if isinstance(e, discord.HTTPException) and e.status == 429:
            await asyncio.sleep(int(e.response.headers['Retry-After']) / 1000)
            await delete_empty_channel(channel)

bot.run(TOKEN)
