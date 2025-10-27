import asyncio
import logging
import os
import re
from typing import Dict, Any, Optional, Union

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

# --- In-Memory Data Storage (Keyed by Chat ID) ---
# We use user_id (int) as the unique identifier within each chat's session data.

# chat_id -> (user_id -> X link)
participants: Dict[int, Dict[int, str]] = {}
# chat_id -> (user_id -> X Username)
x_handles: Dict[int, Dict[int, str]] = {}
# chat_id -> (user_id -> Completion Status: bool)
completed_users: Dict[int, Dict[int, bool]] = {}
# chat_id -> (user_id -> Display Name/Mention String (HTML format))
display_names: Dict[int, Dict[int, str]] = {}
# chat_id -> chat_is_locked (bool)
chat_locks: Dict[int, bool] = {}

# Regex to extract X (formerly Twitter) username from a link
X_LINK_REGEX = re.compile(r"https?:\/\/(?:www\.)?(?:x\.com|twitter\.com)\/([a-zA-Z0-9_]+)\/status\/\d+")

# --- Core Helper Functions ---

def get_user_mention(user: types.User) -> str:
    """
    Creates a mention string for a user, prioritizing username but using a link mention otherwise.
    Uses HTML format for compatibility with aiogram's default parse_mode.
    """
    if user.username:
        # Simple @username
        return f"@{user.username}"
    
    # Fallback to a clickable mention using HTML
    name = user.full_name or "Participant"
    return f'<a href="tg://user?id={user.id}">{name}</a>'

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

def get_session_data(chat_id: int) -> tuple[Dict[int, str], Dict[int, str], Dict[int, bool], Dict[int, str], bool]:
    """Initializes and retrieves session data for a given chat."""
    participants_map = participants.setdefault(chat_id, {})
    x_handles_map = x_handles.setdefault(chat_id, {})
    completed_users_map = completed_users.setdefault(chat_id, {})
    display_names_map = display_names.setdefault(chat_id, {})
    is_locked = chat_locks.get(chat_id, False)
    return participants_map, x_handles_map, completed_users_map, display_names_map, is_locked

def clear_data(chat_id: int) -> None:
    """Clears all in-memory data for a new session in a specific chat."""
    participants.pop(chat_id, None)
    x_handles.pop(chat_id, None)
    completed_users.pop(chat_id, None)
    display_names.pop(chat_id, None)
    chat_locks[chat_id] = False
    logger.info(f"In-memory bot data cleared for chat {chat_id}.")

# --- Filter for Admin and Group Check ---

class GroupAdminFilter(Filter):
    """Filter that only allows messages from admins of the current group/supergroup chat."""
    
    async def __call__(self, message: types.Message, bot: Bot) -> bool:
        if message.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
            return False
        
        if message.from_user:
            is_adm = await is_admin(message.chat.id, message.from_user.id, bot)
            return is_adm
        
        return False

# --- Handlers for Admin Commands ---

async def cmd_send(message: types.Message, bot: Bot):
    """/send: Unlocks chat and starts a new session."""
    chat_id = message.chat.id
    
    clear_data(chat_id) 
    
    await bot.set_chat_permissions(
        chat_id=chat_id,
        permissions=ChatPermissions(can_send_messages=True)
    )
    chat_locks[chat_id] = False
    
    await message.reply("START SENDING LINK 🔗")
    logger.info(f"Admin {message.from_user.id} started a new session in chat {chat_id} with /send.")

async def cmd_list(message: types.Message):
    """/list: Shows all Telegram users/mentions who participated."""
    chat_id = message.chat.id
    participants_map, _, _, display_names_map, _ = get_session_data(chat_id)
    
    sorted_users = sorted(display_names_map.values())
    
    user_list = "\n".join(sorted_users)
    response = "USERS PARTICIPATED ✅\n\n" + (user_list if user_list else "No users have participated yet.")
    
    # HTML is used to correctly render clickable mentions
    await message.reply(response, parse_mode="HTML") 
    logger.info(f"Admin {message.from_user.id} requested /list in chat {chat_id}.")

async def cmd_xlist(message: types.Message):
    """/xlist: Shows all extracted X usernames."""
    chat_id = message.chat.id
    _, x_handles_map, _, _, _ = get_session_data(chat_id)
    
    x_handle_list = "\n".join(sorted(x_handles_map.values()))
    response = "ALL X ID'S WHO HAVE PARTICIPATED ✅\n\n" + (x_handle_list if x_handle_list else "No X handles found yet.")
    
    await message.reply(response)
    logger.info(f"Admin {message.from_user.id} requested /xlist in chat {chat_id}.")

async def cmd_adlist(message: types.Message):
    """/adlist: Lists Telegram users/mentions who completed engagement."""
    chat_id = message.chat.id
    _, _, completed_users_map, display_names_map, _ = get_session_data(chat_id)
    
    completed_display_names = [
        display_names_map[user_id] 
        for user_id, status in completed_users_map.items() if status
    ]
    
    user_list = "\n".join(sorted(completed_display_names))
    response = "USERS WHO COMPLETED ENGAGEMENT ✅\n\n" + (user_list if user_list else "No users have completed engagement yet.")
    
    await message.reply(response, parse_mode="HTML")
    logger.info(f"Admin {message.from_user.id} requested /adlist in chat {chat_id}.")

