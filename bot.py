import asyncio
import logging
import os
import re
from typing import Dict, Any, Optional, Union, List
import sys 

# Dependencies from requirements.txt
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, Filter
from aiogram.enums import ChatType
from aiogram.types import ChatPermissions
from aiogram.client.default import DefaultBotProperties 

from fastapi import FastAPI, Response
import uvicorn

# --- 🧠 General Setup ---

load_dotenv()

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logging.getLogger(__name__).critical("BOT_TOKEN not found. Exiting.")
    sys.exit(1)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- In-Memory Data Storage (Keyed by Chat ID) ---

participants: Dict[int, Dict[int, List[str]]] = {} 
x_handles: Dict[int, Dict[int, str]] = {}
completed_users: Dict[int, Dict[int, bool]] = {}
display_names: Dict[int, Dict[int, str]] = {}
session_active: Dict[int, bool] = {} 
chat_locks: Dict[int, bool] = {} 

MAX_LINKS_PER_USER = 2
X_LINK_REGEX = re.compile(r"https?:\/\/(?:www\.)?(?:x\.com|twitter\.com)\/([a-zA-Z0-9_]+)\/status\/\d+")

# --- Core Helper Functions ---

def get_user_mention(user: types.User) -> str:
    """Creates a clickable HTML mention for a user."""
    if user.username:
        return f"@{user.username}"
    name = user.full_name or "Participant"
    return f'<a href="tg://user?id={user.id}">{name}</a>' 

async def is_admin(chat_id: int, user_id: int, bot: Bot) -> bool:
    """Checks if a user is an admin in the specified chat, using robust error handling."""
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status in ['creator', 'administrator']
    except Exception as e:
        logger.error(f"Error checking admin status in chat {chat_id} for user {user_id}: {e}")
        return False

def extract_x_username(url: str) -> Optional[str]:
    """Extracts the X username from a typical X status link."""
    match = X_LINK_REGEX.search(url)
    return match.group(1) if match else None

def is_x_link(text: str) -> bool:
    """Simple check for common X link patterns."""
    return bool(re.search(r"https?:\/\/(?:x\.com|twitter\.com)\/", text))

def get_session_data(chat_id: int) -> tuple[Dict[int, List[str]], Dict[int, str], Dict[int, bool], Dict[int, str], bool, bool]:
    """Initializes and retrieves session data for a given chat."""
    participants_map = participants.setdefault(chat_id, {})
    x_handles_map = x_handles.setdefault(chat_id, {})
    completed_users_map = completed_users.setdefault(chat_id, {})
    display_names_map = display_names.setdefault(chat_id, {})
    
    is_active = session_active.get(chat_id, True) 
    is_locked = chat_locks.get(chat_id, False) 
    
    return participants_map, x_handles_map, completed_users_map, display_names_map, is_active, is_locked

def clear_data(chat_id: int) -> int:
    """Clears all in-memory data for a specific chat and returns the count of cleared links."""
    links_to_clear = sum(len(links) for links in participants.get(chat_id, {}).values())
    
    participants.pop(chat_id, None)
    x_handles.pop(chat_id, None)
    completed_users.pop(chat_id, None)
    display_names.pop(chat_id, None)
    
    logger.info(f"In-memory bot data cleared for chat {chat_id}. {links_to_clear} links cleared.")
    return links_to_clear

# --- Filter for Admin and Group Check ---

class GroupAdminFilter(Filter):
    """Filter that only allows messages from admins of the current group/supergroup chat."""
    
    async def __call__(self, message: types.Message, bot: Bot) -> bool:
        if message.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
            return False
        
        if message.from_user:
            return await is_admin(message.chat.id, message.from_user.id, bot)
        
        return False

# --- Handlers for Admin Commands ---

async def cmd_send(message: types.Message):
    """/send: Activates the bot session and clears data, replies in 3-4 words."""
    chat_id = message.chat.id
    
    clear_data(chat_id) 
    session_active[chat_id] = True 
    
    # 3-4 word reply with emojis
    await message.reply("Links are open 🔗")
    logger.info(f"Admin {message.from_user.id} activated session in chat {chat_id} with /send.")

