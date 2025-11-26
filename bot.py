import asyncio
import logging
import os
import re
import sys 
from typing import Dict, Any, Optional, Union, List

# --- Core Dependencies ---
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, Filter
from aiogram.enums import ChatType
from aiogram.types import ChatPermissions
from aiogram.client.default import DefaultBotProperties 

# --- 🧠 General Setup ---

# *** MANDATORY: YOUR ACTUAL BOT TOKEN INSERTED HERE ***
BOT_TOKEN = "8234561981:AAGlkXuuwz1eAD8HTRLdhNrnh5C0tK1lWug" 
# *********************************************************

if BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE" or not BOT_TOKEN:
    logging.getLogger(__name__).critical("FATAL: BOT_TOKEN is not set. Please replace the placeholder value.")
    sys.exit(1)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- In-Memory Data Storage (Data IS NOT persistent across restarts) ---
participants: Dict[int, Dict[int, List[str]]] = {} 
x_handles: Dict[int, Dict[int, str]] = {}
completed_users: Dict[int, Dict[int, bool]] = {}
display_names: Dict[int, Dict[int, str]] = {}
session_active: Dict[int, bool] = {} 
chat_locks: Dict[int, bool] = {} 

MAX_LINKS_PER_USER = 2
X_LINK_REGEX = re.compile(r"https?:\/\/(?:www\.)?(?:x\.com|twitter\.com)\/([a-zA-Z0-9_]+)\/status\/\d+")

# --- Core Helper Functions and Handlers (Complete) ---

def get_user_mention(user: types.User) -> str:
    """Creates a clickable HTML mention for a user."""
    if user.username:
        return f"@{user.username}"
    name = user.full_name or "Participant"
    return f'<a href="tg://user?id={user.id}">{name}</a>' 

async def is_admin(chat_id: int, user_id: int, bot: Bot) -> bool:
    """Checks if a user is an admin in the specified chat."""
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
    """Initializes and retrieves session data for a given chat from global dictionaries."""
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

class GroupAdminFilter(Filter):
    """Filter that only allows messages from admins of the current group/supergroup chat."""
    async def __call__(self, message: types.Message, bot: Bot) -> bool:
        if message.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]: return False
        if message.from_user: return await is_admin(message.chat.id, message.from_user.id, bot)
        return False
        
async def set_chat_lock_state(chat_id: int, bot: Bot, lock: bool):
    """Helper function to set chat permissions safely and update database."""
    permissions = ChatPermissions(can_send_messages=not lock, can_send_media_messages=not lock)
    try:
        await bot.set_chat_permissions(chat_id=chat_id, permissions=permissions)
        chat_locks[chat_id] = lock
        return True
    except Exception as e:
        logger.error(f"Failed to set chat permissions for chat {chat_id} (lock={lock}): {e}")
        await bot.send_message(chat_id, "🚨 Error: Failed to change chat lock state. Check bot permissions.")
        return False
        
async def cmd_send(message: types.Message):
    chat_id = message.chat.id
    links_cleared_count = clear_data(chat_id) 
    session_active[chat_id] = True 
    await message.reply(f"Links are open 🔗. Cleared {links_cleared_count} old links.")

async def cmd_refresh(message: types.Message):
    chat_id = message.chat.id
    await message.reply("STARTING CLEANUP 🧹")
    links_cleared_count = clear_data(chat_id) 
    session_active[chat_id] = False 
    await message.reply(f"Data for {links_cleared_count} links cleared. Session idled. ✅") 

async def cmd_list(message: types.Message):
    chat_id = message.chat.id
    participants_map, _, _, display_names_map, _, _ = get_session_data(chat_id) 
    participating_user_ids = participants_map.keys()
    sorted_users = sorted([display_names_map.get(uid) for uid in participating_user_ids if uid in display_names_map])
    user_list = "\n• ".join(sorted(sorted_users))
    response = "USERS PARTICIPATED ✅\n\n• " + (user_list if user_list else "No users have participated yet. ⏳")
    await message.reply(response, parse_mode="HTML") 

async def cmd_xlist(message: types.Message):
    chat_id = message.chat.id
    _, x_handles_map, _, _, _, _ = get_session_data(chat_id)
    x_handle_list = "\n• ".join(sorted(x_handles_map.values()))
    response = "ALL X ID'S WHO HAVE PARTICIPATED ✅\n\n• " + (x_handle_list if x_handle_list else "No X handles found yet. ⏳")
    await message.reply(response)

