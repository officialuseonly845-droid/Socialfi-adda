"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                     SOCIALFI ADDA 👁‍🗨 TELEGRAM BOT                          ║
║                        Production-Ready Version                              ║
╚══════════════════════════════════════════════════════════════════════════════╝

🚀 DEPLOYMENT INSTRUCTIONS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Set these environment variables on Render:
   - BOT_TOKEN=your_telegram_bot_token
   - ADMIN_IDS=123456789,987654321
   - GROUP_ID=-1001234567890

2. Deploy to Render:
   - Build Command: pip install -r requirements.txt
   - Start Command: python bot.py

3. Keep alive with Uptime Robot:
   - Monitor type: HTTP(s)
   - URL: https://your-app.onrender.com (if you add a health endpoint)
   - Interval: 5 minutes

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import re
import sys
import asyncio
import logging
import traceback
from datetime import datetime
from typing import Optional, List, Set
import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, ChatPermissions
from aiogram.filters import Command
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter, TelegramBadRequest

# ═══════════════════════════════════════════════════════════════════════════
# 🔧 CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
GROUP_ID_STR = os.getenv("GROUP_ID", "")

# Parse admin IDs
try:
    ADMIN_IDS = set(int(x.strip()) for x in ADMIN_IDS_STR.split(",") if x.strip())
except:
    ADMIN_IDS = set()

# Parse group ID
try:
    GROUP_ID = int(GROUP_ID_STR)
except:
    GROUP_ID = None

DB_PATH = "socialfi_adda.db"

# ═══════════════════════════════════════════════════════════════════════════
# 📝 LOGGING CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# 🗄️ DATABASE INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════

async def init_database():
    """
    Initialize SQLite database with all required tables.
    Creates tables if they don't exist - safe for first run and restarts.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Users table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Sessions table - tracks each link submission session
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    active INTEGER DEFAULT 1,
                    created_by INTEGER
                )
            """)
            
            # Links table - stores all submitted X/Twitter links
            await db.execute("""
                CREATE TABLE IF NOT EXISTS links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    telegram_id INTEGER,
                    username TEXT,
                    link TEXT,
                    handle TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                )
            """)
            
            # Engagement table - tracks who completed engagement
            await db.execute("""
                CREATE TABLE IF NOT EXISTS engagement (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    telegram_id INTEGER,
                    username TEXT,
                    completed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(session_id, telegram_id),
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                )
            """)
            
            await db.commit()
            logger.info("✅ Database initialized successfully")
            
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        logger.error(traceback.format_exc())
        raise

# ═══════════════════════════════════════════════════════════════════════════
# 🔒 DATABASE OPERATIONS WITH LOCKING
# ═══════════════════════════════════════════════════════════════════════════

db_lock = asyncio.Lock()

async def get_active_session() -> Optional[int]:
    """Get current active session ID, returns None if no active session"""
    async with db_lock:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT id FROM sessions WHERE active = 1 ORDER BY id DESC LIMIT 1"
                ) as cursor:
                    row = await cursor.fetchone()
                    return row[0] if row else None
        except Exception as e:
            logger.error(f"Error getting active session: {e}")
            return None

async def create_new_session(admin_id: int) -> int:
    """
    Create new session and deactivate all previous ones.
    Returns new session ID.
    """
    async with db_lock:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                # Deactivate all previous sessions
                await db.execute("UPDATE sessions SET active = 0")
                
                # Create new session
                cursor = await db.execute(
                    "INSERT INTO sessions (start_time, active, created_by) VALUES (?, 1, ?)",
                    (datetime.now(), admin_id)
                )
                await db.commit()
                session_id = cursor.lastrowid
                logger.info(f"✅ New session created: #{session_id} by admin {admin_id}")
                return session_id
        except Exception as e:
            logger.error(f"Error creating session: {e}")
            raise

async def get_user_link_count(session_id: int, telegram_id: int) -> int:
    """Get number of links user has submitted in current session"""
    async with db_lock:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT COUNT(*) FROM links WHERE session_id = ? AND telegram_id = ?",
                    (session_id, telegram_id)
                ) as cursor:
                    row = await cursor.fetchone()
                    return row[0] if row else 0
        except Exception as e:
            logger.error(f"Error counting user links: {e}")
            return 0