async def cmd_refresh(message: types.Message):
    """/refresh: Cleans up data and sets the bot to idle, and reports progress."""
    chat_id = message.chat.id
    
    # 1. Immediate Reply
    await message.reply("STARTING CLEANUP 🧹")
    
    # 2. Clear Data and get count
    links_cleared_count = clear_data(chat_id) 
    session_active[chat_id] = False 
    
    # 3. Final Report
    await message.reply(f"Data for {links_cleared_count} links cleared. Session idled. ✅") 
    logger.info(f"Admin {message.from_user.id} finished /refresh in chat {chat_id}. Data for {links_cleared_count} links reset and bot idled.")

async def cmd_list(message: types.Message):
    """/list: Shows all Telegram users/mentions who participated."""
    chat_id = message.chat.id
    participants_map, _, _, display_names_map, _, _ = get_session_data(chat_id) 
    
    participating_user_ids = participants_map.keys()
    sorted_users = sorted([display_names_map.get(uid) for uid in participating_user_ids if uid in display_names_map])
    
    user_list = "\n• ".join(sorted_users)
    response = "USERS PARTICIPATED ✅\n\n• " + (user_list if user_list else "No users have participated yet. ⏳")
    
    await message.reply(response, parse_mode="HTML") 
    logger.info(f"Admin {message.from_user.id} requested /list in chat {chat_id}.")

async def cmd_xlist(message: types.Message):
    """/xlist: Shows all extracted X usernames."""
    chat_id = message.chat.id
    _, x_handles_map, _, _, _, _ = get_session_data(chat_id)
    
    x_handle_list = "\n• ".join(sorted(x_handles_map.values()))
    response = "ALL X ID'S WHO HAVE PARTICIPATED ✅\n\n• " + (x_handle_list if x_handle_list else "No X handles found yet. ⏳")
    
    await message.reply(response)
    logger.info(f"Admin {message.from_user.id} requested /xlist in chat {chat_id}.")

async def cmd_adlist(message: types.Message):
    """/adlist: Lists Telegram users/mentions who completed engagement."""
    chat_id = message.chat.id
    _, _, completed_users_map, display_names_map, _, _ = get_session_data(chat_id)
    
    completed_display_names = [
        display_names_map[user_id] 
        for user_id, status in completed_users_map.items() if status
    ]
    
    user_list = "\n• ".join(sorted(completed_display_names))
    response = "USERS WHO COMPLETED ENGAGEMENT ✅\n\n• " + (user_list if user_list else "No users have completed engagement yet. ⏳")
    
    await message.reply(response, parse_mode="HTML")
    logger.info(f"Admin {message.from_user.id} requested /adlist in chat {chat_id}.")

async def cmd_notad(message: types.Message):
    """/notad: Finds users who haven't completed engagement."""
    chat_id = message.chat.id
    participants_map, _, completed_users_map, display_names_map, _, _ = get_session_data(chat_id)
    
    all_participants_ids = set(participants_map.keys())
    completed_ids = {user_id for user_id, status in completed_users_map.items() if status}
    not_completed_ids = all_participants_ids - completed_ids
    
    if not_completed_ids:
        not_completed_display_names = [display_names_map[user_id] for user_id in not_completed_ids]
        user_list = "\n• ".join(sorted(not_completed_display_names))
        response = "USERS WHO HAVE NOT COMPLETED ⚠️\n\n• " + user_list
    else:
        response = "All users completed engagement ✅"
        
    await message.reply(response, parse_mode="HTML")
    logger.info(f"Admin {message.from_user.id} requested /notad in chat {chat_id}.")

async def set_chat_lock_state(chat_id: int, bot: Bot, lock: bool):
    """Helper function to set chat permissions safely."""
    permissions = ChatPermissions(
        can_send_messages=not lock, 
        can_send_media_messages=not lock,
        can_send_polls=not lock,
        can_send_other_messages=not lock,
        can_add_web_page_previews=not lock,
        can_change_info=not lock,
        can_invite_users=not lock,
        can_pin_messages=not lock
    )
    try:
        await bot.set_chat_permissions(chat_id=chat_id, permissions=permissions)
        chat_locks[chat_id] = lock
        return True
    except Exception as e:
        logger.error(f"Failed to set chat permissions for chat {chat_id} (lock={lock}): {e}")
        if lock:
            await bot.send_message(chat_id, "🚨 Error: Failed to lock chat. Check bot permissions.")
        else:
            await bot.send_message(chat_id, "🚨 Error: Failed to unlock chat. Check bot permissions.")
        return False

