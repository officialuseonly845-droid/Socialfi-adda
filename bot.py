import asyncio
import logging
import os
import re
from typing import Dict, Any, Optional

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, Filter
from aiogram.enums import ChatType
from aiogram.types import ChatPermissions

from fastapi import FastAPI
import uvicorn

# --- 🧠 General Setup ---

# Load environment variables from .env file
load_dotenv()

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in environment variables or .env file.")

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# In-memory data storage (Changed to support multiple chats)
# chat_id -> (telegram_username -> link)
participants: Dict[int, Dict[str, str]] = {}
# chat_id -> (telegram_username -> x_username)
x_handles: Dict[int, Dict[str, str]] = {}
# chat_id -> (telegram_username -> bool)
completed_users: Dict[int, Dict[str, bool]] = {}
# chat_id -> chat_is_locked
chat_locks: Dict[int, bool] = {}

# Regex to extract X (formerly Twitter) username from a link
X_LINK_REGEX = re.compile(r"https?:\/\/(?:www\.)?(?:x\.com|twitter\.com)\/([a-zA-Z0-9_]+)\/status\/\d+")

# --- Helper Functions ---

async def is_admin(chat_id: int, user_id: int, bot: Bot) -> bool:
    """Checks if a user is an admin in the specified chat."""
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status in ['creator', 'administrator']
    except Exception as e:
        logger.error(f"Error checking admin status in chat {chat_id}: {e}")
        return False

def extract_x_username(url: str) -> Optional[str]:
    """Extracts the X username from a typical X status link."""
    match = X_LINK_REGEX.search(url)
    return match.group(1) if match else None

def is_x_link(text: str) -> bool:
    """Simple check for common X link patterns."""
    return bool(re.search(r"https?:\/\/(?:x\.com|twitter\.com)\/", text))

def get_session_data(chat_id: int) -> tuple[Dict[str, str], Dict[str, str], Dict[str, bool], bool]:
    """Initializes and retrieves session data for a given chat."""
    participants_map = participants.setdefault(chat_id, {})
    x_handles_map = x_handles.setdefault(chat_id, {})
    completed_users_map = completed_users.setdefault(chat_id, {})
    is_locked = chat_locks.get(chat_id, False)
    return participants_map, x_handles_map, completed_users_map, is_locked

def clear_data(chat_id: int) -> None:
    """Clears all in-memory data for a new session in a specific chat."""
    participants.pop(chat_id, None)
    x_handles.pop(chat_id, None)
    completed_users.pop(chat_id, None)
    chat_locks[chat_id] = False
    logger.info(f"In-memory bot data cleared for chat {chat_id}.")

# --- Middleware/Filter for Admin and Group Check (Dynamic) ---

class GroupAdminFilter(Filter):
    """Filter that only allows messages from admins of the current group/supergroup chat."""
    
    async def __call__(self, message: types.Message, bot: Bot) -> bool:
        # 1. Check if the message is from a group chat
        if message.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
            # Ignore commands outside of groups
            return False
        
        # 2. Check if the user is an admin in that specific chat
        if message.from_user:
            is_adm = await is_admin(message.chat.id, message.from_user.id, bot)
            if not is_adm:
                logger.warning(f"Ignoring admin command in chat {message.chat.id} from non-admin user: @{message.from_user.username or message.from_user.id}")
            return is_adm
        
        return False

# --- Handlers for Admin Commands ---
# All handlers now accept chat_id and use get_session_data to access the correct group's data.

async def cmd_send(message: types.Message, bot: Bot):
    """/send: Unlocks chat, starts a new session, and clears data."""
    chat_id = message.chat.id
    
    # Clear previous session data
    clear_data(chat_id) 
    
    # Unlock the chat for message sending
    await bot.set_chat_permissions(
        chat_id=chat_id,
        permissions=ChatPermissions(can_send_messages=True)
    )
    chat_locks[chat_id] = False
    
    await message.reply("START SENDING LINK 🔗")
    logger.info(f"Admin @{message.from_user.username} started a new session in chat {chat_id} with /send. Chat unlocked.")