async def save_link(session_id: int, telegram_id: int, username: str, link: str, handle: str):
    """Save a submitted link to database"""
    async with db_lock:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """INSERT INTO links (session_id, telegram_id, username, link, handle)
                       VALUES (?, ?, ?, ?, ?)""",
                    (session_id, telegram_id, username or "Unknown", link, handle)
                )
                await db.commit()
                logger.info(f"💾 Link saved: @{username} → {handle}")
        except Exception as e:
            logger.error(f"Error saving link: {e}")

async def get_session_participants(session_id: int) -> List[str]:
    """Get list of usernames who participated in session"""
    async with db_lock:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT DISTINCT username FROM links WHERE session_id = ? ORDER BY username",
                    (session_id,)
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [f"@{row[0]}" if row[0] else "Unknown" for row in rows]
        except Exception as e:
            logger.error(f"Error getting participants: {e}")
            return []

async def get_session_handles(session_id: int) -> List[str]:
    """Get list of X handles from session"""
    async with db_lock:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT DISTINCT handle FROM links WHERE session_id = ? AND handle IS NOT NULL ORDER BY handle",
                    (session_id,)
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [f"@{row[0]}" for row in rows if row[0]]
        except Exception as e:
            logger.error(f"Error getting handles: {e}")
            return []

async def save_engagement(session_id: int, telegram_id: int, username: str):
    """Record that user completed engagement"""
    async with db_lock:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """INSERT OR IGNORE INTO engagement (session_id, telegram_id, username)
                       VALUES (?, ?, ?)""",
                    (session_id, telegram_id, username or "Unknown")
                )
                await db.commit()
                logger.info(f"✅ Engagement recorded: @{username} (ID: {telegram_id})")
        except Exception as e:
            logger.error(f"Error saving engagement: {e}")

async def get_user_links(session_id: int, telegram_id: int) -> List[str]:
    """Get user's submitted links from current session"""
    async with db_lock:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT link FROM links WHERE session_id = ? AND telegram_id = ?",
                    (session_id, telegram_id)
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"Error getting user links: {e}")
            return []

async def get_engagement_list(session_id: int) -> List[str]:
    """Get list of usernames who completed engagement"""
    async with db_lock:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT DISTINCT username FROM engagement WHERE session_id = ? ORDER BY username",
                    (session_id,)
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [f"@{row[0]}" if row[0] else "Unknown" for row in rows]
        except Exception as e:
            logger.error(f"Error getting engagement list: {e}")
            return []

# ═══════════════════════════════════════════════════════════════════════════
# 🛠️ UTILITY FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def extract_x_handle(link: str) -> Optional[str]:
    """
    Extract X/Twitter handle from link.
    Supports: x.com/username, twitter.com/username
    """
    try:
        # Match x.com or twitter.com links
        pattern = r'(?:https?://)?(?:www\.)?(?:x\.com|twitter\.com)/([a-zA-Z0-9_]+)'
        match = re.search(pattern, link)
        if match:
            return match.group(1)
        return None
    except Exception as e:
        logger.error(f"Error extracting handle: {e}")
        return None

def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id in ADMIN_IDS

async def safe_delete_message(bot: Bot, chat_id: int, message_id: int) -> bool:
    """
    Safely delete a message with exponential backoff retry.
    Returns True if successful, False otherwise.
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            await bot.delete_message(chat_id, message_id)
            return True
        except TelegramRetryAfter as e:
            wait_time = e.retry_after
            logger.warning(f"Rate limited. Waiting {wait_time}s before retry...")
            await asyncio.sleep(wait_time)
        except TelegramBadRequest as e:
            # Message not found or can't be deleted
            logger.debug(f"Cannot delete message {message_id}: {e}")
            return False
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"Failed to delete message after {max_retries} attempts: {e}")
                return False
    return False

async def send_safe(message: Message, text: str, **kwargs):
    """
    Safely send message with error handling and retry logic.
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return await message.answer(text, **kwargs)
        except TelegramRetryAfter as e:
            wait_time = e.retry_after
            logger.warning(f"Rate limited. Waiting {wait_time}s...")
            await asyncio.sleep(wait_time)
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"Failed to send message: {e}")
                raise