async def cmd_lock(message: types.Message, bot: Bot):
    """/lock: Locks the group chat (prevents all non-admin messages/media)."""
    if await set_chat_lock_state(message.chat.id, bot, lock=True):
        await message.reply("Group chat locked 🔒. Only admins can send messages.")
        logger.info(f"Admin {message.from_user.id} locked chat {message.chat.id} via /lock.")

async def cmd_unlock(message: types.Message, bot: Bot):
    """/unlock: Unlocks the group chat (allows all members to send messages/media)."""
    if await set_chat_lock_state(message.chat.id, bot, lock=False):
        await message.reply("Group chat unlocked 🔓.")
        logger.info(f"Admin {message.from_user.id} unlocked chat {message.chat.id} via /unlock.")

async def cmd_stop(message: types.Message):
    """/stop: Sets the bot session to inactive (idle state) but does NOT lock the chat."""
    chat_id = message.chat.id
    
    clear_data(chat_id)
    session_active[chat_id] = False 
    
    await message.reply("Bot session stopped (IDLE). ⏸️")
    logger.info(f"Admin {message.from_user.id} idled the bot session in chat {chat_id} via /stop.")

async def cmd_detect(message: types.Message):
    """/detect: Announces the start of the engagement phase."""
    
    response = 'IF YOU HAVE COMPLETED ENGAGEMENT START SENDING "AD" ✅'
    await message.reply(response)
    logger.info(f"Admin {message.from_user.id} started /detect (engagement phase) in chat {message.chat.id}.")

# --- Handler for Non-Text Messages (Ensures 100% update coverage) ---

async def handle_non_text_messages(message: types.Message):
    """Handles non-text updates (photos, stickers, service messages) to prevent 'is not handled' warnings."""
    if not message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        return

    chat_id = message.chat.id
    _, _, _, _, _, chat_is_locked = get_session_data(chat_id)
    
    if chat_is_locked and message.from_user:
        try:
            # Only delete if not an admin
            if not await is_admin(chat_id, message.from_user.id, message.bot):
                 await message.delete()
        except Exception as e:
            logger.warning(f"Could not delete non-text message in locked chat {chat_id}: {e}")

# --- Handler for User Messages (Link Sharing and AD/Done) ---

async def handle_user_messages(message: types.Message):
    """Handles link sharing and 'AD' messages from regular users."""
    
    if not message.from_user or not message.text:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    user_text = message.text.strip()
    
    participants_map, x_handles_map, completed_users_map, display_names_map, session_is_active, chat_is_locked = get_session_data(chat_id)
    is_user_admin = await is_admin(chat_id, user_id, message.bot)

    # If the chat is locked, delete non-admin messages and stop processing
    if chat_is_locked and not is_user_admin:
        try:
            await message.delete()
        except Exception:
            pass 
        return
        
    # 1. Handle "AD/Done" messages
    ad_keywords = {"ad", "done", "all done", "completed"}
    if user_text.lower() in ad_keywords:
        
        if not session_is_active:
            return

        recorded_links = participants_map.get(user_id) 
        
        if not recorded_links:
            await message.reply("Your link hasn't been recorded yet. Please send your X link first. ⚠️")
            return

        completed_users_map[user_id] = True
        
        user_mention = display_names_map.get(user_id, get_user_mention(message.from_user))
        last_recorded_link = recorded_links[-1] 
        
        response = (
            f"ENGAGEMENT RECORDED 👍 for {user_mention}\n"
            f"Their X link:\n{last_recorded_link}" 
        )
        try:
             await message.reply(response, parse_mode="HTML") 
        except Exception as e:
             logger.error(f"Failed to reply to AD/Done message in chat {chat_id}: {e}")
             
        logger.info(f"AD/Done recorded for {user_id} in chat {chat_id}.")
        return

    # 2. Handle Link Sharing
    if is_x_link(user_text):
        
        if not session_is_active:
             await message.reply("The bot session is currently idle. Please wait for an admin to start a new session with /send. ⏸️")
             return
            
        user_links = participants_map.setdefault(user_id, [])
        if len(user_links) >= MAX_LINKS_PER_USER:
            # Delete message for exceeding limit
            try:
                await message.delete()
            except Exception:
                pass
            return
            
        x_username = extract_x_username(user_text)
        
        if not x_username:
            await message.reply("Could not extract an X username from the link. Please ensure it's a valid `x.com/<username>/status/...` link. 🚨")
            return
            
        # SILENT TRACKING: Store data without replying to the user
        user_links.append(user_text) 
        if user_id not in x_handles_map:
            x_handles_map[user_id] = x_username
        
        completed_users_map[user_id] = False 
        display_names_map[user_id] = get_user_mention(message.from_user) 

        # LOGGING is the only output for link submission
        link_count = len(user_links)
        logger.info(f"Link {link_count} received silently from {user_id} in chat {chat_id}. X Handle: {x_username}.")