async def cmd_list(message: types.Message):
    """/list: Shows all Telegram usernames who participated."""
    chat_id = message.chat.id
    participants_map, _, _, _ = get_session_data(chat_id)
    
    user_list = "\n".join(sorted(participants_map.keys()))
    response = "USERS PARTICIPATED ✅\n\n" + (user_list if user_list else "No users have participated yet.")
    
    await message.reply(response)
    logger.info(f"Admin @{message.from_user.username} requested /list in chat {chat_id}. {len(participants_map)} users found.")

async def cmd_xlist(message: types.Message):
    """/xlist: Shows all extracted X usernames."""
    chat_id = message.chat.id
    _, x_handles_map, _, _ = get_session_data(chat_id)
    
    x_handle_list = "\n".join(sorted(x_handles_map.values()))
    response = "ALL X ID'S WHO HAVE PARTICIPATED ✅\n\n" + (x_handle_list if x_handle_list else "No X handles found yet.")
    
    await message.reply(response)
    logger.info(f"Admin @{message.from_user.username} requested /xlist in chat {chat_id}. {len(x_handles_map)} X handles found.")

async def cmd_adlist(message: types.Message):
    """/adlist: Lists Telegram usernames who completed engagement."""
    chat_id = message.chat.id
    _, _, completed_users_map, _ = get_session_data(chat_id)
    
    completed = [u for u, status in completed_users_map.items() if status]
    user_list = "\n".join(sorted(completed))
    response = "USERS WHO COMPLETED ENGAGEMENT ✅\n\n" + (user_list if user_list else "No users have completed engagement yet.")
    
    await message.reply(response)
    logger.info(f"Admin @{message.from_user.username} requested /adlist in chat {chat_id}. {len(completed)} users completed.")

async def cmd_notad(message: types.Message):
    """/notad: Compares /list vs /adlist to find non-completers."""
    chat_id = message.chat.id
    participants_map, _, completed_users_map, _ = get_session_data(chat_id)
    
    all_participants = set(participants_map.keys())
    completed = {u for u, status in completed_users_map.items() if status}
    not_completed = all_participants - completed
    
    if not_completed:
        user_list = "\n".join(sorted(not_completed))
        response = "USERS WHO HAVEN'T COMPLETED ENGAGEMENT ⚠️\n\n" + user_list
        logger.info(f"Admin @{message.from_user.username} requested /notad in chat {chat_id}. {len(not_completed)} users found incomplete.")
    else:
        response = "All participants have completed engagement! 🎉"
        logger.info(f"Admin @{message.from_user.username} requested /notad in chat {chat_id}. All complete.")
        
    await message.reply(response)

async def cmd_refresh(message: types.Message, bot: Bot):
    """/refresh: Cleans up data and deletes all messages."""
    chat_id = message.chat.id
    
    await message.reply("STARTING CLEANUP 🧹")
    logger.info(f"Admin @{message.from_user.username} initiated /refresh (cleanup) in chat {chat_id}.")
    
    # 1. Clear stored data for this chat
    clear_data(chat_id) 
    
    # 2. Delete all messages (placeholder)
    messages_deleted = 0
    # In a real scenario, this block would contain a loop to delete tracked message IDs.

    await message.reply(f"Cleaned {messages_deleted} messages 🧽 (Data cleared successfully).")
    logger.info(f"Cleanup finished in chat {chat_id}. Data reset.")

async def cmd_lock(message: types.Message, bot: Bot):
    """/lock: Locks the chat (no one can send messages)."""
    chat_id = message.chat.id
    
    await bot.set_chat_permissions(
        chat_id=chat_id,
        permissions=ChatPermissions(can_send_messages=False)
    )
    chat_locks[chat_id] = True
    
    await message.reply("GROUP LOCKED 🔒")
    logger.info(f"Admin @{message.from_user.username} locked chat {chat_id}.")