async def cmd_notad(message: types.Message):
    """/notad: Finds users who haven't completed engagement."""
    chat_id = message.chat.id
    participants_map, _, completed_users_map, display_names_map, _ = get_session_data(chat_id)
    
    all_participants_ids = set(participants_map.keys())
    completed_ids = {user_id for user_id, status in completed_users_map.items() if status}
    not_completed_ids = all_participants_ids - completed_ids
    
    if not_completed_ids:
        not_completed_display_names = [display_names_map[user_id] for user_id in not_completed_ids]
        user_list = "\n".join(sorted(not_completed_display_names))
        response = "USERS WHO HAVE NOT COMPLETED ⚠️\n\n" + user_list
    else:
        response = "All users completed engagement ✅"
        
    await message.reply(response, parse_mode="HTML")
    logger.info(f"Admin {message.from_user.id} requested /notad in chat {chat_id}. {len(not_completed_ids)} incomplete.")

async def cmd_refresh(message: types.Message, bot: Bot):
    """/refresh: Cleans up data and deletes all messages."""
    chat_id = message.chat.id
    
    await message.reply("STARTING CLEANUP 🧹")
    
    clear_data(chat_id) 
    
    # Placeholder for message deletion logic.
    messages_deleted = 0 
    
    await message.reply(f"Cleaned {messages_deleted} messages 🧽 (Data cleared successfully)") 
    logger.info(f"Admin {message.from_user.id} finished /refresh in chat {chat_id}. Data reset.")

async def cmd_lock(message: types.Message, bot: Bot):
    """/lock: Locks the chat."""
    chat_id = message.chat.id
    
    await bot.set_chat_permissions(
        chat_id=chat_id,
        permissions=ChatPermissions(can_send_messages=False)
    )
    chat_locks[chat_id] = True
    
    await message.reply("Group chat locked 🔒")
    logger.info(f"Admin {message.from_user.id} locked chat {chat_id} via /lock.")

async def cmd_stop(message: types.Message, bot: Bot):
    """/stop: Locks the chat (identical to /lock)."""
    chat_id = message.chat.id
    
    await bot.set_chat_permissions(
        chat_id=chat_id,
        permissions=ChatPermissions(
            can_send_messages=False, 
            can_send_media_messages=False 
        )
    )
    chat_locks[chat_id] = True
    
    await message.reply("Group chat locked 🔒")
    logger.info(f"Admin {message.from_user.id} locked chat {chat_id} via /stop.")


async def cmd_rs(message: types.Message):
    """/rs: Sends the group rules."""
    
    # Using MarkdownV2 for bold/italic text
    rules = (
        "📜 *SOCIALFI ADDA 👁‍🗨 — Group Rules & How It Works*\n\n"
        "🔹 *Sessions \\& Timing:*\n"
        "• 2 sessions daily\\.\n"
        "👉 *1st Session:* 9:00 AM – 3:00 PM\n"
        "➡️ *Engagement:* 3:00 PM – 5:00 PM\n"
        "➡️ *Admin Check:* 5:00 PM – 5:30 PM\n"
        "👉 *2nd Session:* 6:00 PM – 8:00 PM IST\n"
        "✅ *Engagement :* 8:00 PM - 10:00 PM IST\n"
        "➡️ *Admin Check:* 10:00 PM – 11:00 PM\n\n"
        "🔹 *Link Sharing:*\n"
        "• Each user can send 2 links per session only\\.\n\n"
        "🔹 *Engagement Rule:*\n"
        "• Engage with all links shared in GC\\.\n"
        "• After engaging, react on each link\\.\n"
        "• Then type \\*\\*\"AD\"\\*\\* Which means \\*\\*ALL DONE ✔️\\*\\* in the group\\.\n\n"
        "🔹 *Penalties:*\n"
        "• Missed engagement = 24h mute 🔇\n"
        "• Repeated misses = ban ✅\n"
        "Stay active, engage genuinely \\& grow together 🚀"
    )
    
    await message.reply(rules, parse_mode="MarkdownV2")
    logger.info(f"Admin {message.from_user.id} requested /rs (rules) in chat {message.chat.id}.")

async def cmd_detect(message: types.Message):
    """/detect: Announces the start of the engagement phase."""
    
    response = 'IF YOU HAVE COMPLETED ENGAGEMENT START SENDING "AD" ✅'
    await message.reply(response)
    logger.info(f"Admin {message.from_user.id} started /detect (engagement phase) in chat {message.chat.id}.")

# --- Handler for User Messages (Link Sharing and AD/Done) ---

