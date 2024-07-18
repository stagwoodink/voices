import os
import discord
from dotenv import load_dotenv
from pymongo import MongoClient
import asyncio
import re
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')

# Connect to MongoDB
client = MongoClient(MONGO_URI)
db = client['your_database_name']
logs_collection = db['logs']

# Configure logging
def setup_logger(guild_id):
    now = datetime.now()
    log_directory = f"logs/{guild_id}/{now.year}/{now.month}"
    os.makedirs(log_directory, exist_ok=True)
    log_path = f"{log_directory}/{now.day}.log"

    logger = logging.getLogger(f'guild_{guild_id}')
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = RotatingFileHandler(log_path, maxBytes=5*1024*1024, backupCount=3)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger

# Setup Discord client
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True

bot = discord.Client(intents=intents)
queue = asyncio.Queue()

def sanitize_nickname(nickname):
    return re.sub(r'[^a-zA-Z0-9-_]', '', nickname)[:32]

@bot.event
async def on_ready():
    for guild in bot.guilds:
        await queue.put(ensure_voices_category_and_channel(guild))
    bot.loop.create_task(process_queue())
    print(f'Logged in as {bot.user}')

@bot.event
async def on_guild_join(guild):
    await queue.put(ensure_voices_category_and_channel(guild))

async def process_queue():
    while True:
        task = await queue.get()
        await task
        await asyncio.sleep(1)

async def ensure_voices_category_and_channel(guild):
    logger = setup_logger(guild.id)
    try:
        bot_member = guild.get_member(bot.user.id)
        if bot_member and bot_member.guild_permissions.manage_channels:
            voices_category = discord.utils.get(guild.categories, name="VOICES")
            if not voices_category:
                voices_category = await guild.create_category("VOICES")
                logger.info(f"'VOICES' category created in guild {guild.name} ({guild.id})")
            if not discord.utils.get(voices_category.channels, name="➕︱voice"):
                await voices_category.create_voice_channel("➕︱voice")
                logger.info(f"'➕︱voice' channel created in guild {guild.name} ({guild.id})")
    except (discord.Forbidden, discord.HTTPException) as e:
        logger.error(f"Error in guild {guild.name} ({guild.id}): {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    logger = setup_logger(member.guild.id)
    if after.channel and after.channel.name == "➕︱voice":
        voices_category = discord.utils.get(member.guild.categories, name="VOICES")
        if voices_category:
            sanitized_nickname = sanitize_nickname(member.nick or member.name)
            user_channel = discord.utils.get(voices_category.channels, name=sanitized_nickname)
            if user_channel:
                await member.move_to(user_channel)
            else:
                await queue.put(create_and_move_to_channel(member, voices_category, sanitized_nickname))
    if before.channel and before.channel != after.channel:
        if before.channel.name != "➕︱voice" and before.channel.category and before.channel.category.name == "VOICES":
            if len(before.channel.members) == 0:
                await queue.put(delete_channel(before.channel))

async def create_and_move_to_channel(member, category, channel_name):
    logger = setup_logger(member.guild.id)
    try:
        new_channel = await category.create_voice_channel(channel_name)
        await member.move_to(new_channel)
        logger.info(f"Created and moved {member.nick or member.name} to channel {channel_name} in {category.guild.name}")
        logs_collection.insert_one({"event": "channel_created", "member": member.nick or member.name, "channel": channel_name, "timestamp": datetime.now()})
    except (discord.Forbidden, discord.HTTPException) as e:
        logger.error(f"Error for {member.nick or member.name}: {e}")
        if isinstance(e, discord.HTTPException) and e.status == 429:
            await asyncio.sleep(int(e.response.headers['Retry-After']) / 1000)
            await create_and_move_to_channel(member, category, channel_name)

async def delete_channel(channel):
    logger = setup_logger(channel.guild.id)
    try:
        await channel.delete()
        logger.info(f"Deleted empty channel {channel.name} in {channel.guild.name}")
        logs_collection.insert_one({"event": "channel_deleted", "channel": channel.name, "timestamp": datetime.now()})
    except (discord.Forbidden, discord.HTTPException) as e:
        logger.error(f"Error deleting {channel.name}: {e}")
        if isinstance(e, discord.HTTPException) and e.status == 429:
            await asyncio.sleep(int(e.response.headers['Retry-After']) / 1000)
            await delete_channel(channel)

bot.run(TOKEN)
