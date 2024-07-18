import os
import discord
from dotenv import load_dotenv
import asyncio
import re
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

if not TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable not set.")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True

bot = discord.Client(intents=intents)
queue = asyncio.Queue()

def sanitize_username(username):
    # Remove all non-alphanumeric characters except hyphens and underscores
    sanitized_name = re.sub(r'[^a-zA-Z0-9-_]', '', username)
    # Limit the length of the channel name
    return sanitized_name[:32]

def setup_logger(guild_id):
    now = datetime.now()
    log_directory = os.path.join("logs", str(guild_id), str(now.year), str(now.month))
    os.makedirs(log_directory, exist_ok=True)
    log_path = os.path.join(log_directory, f"{now.day}.log")
    
    logger = logging.getLogger(f'guild_{guild_id}')
    logger.setLevel(logging.INFO)
    
    # Avoid adding multiple handlers to the logger
    if not logger.handlers:
        handler = RotatingFileHandler(log_path, maxBytes=5*1024*1024, backupCount=3)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger

@bot.event
async def on_ready():
    for guild in bot.guilds:
        await queue.put(ensure_voices_category_and_channel(guild))
    bot.loop.create_task(process_queue())

@bot.event
async def on_guild_join(guild):
    await queue.put(ensure_voices_category_and_channel(guild))

async def process_queue():
    while True:
        task = await queue.get()
        await task
        await asyncio.sleep(1)  # Adjust sleep time as needed to stay under rate limits

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
    except discord.Forbidden:
        logger.error(f"Permission error in guild {guild.name} ({guild.id})")
    except discord.HTTPException as e:
        logger.error(f"HTTP error in guild {guild.name} ({guild.id}): {e}")
    except Exception as e:
        logger.error(f"Unexpected error in guild {guild.name} ({guild.id}): {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    logger = setup_logger(member.guild.id)
    if after.channel and after.channel.name == "➕︱voice":
        voices_category = discord.utils.get(member.guild.categories, name="VOICES")
        if voices_category:
            sanitized_name = sanitize_username(member.name)
            await queue.put(create_and_move_to_channel(member, voices_category, sanitized_name))

    if before.channel and before.channel != after.channel:
        if before.channel.name != "➕︱voice" and before.channel.category and before.channel.category.name == "VOICES":
            if len(before.channel.members) == 0:
                await queue.put(delete_channel(before.channel))

async def create_and_move_to_channel(member, category, channel_name):
    logger = setup_logger(member.guild.id)
    try:
        # Create channel with default permissions and manage channel permission for the member
        overwrites = {
            member: discord.PermissionOverwrite(manage_channels=True)
        }
        new_channel = await category.create_voice_channel(channel_name, overwrites=overwrites)
        await member.move_to(new_channel)
        logger.info(f"Created and moved {member.name} to channel {channel_name} in {category.guild.name}")
    except discord.Forbidden:
        logger.error(f"Permission error when creating/moving channel for {member.name}")
    except discord.HTTPException as e:
        logger.error(f"HTTP error when creating/moving channel for {member.name}: {e}")
        if e.status == 429:
            retry_after = int(e.response.headers['Retry-After']) / 1000
            logger.warning(f"Rate limited. Retrying after {retry_after} seconds.")
            await asyncio.sleep(retry_after)
            new_channel = await category.create_voice_channel(channel_name, overwrites=overwrites)
            await member.move_to(new_channel)
    except Exception as e:
        logger.error(f"Unexpected error when creating/moving channel for {member.name}: {e}")

async def delete_channel(channel):
    logger = setup_logger(channel.guild.id)
    try:
        await channel.delete()
        logger.info(f"Deleted empty channel {channel.name} in {channel.guild.name}")
    except discord.Forbidden:
        logger.error(f"Permission error when deleting channel {channel.name}")
    except discord.HTTPException as e:
        logger.error(f"HTTP error when deleting channel {channel.name}: {e}")
        if e.status == 429:
            retry_after = int(e.response.headers['Retry-After']) / 1000
            logger.warning(f"Rate limited. Retrying after {retry_after} seconds.")
            await asyncio.sleep(retry_after)
            await channel.delete()
    except Exception as e:
        logger.error(f"Unexpected error when deleting channel {channel.name}: {e}")

bot.run(TOKEN)