async def cmd_adlist(message: types.Message):
    chat_id = message.chat.id
    _, _, completed_users_map, display_names_map, _, _ = get_session_data(chat_id)
    completed_display_names = [display_names_map[user_id] for user_id, status in completed_users_map.items() if status]
    user_list = "\n• ".join(sorted(completed_display_names))
    response = "USERS WHO COMPLETED ENGAGEMENT ✅\n\n• " + (user_list if user_list else "No users have completed engagement yet. ⏳")
    await message.reply(response, parse_mode="HTML")

async def cmd_notad(message: types.Message):
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

async def cmd_lock(message: types.Message, bot: Bot):
    if await set_chat_lock_state(message.chat.id, bot, lock=True):
        await message.reply("Group chat locked 🔒. Only admins can send messages.")

async def cmd_unlock(message: types.Message, bot: Bot):
    if await set_chat_lock_state(message.chat.id, bot, lock=False):
        await message.reply("Group chat unlocked 🔓.")

async def cmd_stop(message: types.Message):
    chat_id = message.chat.id
    session_active[chat_id] = False
    await message.reply("Bot session stopped (IDLE). ⏸️")

async def cmd_detect(message: types.Message):
    response = 'IF YOU HAVE COMPLETED ENGAGEMENT START SENDING "AD" ✅'
    await message.reply(response)

async def handle_non_text_messages(message: types.Message):
    if not message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP] or not message.from_user: return
    chat_id = message.chat.id
    _, _, _, _, _, chat_is_locked = get_session_data(chat_id)
    if chat_is_locked:
        try:
            if not await is_admin(chat_id, message.from_user.id, message.bot): await message.delete()
        except Exception: pass 

async def handle_user_messages(message: types.Message):
    if not message.from_user or not message.text: return
    chat_id = message.chat.id
    user_id = message.from_user.id
    user_text = message.text.strip()
    participants_map, x_handles_map, completed_users_map, display_names_map, session_is_active, chat_is_locked = get_session_data(chat_id)
    is_user_admin = await is_admin(chat_id, user_id, message.bot)
    
    # 1. Chat Lock Filter
    if chat_is_locked and not is_user_admin:
        try: await message.delete()
        except Exception: pass 
        return
        
    # 2. Handle "AD/Done" messages
    ad_keywords = {"ad", "done", "all done", "completed"}
    if user_text.lower() in ad_keywords:
        if not session_is_active:
            await message.reply("The session is paused. ⏸️")
            return
        recorded_links = participants_map.get(user_id) 
        if not recorded_links:
            await message.reply("Your link hasn't been recorded yet. Please send your X link first. ⚠️")
            return
        completed_users_map[user_id] = True
        user_mention = display_names_map.get(user_id, get_user_mention(message.from_user))
        last_recorded_link = recorded_links[-1] 
        response = (f"ENGAGEMENT RECORDED 👍 for {user_mention}\n" f"Their last X link:\n{last_recorded_link}")
        try: await message.reply(response, parse_mode="HTML") 
        except Exception as e: logger.error(f"Failed to reply to AD/Done message in chat {chat_id}: {e}")
        return

    # 3. Handle Link Sharing (SILENTLY)
    if is_x_link(user_text):
        if not session_is_active:
             await message.reply("The bot session is currently idle. ⏸️")
             return
        user_links = participants_map.setdefault(user_id, [])
        if len(user_links) >= MAX_LINKS_PER_USER:
            try: await message.delete()
            except Exception: pass
            return
        x_username = extract_x_username(user_text)
        if not x_username:
            await message.reply("Could not extract X username. Please ensure it's a valid link. 🚨")
            return
        user_links.append(user_text) 
        x_handles_map[user_id] = x_username
        completed_users_map[user_id] = False 
        display_names_map[user_id] = get_user_mention(message.from_user) 
        logger.info(f"Link {len(user_links)} received silently from {user_id} in chat {chat_id}. X Handle: {x_username}.")

# --- Polling Setup ---

async def main():
    """Initializes the bot and starts polling for updates."""
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML")
    )
    dp = Dispatcher()
    
    # Register all handlers
    admin_filter = GroupAdminFilter()
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

    dp.message.register(
        handle_user_messages, 
        F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), 
        F.text
    )
    dp.message.register(
        handle_non_text_messages,
        F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
        ~F.text 
    )

    # Start polling
    logger.info("Starting Telegram Bot in Polling Mode...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shut down manually.")
    except Exception as e:
        logger.critical(f"FATAL POLLING ERROR: Bot crashed: {e}", exc_info=True)
        sys.exit(1)