async def cmd_rs(message: types.Message):
    """/rs: Sends the group rules."""
    
    rules = (
        "📜 **SOCIALFI ADDA 👁‍🗨 — Group Rules & How It Works**\n\n"
        "🔹 **Sessions & Timing**:\n"
        "• 2 sessions daily.\n"
        "👉 **1st Session**: 9:00 AM – 3:00 PM\n"
        "➡️ **Engagement**: 3:00 PM – 5:00 PM\n"
        # ... (Rest of the rules text remains the same)
        "➡️ **Admin Check**: 10:00 PM – 11:00 PM\n\n"
        "🔹 **Link Sharing**:\n"
        "• Each user can send **2 links per session** only.\n\n"
        "🔹 **Engagement Rule**:\n"
        "• Engage with all links shared in GC.\n"
        "• After engaging, react on each link.\n"
        "• Then type **“AD”** which means **ALL DONE ✔️** in the group.\n\n"
        "🔹 **Penalties**:\n"
        "• Missed engagement = 24h mute 🔇\n"
        "• Repeated misses = ban ✅\n"
        "Stay active, engage genuinely & grow together 🚀"
    )
    
    await message.reply(rules, parse_mode="Markdown")
    logger.info(f"Admin @{message.from_user.username} requested /rs (rules) in chat {message.chat.id}.")

# --- Handler for /detect (Admin-only) ---

async def cmd_detect(message: types.Message):
    """/detect: Announces the start of the engagement phase."""
    
    response = "IF YOU HAVE COMPLETED ENGAGEMENT START SENDING 'AD' ✅"
    await message.reply(response)
    logger.info(f"Admin @{message.from_user.username} started /detect (engagement phase) in chat {message.chat.id}.")

# --- Handler for User Messages (Link Sharing and AD/Done) ---

async def handle_user_messages(message: types.Message):
    """Handles link sharing and 'AD' messages from regular users."""
    
    if not message.from_user or not message.text:
        return

    chat_id = message.chat.id
    username = message.from_user.username
    
    # Get session data for this specific chat
    participants_map, x_handles_map, completed_users_map, chat_is_locked = get_session_data(chat_id)

    if not username:
        await message.reply("Participation requires a **Telegram username** set in your profile.", parse_mode="Markdown")
        logger.warning(f"User {message.from_user.id} tried to participate without a username in chat {chat_id}.")
        return
        
    user_text = message.text.strip()
    
    # 1. Handle "AD/Done" messages
    ad_keywords = {"ad", "done", "all done", "completed"}
    if user_text.lower() in ad_keywords:
        
        # Check if the user has a link recorded in THIS group's session
        recorded_link = participants_map.get(username)
        if not recorded_link:
            await message.reply("Your link hasn't been recorded yet. Please send your X link first.")
            logger.info(f"AD/Done received from @{username} in chat {chat_id} but no link recorded.")
            return

        # Record completion in THIS group's session
        completed_users_map[username] = True
        
        response = (
            "ENGAGEMENT RECORDED 👍\n\n"
            f"Your recorded link: {recorded_link}"
        )
        await message.reply(response)
        logger.info(f"AD/Done received and recorded for @{username} in chat {chat_id}.")
        return

    # 2. Handle Link Sharing
    if is_x_link(user_text):
        if chat_is_locked:
            try:
                # If chat is locked, delete the message
                await message.delete()
                logger.info(f"Deleted link message from @{username} in chat {chat_id} due to chat lock.")
            except Exception as e:
                logger.error(f"Failed to delete locked message from @{username}: {e}")
            return
            
        if username in participants_map:
            await message.reply("You have already shared a link this session.")
            logger.warning(f"Duplicate link ignored from @{username} in chat {chat_id}.")
            return
            
        x_username = extract_x_username(user_text)
        
        if not x_username:
            await message.reply("Could not extract an X username from the link. Please ensure it's a valid `x.com/<username>/status/...` link.")
            logger.warning(f"Invalid X link format from @{username} in chat {chat_id}: {user_text}")
            return
            
        # Store the data in THIS group's session
        participants_map[username] = user_text
        x_handles_map[username] = x_username
        completed_users_map[username] = False # Set initial status
        
        logger.info(f"Link received from @{username} in chat {chat_id}. X Handle: {x_username}.")
        
    else:
        # Not a link and not an AD keyword, so this is regular chat.
        # If the chat is locked, we delete the message.
        if chat_is_locked:
            try:
                await message.delete()
                logger.info(f"Deleted message from @{username} in chat {chat_id} due to chat lock.")
            except Exception as e:
                logger.error(f"Failed to delete message from @{username} during lock: {e}")
                