# --- Error Handling ---

async def on_error(update: types.Update, exception: Exception):
    """
    Global error handler for all unhandled exceptions. 
    Logs the error but prevents the Dispatcher from crashing.
    """
    logger.error(f"Unhandled exception during update processing: {exception}", exc_info=True)

# --- Main Bot Setup ---

def setup_bot_handlers(dp: Dispatcher, admin_filter: GroupAdminFilter):
    """Registers all command and message handlers."""
    
    # Admin Commands
    dp.message.register(cmd_send, Command("send"), admin_filter)
    dp.message.register(cmd_list, Command("list"), admin_filter)
    dp.message.register(cmd_xlist, Command("xlist"), admin_filter)
    dp.message.register(cmd_adlist, Command("adlist"), admin_filter)
    dp.message.register(cmd_notad, Command("notad"), admin_filter)
    dp.message.register(cmd_refresh, Command("refresh"), admin_filter)
    dp.message.register(cmd_lock, Command("lock"), admin_filter) 
    dp.message.register(cmd_unlock, Command("unlock"), admin_filter) 
    dp.message.register(cmd_stop, Command("stop"), admin_filter)
    dp.message.register(cmd_detect, Command("detect"), admin_filter)
    # /rs command is removed.
    
    # 1. Catch-all for TEXT messages (User activity)
    dp.message.register(
        handle_user_messages, 
        F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), 
        F.text
    )
    
    # 2. Catch-all for NON-TEXT messages (Service, Photos, Stickers, etc.)
    dp.message.register(
        handle_non_text_messages,
        F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
        ~F.text 
    )
    
    # Global Error Handler
    dp.error.register(on_error)
    logger.info("Bot handlers registered successfully.")
    
# --- Keep-Alive Web Server (FastAPI) ---

app = FastAPI(title="Bot Keep-Alive")

@app.head("/") 
@app.get("/")
def read_root():
    """Simple health check endpoint for UptimeRobot/Render."""
    return Response(status_code=200)

async def run_webserver():
    """Runs the FastAPI server using uvicorn."""
    port = int(os.getenv("PORT", 8080))
    config = uvicorn.Config(
        app, 
        host="0.0.0.0", 
        port=port, 
        log_level="info",
        lifespan="off"
    )
    server = uvicorn.Server(config)
    logger.info(f"Starting Keep-Alive Webserver on port {port}...")
    await server.serve()

# --- Main Entry Point (Designed for Auto-Restart) ---

async def main():
    """The main entry point for the bot and webserver."""
    
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML")
    )
    dp = Dispatcher()
    
    admin_filter = GroupAdminFilter()
    setup_bot_handlers(dp, admin_filter)

    web_task = asyncio.create_task(run_webserver())
    
    try:
        logger.info("Starting AIOGram Bot Polling...")
        await dp.start_polling(bot)
    except Exception as e:
        # If polling fails (e.g., due to TelegramConflictError)
        logger.critical(f"FATAL POLLING ERROR: Polling loop crashed. Preparing for restart: {e}", exc_info=True)
        web_task.cancel()
        # Non-zero exit code (1) triggers the hosting service to restart
        sys.exit(1)
        
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        logger.info("Starting production AIOGram Bot...")
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shutting down due to Keyboard Interrupt.")
    except Exception as e:
        logger.critical(f"Bot failed to start or shut down unexpectedly: {e}")
