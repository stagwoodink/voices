import os
import discord
from dotenv import load_dotenv
import asyncio
import re
import yaml

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# YAML file path
YAML_FILE_PATH = "data.yaml"

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True

bot = discord.Client(intents=intents)
queue = asyncio.Queue()
created_channels = {}

TRIGGER_CHANNEL_NAME = "➕︱voices"
ADMIN_PERMISSION_MESSAGE = "# Hello\n**Sorry**, but I need **admin permissions** to function properly. Please **re-invite** me with admin permissions using this link: {invite_link}"
INVITE_LINK = "https://discord.com/oauth2/authorize?client_id=1263237947461996605&permissions=8&integration_type=0&scope=bot"

trigger_channel_ids = {}  # Dictionary to store server ID and trigger channel ID

def sanitize_nickname(nickname):
    return re.sub(r'[^a-zA-Z0-9-_]', '', nickname)[:32]

def read_yaml():
    if os.path.exists(YAML_FILE_PATH):
        with open(YAML_FILE_PATH, "r") as file:
            return yaml.safe_load(file) or {}
    return {}

def write_yaml(data):
    with open(YAML_FILE_PATH, "w") as file:
        yaml.safe_dump(data, file)

async def update_status():
    await bot.wait_until_ready()
    while not bot.is_closed():
        status = f"over {len(bot.guilds)} servers"
        await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=status))
        await asyncio.sleep(600)

@bot.event
async def on_ready():
    global trigger_channel_ids
    trigger_channel_ids = read_yaml()
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
            print(f"DiscordServerError: {e}")
        await asyncio.sleep(1)

async def ensure_trigger_channel(guild):
    trigger_channel = discord.utils.get(guild.voice_channels, name=TRIGGER_CHANNEL_NAME)
    if not trigger_channel:
        try:
            trigger_channel = await guild.create_voice_channel(TRIGGER_CHANNEL_NAME)
            await trigger_channel.edit(position=0)
            trigger_channel_ids[guild.id] = trigger_channel.id
            write_yaml(trigger_channel_ids)
        except discord.Forbidden:
            await notify_missing_permissions(guild)
        except discord.HTTPException as e:
            print(f"HTTPException: {e}")
    else:
        trigger_channel_ids[guild.id] = trigger_channel.id
        write_yaml(trigger_channel_ids)

async def notify_missing_permissions(guild):
    inviter = await get_inviter(guild)
    if inviter:
        await inviter.send(ADMIN_PERMISSION_MESSAGE.format(user=inviter.name, invite_link=INVITE_LINK))
    await guild.leave()

async def get_inviter(guild):
    async for entry in guild.audit_logs(action=discord.AuditLogAction.bot_add, limit=1):
        if entry.target.id == bot.user.id:
            return entry.user
    return None

@bot.event
async def on_voice_state_update(member, before, after):
    if after.channel and after.channel.id == trigger_channel_ids.get(member.guild.id):
        await handle_new_voice_channel(member, after.channel)
    if before.channel and before.channel != after.channel:
        await check_empty_channel(before.channel)

async def handle_new_voice_channel(member, after_channel):
    sanitized_name = sanitize_nickname(member.nick or member.name)
    category = after_channel.category if after_channel else None
    user_channel = discord.utils.get(after_channel.guild.voice_channels, name=sanitized_name)

    if user_channel:
        await member.move_to(user_channel)
    else:
        await queue.put(create_and_move_to_channel(member, after_channel, sanitized_name, category))

async def create_and_move_to_channel(member, after_channel, channel_name, category):
    try:
        overwrite_permissions = {
            member: discord.PermissionOverwrite(
                manage_channels=True,
                connect=True,
                speak=True,
                manage_permissions=True
            )
        }
        new_channel = await (category.create_voice_channel(channel_name, overwrites=overwrite_permissions) if category else after_channel.guild.create_voice_channel(channel_name, overwrites=overwrite_permissions))
        
        if not category:
            await new_channel.edit(position=after_channel.position + 1)
        
        created_channels[new_channel.id] = {
            "guild_id": member.guild.id,
            "channel_id": new_channel.id
        }
        await member.move_to(new_channel)
    except (discord.Forbidden, discord.HTTPException) as e:
        print(f"Error creating or moving to channel: {e}")
        if isinstance(e, discord.HTTPException) and e.status == 429:
            await asyncio.sleep(int(e.response.headers['Retry-After']) / 1000)
            await create_and_move_to_channel(member, after_channel, channel_name, category)

async def check_empty_channel(channel):
    await asyncio.sleep(1)  # Add a delay to check if the channel is still empty
    if isinstance(channel, discord.VoiceChannel) and len(channel.members) == 0:
        if channel.id in created_channels:
            await delete_empty_channel(channel)

async def delete_empty_channel(channel):
    try:
        await channel.delete()
        del created_channels[channel.id]
    except (discord.Forbidden, discord.HTTPException) as e:
        print(f"Error deleting channel: {e}")
        if isinstance(e, discord.HTTPException) and e.status == 429:
            await asyncio.sleep(int(e.response.headers['Retry-After']) / 1000)
            await delete_empty_channel(channel)

bot.run(TOKEN)