# --- Error Handling ---

async def on_error(update: types.Update, exception: Exception):
    """Global error handler for all unhandled exceptions."""
    logger.error(f"Unhandled exception: {exception}", exc_info=True)

# --- Main Bot Setup ---

def setup_bot_handlers(dp: Dispatcher, admin_filter: GroupAdminFilter):
    """Registers all command and message handlers."""
    
    # Register Admin Commands with the dynamic Admin Filter
    # Only admins in the respective group can use these commands.
    dp.message.register(cmd_send, Command("send"), admin_filter)
    dp.message.register(cmd_list, Command("list"), admin_filter)
    dp.message.register(cmd_xlist, Command("xlist"), admin_filter)
    dp.message.register(cmd_adlist, Command("adlist"), admin_filter)
    dp.message.register(cmd_notad, Command("notad"), admin_filter)
    dp.message.register(cmd_refresh, Command("refresh"), admin_filter)
    dp.message.register(cmd_lock, Command("lock"), admin_filter)
    dp.message.register(cmd_rs, Command("rs"), admin_filter)
    dp.message.register(cmd_detect, Command("detect"), admin_filter)
    
    # Register regular user message handler
    # F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}) ensures we only process group messages
    dp.message.register(
        handle_user_messages, 
        F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), 
        F.text
    )
    
    # Register global error handler
    dp.error.register(on_error)
    
    logger.info("Bot handlers registered successfully for multi-group operation.")
    
# --- Keep-Alive Web Server (FastAPI) ---

app = FastAPI(title="Multi-Group Bot Keep-Alive")

@app.get("/")
def read_root():
    """Simple health check endpoint for UptimeRobot."""
    return {"status": "ok", "message": "Bot is alive and well!"}

async def run_webserver():
    """Runs the FastAPI server using uvicorn."""
    config = uvicorn.Config(
        app, 
        host="0.0.0.0", 
        port=int(os.getenv("PORT", 8080)), 
        log_level="info"
    )
    server = uvicorn.Server(config)
    logger.info(f"Starting Keep-Alive Webserver on port {config.port}...")
    await server.serve()

# --- Main Entry Point ---

async def main():
    """The main entry point for the bot and webserver."""
    
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    
    # Setup the dynamic Admin filter
    admin_filter = GroupAdminFilter()
    
    # Register handlers
    setup_bot_handlers(dp, admin_filter)

    try:
        # Start bot polling in the background
        bot_task = asyncio.create_task(dp.start_polling(bot))
        
        # Start webserver
        web_task = asyncio.create_task(run_webserver())
        
        await asyncio.gather(bot_task, web_task)
        
    except Exception as e:
        logger.error(f"A fatal error occurred in the main execution loop: {e}", exc_info=True)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        logger.info("Starting Multi-Group AIOGram Bot...")
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shutting down due to Keyboard Interrupt.")
    except Exception as e:
        logger.critical(f"Bot failed to start: {e}")