async def handle_user_messages(message: types.Message):
    """Handles link sharing and 'AD' messages from regular users."""
    
    if not message.from_user or not message.text:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    user_text = message.text.strip()
    
    # Get session data for this specific chat
    participants_map, x_handles_map, completed_users_map, display_names_map, chat_is_locked = get_session_data(chat_id)

    # 1. Handle "AD/Done" messages
    ad_keywords = {"ad", "done", "all done", "completed"}
    if user_text.lower() in ad_keywords:
        
        recorded_link = participants_map.get(user_id)
        user_mention = display_names_map.get(user_id, f"User {user_id}") 
        
        if not recorded_link:
            await message.reply("Your link hasn't been recorded yet. Please send your X link first.")
            return

        completed_users_map[user_id] = True
        
        # Format the response exactly as in the example
        response = (
            f"ENGAGEMENT RECORDED 👍 for {user_mention}\n"
            f"Their X link:\n{recorded_link}"
        )
        await message.reply(response, parse_mode="HTML") 
        logger.info(f"AD/Done recorded for {user_id} in chat {chat_id}.")
        return

    # 2. Handle Link Sharing
    if is_x_link(user_text):
        if chat_is_locked:
            try:
                await message.delete()
            except Exception:
                pass
            return
            
        if user_id in participants_map:
            await message.reply("You have already shared a link this session.")
            return
            
        x_username = extract_x_username(user_text)
        
        if not x_username:
            await message.reply("Could not extract an X username from the link. Please ensure it's a valid `x.com/<username>/status/...` link.")
            return
            
        # Store the data
        participants_map[user_id] = user_text
        x_handles_map[user_id] = x_username
        completed_users_map[user_id] = False 
        display_names_map[user_id] = get_user_mention(message.from_user) # Store the HTML mention string
        
        # User feedback for recorded link (as per example flow)
        user_mention = get_user_mention(message.from_user)
        await message.reply(f"✅ Link from {user_mention} recorded ({x_username})", parse_mode="HTML")

        logger.info(f"Link received from {user_id} in chat {chat_id}. X Handle: {x_username}.")
        
    else:
        # Regular chat message: delete if locked
        if chat_is_locked:
            try:
                await message.delete()
            except Exception:
                pass
                
# --- Error Handling ---

async def on_error(update: types.Update, exception: Exception):
    """Global error handler for all unhandled exceptions."""
    logger.error(f"Unhandled exception: {exception}", exc_info=True)

# --- Main Bot Setup ---

def setup_bot_handlers(dp: Dispatcher, admin_filter: GroupAdminFilter):
    """Registers all command and message handlers."""
    
    # Admin Commands (filtered by GroupAdminFilter)
    dp.message.register(cmd_send, Command("send"), admin_filter)
    dp.message.register(cmd_list, Command("list"), admin_filter)
    dp.message.register(cmd_xlist, Command("xlist"), admin_filter)
    dp.message.register(cmd_adlist, Command("adlist"), admin_filter)
    dp.message.register(cmd_notad, Command("notad"), admin_filter)
    dp.message.register(cmd_refresh, Command("refresh"), admin_filter)
    dp.message.register(cmd_lock, Command("lock"), admin_filter)
    dp.message.register(cmd_stop, Command("stop"), admin_filter) # New /stop command
    dp.message.register(cmd_rs, Command("rs"), admin_filter)
    dp.message.register(cmd_detect, Command("detect"), admin_filter)
    
    # User Message Handler (applies to groups/supergroups with text)
    dp.message.register(
        handle_user_messages, 
        F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), 
        F.text
    )
    
    dp.error.register(on_error)
    logger.info("Bot handlers registered successfully.")
    
# --- Keep-Alive Web Server (FastAPI) ---

app = FastAPI(title="Bot Keep-Alive")

@app.get("/")
def read_root():
    """Simple health check endpoint for UptimeRobot."""
    return {"status": "ok", "message": "Bot is alive and well!"}

async def run_webserver():
    """Runs the FastAPI server using uvicorn."""
    # Render uses the 'PORT' environment variable
    port = int(os.getenv("PORT", 8080))
    config = uvicorn.Config(
        app, 
        host="0.0.0.0", 
        port=port, 
        log_level="info"
    )
    server = uvicorn.Server(config)
    logger.info(f"Starting Keep-Alive Webserver on port {port}...")
    await server.serve()

# --- Main Entry Point ---

async def main():
    """The main entry point for the bot and webserver."""
    
    # Set default parse_mode to HTML for correct rendering of mentions
    bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
    dp = Dispatcher()
    
    admin_filter = GroupAdminFilter()
    setup_bot_handlers(dp, admin_filter)

    try:
        # Start both the bot polling and the webserver concurrently
        bot_task = asyncio.create_task(dp.start_polling(bot))
        web_task = asyncio.create_task(run_webserver())
        
        await asyncio.gather(bot_task, web_task)
        
    except Exception as e:
        logger.error(f"A fatal error occurred: {e}", exc_info=True)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        logger.info("Starting production AIOGram Bot...")
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shutting down due to Keyboard Interrupt.")
    except Exception as e:
        logger.critical(f"Bot failed to start: {e}")