# ═══════════════════════════════════════════════════════════════════════════
# 🎯 COMMAND HANDLERS (ADMIN-ONLY)
# ═══════════════════════════════════════════════════════════════════════════

router = Router()

@router.message(Command("send"))
async def cmd_send(message: Message):
    """
    /send - Start new link submission session
    Admin-only command to unlock group for link submissions
    """
    try:
        # Check admin
        if not is_admin(message.from_user.id):
            return  # Silently ignore non-admin
        
        # Create new session
        session_id = await create_new_session(message.from_user.id)
        
        await send_safe(message, "START SENDING LINK 🔗")
        logger.info(f"📣 /send executed by admin {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"Error in /send: {e}")
        logger.error(traceback.format_exc())
        await send_safe(message, "⚠️ Error occurred but bot is still running.")

@router.message(Command("list"))
async def cmd_list(message: Message):
    """
    /list - Show all users who participated in current session
    """
    try:
        if not is_admin(message.from_user.id):
            return
        
        session_id = await get_active_session()
        if not session_id:
            await send_safe(message, "❌ No active session. Use /send first.")
            return
        
        participants = await get_session_participants(session_id)
        
        if participants:
            text = "USERS PARTICIPATED ✅\n\n" + "\n".join(participants)
        else:
            text = "USERS PARTICIPATED ✅\n\nNo participants yet."
        
        await send_safe(message, text)
        logger.info(f"📋 /list executed: {len(participants)} participants")
        
    except Exception as e:
        logger.error(f"Error in /list: {e}")
        logger.error(traceback.format_exc())
        await send_safe(message, "⚠️ Error occurred but bot is still running.")

@router.message(Command("xlist"))
async def cmd_xlist(message: Message):
    """
    /xlist - Show all X handles from current session
    """
    try:
        if not is_admin(message.from_user.id):
            return
        
        session_id = await get_active_session()
        if not session_id:
            await send_safe(message, "❌ No active session.")
            return
        
        handles = await get_session_handles(session_id)
        
        if handles:
            text = "ALL X ID'S WHO HAVE PARTICIPATED ✅\n\n" + "\n".join(handles)
        else:
            text = "ALL X ID'S WHO HAVE PARTICIPATED ✅\n\nNo X handles yet."
        
        await send_safe(message, text)
        logger.info(f"🐦 /xlist executed: {len(handles)} handles")
        
    except Exception as e:
        logger.error(f"Error in /xlist: {e}")
        logger.error(traceback.format_exc())
        await send_safe(message, "⚠️ Error occurred but bot is still running.")

@router.message(Command("detect"))
async def cmd_detect(message: Message):
    """
    /detect - Start engagement detection mode
    """
    try:
        if not is_admin(message.from_user.id):
            return
        
        session_id = await get_active_session()
        if not session_id:
            await send_safe(message, "❌ No active session.")
            return
        
        await send_safe(message, "IF YOU HAVE COMPLETED ENGAGEMENT START SENDING 'AD' ✅")
        logger.info(f"🔍 /detect executed by admin {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"Error in /detect: {e}")
        logger.error(traceback.format_exc())
        await send_safe(message, "⚠️ Error occurred but bot is still running.")

@router.message(Command("adlist"))
async def cmd_adlist(message: Message):
    """
    /adlist - Show users who completed engagement
    """
    try:
        if not is_admin(message.from_user.id):
            return
        
        session_id = await get_active_session()
        if not session_id:
            await send_safe(message, "❌ No active session.")
            return
        
        completed = await get_engagement_list(session_id)
        
        if completed:
            text = "COMPLETED ENGAGEMENT ✅\n\n" + "\n".join(completed)
        else:
            text = "COMPLETED ENGAGEMENT ✅\n\nNo one yet."
        
        await send_safe(message, text)
        logger.info(f"✅ /adlist executed: {len(completed)} completed")
        
    except Exception as e:
        logger.error(f"Error in /adlist: {e}")
        logger.error(traceback.format_exc())
        await send_safe(message, "⚠️ Error occurred but bot is still running.")

@router.message(Command("notad"))
async def cmd_notad(message: Message):
    """
    /notad - Show users who haven't completed engagement
    """
    try:
        if not is_admin(message.from_user.id):
            return
        
        session_id = await get_active_session()
        if not session_id:
            await send_safe(message, "❌ No active session.")
            return
        
        all_participants = set(await get_session_participants(session_id))
        completed = set(await get_engagement_list(session_id))
        not_completed = sorted(all_participants - completed)
        
        if not_completed:
            text = "NOT COMPLETED ENGAGEMENT ❌\n\n" + "\n".join(not_completed)
        else:
            text = "NOT COMPLETED ENGAGEMENT ❌\n\nEveryone completed! 🎉"
        
        await send_safe(message, text)
        logger.info(f"⚠️ /notad executed: {len(not_completed)} incomplete")
        
    except Exception as e:
        logger.error(f"Error in /notad: {e}")
        logger.error(traceback.format_exc())
        await send_safe(message, "⚠️ Error occurred but bot is still running.")

@router.message(Command("refresh"))
async def cmd_refresh(message: Message, bot: Bot):
    """
    /refresh - Clean up group messages
    Attempts to delete recent messages in the group
    """
    try:
        if not is_admin(message.from_user.id):
            return
        
        await send_safe(message, "STARTING CLEANUP 🧹")
        
        deleted_count = 0
        # Try to delete last 100 messages
        current_msg_id = message.message_id
        
        for i in range(1, 101):
            msg_id = current_msg_id - i
            if msg_id > 0:
                success = await safe_delete_message(bot, message.chat.id, msg_id)
                if success:
                    deleted_count += 1
                await asyncio.sleep(0.1)  # Small delay to avoid rate limits
        
        await send_safe(message, f"Cleaned {deleted_count} messages 🧽")
        logger.info(f"🧹 /refresh executed: {deleted_count} messages deleted")
        
    except Exception as e:
        logger.error(f"Error in /refresh: {e}")
        logger.error(traceback.format_exc())
        await send_safe(message, "⚠️ Error occurred but bot is still running.")

@router.message(Command("lock"))
async def cmd_lock(message: Message, bot: Bot):
    """
    /lock - Lock group chat (restrict all members)
    """
    try:
        if not is_admin(message.from_user.id):
            return
        
        # Set restrictive permissions
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False
        )
        
        await bot.set_chat_permissions(message.chat.id, permissions)
        await send_safe(message, "GROUP LOCKED 🔒")
        logger.info(f"🔒 /lock executed by admin {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"Error in /lock: {e}")
        logger.error(traceback.format_exc())
        await send_safe(message, "⚠️ Error occurred but bot is still running.")

@router.message(Command("rs"))
async def cmd_rules(message: Message):
    """
    /rs - Send group rules
    """
    try:
        if not is_admin(message.from_user.id):
            return
        
        rules_text = """📜 **SOCIALFI ADDA 👁‍🗨 — Group Rules & How It Works**

🔹 **Sessions & Timing:**
• 2 sessions daily.
👉 1st Session: 9:00 AM – 3:00 PM
➡️ Engagement: 3:00 PM – 5:00 PM
➡️ Admin Check: 5:00 PM – 5:30 PM
👉 2nd Session: 6:00 PM – 8:00 PM IST
✅ Engagement: 8:00 PM – 10:00 PM IST
➡️ Admin Check: 10:00 PM – 11:00 PM

🔹 **Link Sharing:**
• Each user can send 2 links per session only.

🔹 **Engagement Rule:**
• Engage with all links shared in GC.
• After engaging, react on each link.
• Then type **"AD"** which means **ALL DONE ✔️**

🔹 **Penalties:**
• Missed engagement = 24h mute 🔇
• Repeated misses = ban ✅

Stay active, engage genuinely & grow together 🚀"""
        
        await send_safe(message, rules_text)
        logger.info(f"📜 /rs executed by admin {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"Error in /rs: {e}")
        logger.error(traceback.format_exc())
        await send_safe(message, "⚠️ Error occurred but bot is still running.")

# ═══════════════════════════════════════════════════════════════════════════
# 📨 MESSAGE HANDLERS
# ═══════════════════════════════════════════════════════════════════════════

@router.message(F.text)
async def handle_text_message(message: Message):
    """
    Handle all text messages:
    1. X/Twitter links during active session
    2. Engagement confirmations (AD, done, etc.)
    """
    try:
        # Ignore private messages and non-group messages
        if message.chat.type not in ["group", "supergroup"]:
            return
        
        session_id = await get_active_session()
        if not session_id:
            return  # No active session, ignore
        
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        text = message.text.strip()
        
        # Check for engagement confirmation keywords
        engagement_keywords = ["ad", "done", "all done", "completed"]
        if text.lower() in engagement_keywords:
            # Get user's links
            user_links = await get_user_links(session_id, user_id)
            
            if user_links:
                # Save engagement
                await save_engagement(session_id, user_id, username)
                
                # Reply with confirmation and their links
                links_text = "\n".join(user_links)
                response = f"ENGAGEMENT RECORDED 👍\n\nYour links:\n{links_text}"
                await send_safe(message, response)
            else:
                await send_safe(message, "⚠️ You haven't submitted any links in this session.")
            return
        
        # Check for X/Twitter links
        x_pattern = r'(?:https?://)?(?:www\.)?(?:x\.com|twitter\.com)/[^\s]+'
        if re.search(x_pattern, text, re.IGNORECASE):
            # Check link count
            current_count = await get_user_link_count(session_id, user_id)
            
            if current_count >= 2:
                await send_safe(message, "❌ You've already submitted 2 links. Maximum reached.")
                return
            
            # Extract handle
            handle = extract_x_handle(text)
            
            # Save link
            await save_link(session_id, user_id, username, text, handle)
            
            remaining = 2 - (current_count + 1)
            if remaining > 0:
                await send_safe(message, f"✅ Link saved! You can submit {remaining} more link(s).")
            else:
                await send_safe(message, "✅ Link saved! You've reached your limit (2/2).")
        
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        logger.error(traceback.format_exc())
        # Don't send error message for regular messages

# ═══════════════════════════════════════════════════════════════════════════
# 🚀 BOT STARTUP & MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════

async def on_startup():
    """Initialize bot on startup"""
    logger.info("=" * 80)
    logger.info("🚀 SOCIALFI ADDA BOT STARTING...")
    logger.info("=" * 80)
    
    # Validate configuration
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN not set!")
        sys.exit(1)
    
    if not ADMIN_IDS:
        logger.error("❌ ADMIN_IDS not set!")
        sys.exit(1)
    
    logger.info(f"✅ Admin IDs: {ADMIN_IDS}")
    logger.info(f"✅ Group ID: {GROUP_ID}")
    
    # Initialize database
    await init_database()
    
    logger.info("✅ Bot ready to receive commands")
    logger.info("=" * 80)

async def on_shutdown():
    """Cleanup on shutdown"""
    logger.info("👋 Bot shutting down...")

async def main():
    """
    Main bot loop with error recovery.
    Bot will automatically restart on crashes.
    """
    while True:
        try:
            # Initialize bot and dispatcher
            bot = Bot(token=BOT_TOKEN)
            dp = Dispatcher()
            
            # Register router
            dp.include_router(router)
            
            # Register startup/shutdown
            dp.startup.register(on_startup)
            dp.shutdown.register(on_shutdown)
            
            # Start polling
            logger.info("🔄 Starting polling...")
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
            
        except KeyboardInterrupt:
            logger.info("🛑 Bot stopped by user")
            break
            
        except Exception as e:
            logger.error(f"💥 CRITICAL ERROR: {e}")
            logger.error(traceback.format_exc())
            logger.info("♻️ Restarting bot in 5 seconds...")
            await asyncio.sleep(5)

# ═══════════════════════════════════════════════════════════════════════════
# 🎬 ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Goodbye!")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        logger.error(traceback.format_exc())
