import asyncio
import logging
import os
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramNetworkError
from dotenv import load_dotenv
from fastapi import FastAPI
import uvicorn

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = -1003233403243  # SOCIALFI ADDA 👁‍🗨 group

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Data stores (in-memory)
participants = {}
x_handles = {}
completed_users = set()

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# FastAPI keep-alive app for Render + UptimeRobot
app = FastAPI()

@app.get("/")
async def home():
    return {"status": "✅ Bot running fine"}

# --- Utility Functions ---
async def is_admin(user_id: int) -> bool:
    try:
        admins = await bot.get_chat_administrators(GROUP_ID)
        return any(admin.user.id == user_id for admin in admins)
    except Exception as e:
        logging.error(f"Admin check failed: {e}")
        return False

async def safe_send(chat_id, text):
    try:
        await bot.send_message(chat_id, text)
    except TelegramRetryAfter as e:
        logging.warning(f"Rate limited, retrying in {e.retry_after}s")
        await asyncio.sleep(e.retry_after)
        await safe_send(chat_id, text)
    except (TelegramNetworkError, TelegramForbiddenError) as e:
        logging.error(f"Telegram network error: {e}")
    except Exception as e:
        logging.exception(f"Send failed: {e}")

# --- Bot Commands ---
@dp.message(Command("send"))
async def start_send(msg: types.Message):
    if msg.chat.id != GROUP_ID or not await is_admin(msg.from_user.id):
        return
    participants.clear()
    x_handles.clear()
    completed_users.clear()
    await safe_send(GROUP_ID, "START SENDING LINK 🔗")

@dp.message(Command("list"))
async def show_list(msg: types.Message):
    if msg.chat.id != GROUP_ID:
        return
    if not participants:
        await safe_send(GROUP_ID, "No users have sent links yet.")
        return
    lines = [f"• @{user}" for user in participants.keys()]
    await safe_send(GROUP_ID, "USERS PARTICIPATED ✅\n" + "\n".join(lines))

@dp.message(Command("xlist"))
async def show_xlist(msg: types.Message):
    if msg.chat.id != GROUP_ID:
        return
    if not x_handles:
        await safe_send(GROUP_ID, "No X handles detected yet.")
        return
    lines = [f"• {x}" for x in x_handles.values()]
    await safe_send(GROUP_ID, "ALL X ID'S WHO HAVE PARTICIPATED ✅\n" + "\n".join(lines))

@dp.message(Command("detect"))
async def detect_start(msg: types.Message):
    if msg.chat.id != GROUP_ID:
        return
    await safe_send(GROUP_ID, "IF YOU HAVE COMPLETED ENGAGEMENT START SENDING 'AD' ✅")

@dp.message(Command("adlist"))
async def show_adlist(msg: types.Message):
    if msg.chat.id != GROUP_ID:
        return
    if not completed_users:
        await safe_send(GROUP_ID, "No one has completed engagement yet.")
        return
    lines = [f"• @{u}" for u in completed_users]
    await safe_send(GROUP_ID, "USERS WHO COMPLETED ENGAGEMENT ✅\n" + "\n".join(lines))

@dp.message(Command("notad"))
async def show_notad(msg: types.Message):
    if msg.chat.id != GROUP_ID:
        return
    not_done = set(participants.keys()) - completed_users
    if not not_done:
        await safe_send(GROUP_ID, "All users completed engagement ✅")
    else:
        lines = [f"• @{u}" for u in not_done]
        await safe_send(GROUP_ID, "USERS WHO HAVE NOT COMPLETED ⚠️\n" + "\n".join(lines))

@dp.message(Command("refresh"))
async def refresh(msg: types.Message):
    if msg.chat.id != GROUP_ID or not await is_admin(msg.from_user.id):
        return
    participants.clear()
    x_handles.clear()
    completed_users.clear()
    await safe_send(GROUP_ID, "STARTING CLEANUP 🧹\nData cleared successfully 🧽")

@dp.message(Command("rs"))
async def rules(msg: types.Message):
    if msg.chat.id != GROUP_ID:
        return
    rules_text = (
        "📜 SOCIALFI ADDA 👁‍🗨 — Group Rules & How It Works\n\n"
        "🔹 Sessions & Timing:\n"
        "• 2 sessions daily.\n"
        "👉 1st Session: 9:00 AM – 3:00 PM\n➡️ Engagement: 3:00 PM – 5:00 PM\n➡️ Admin Check: 5:00 PM – 5:30 PM\n"
        "👉 2nd Session: 6:00 PM – 8:00 PM IST\n✅ Engagement: 8:00 PM – 10:00 PM IST\n➡️ Admin Check: 10:00 PM – 11:00 PM\n\n"
        "🔹 Link Sharing:\n• Each user can send 2 links per session only.\n\n"
        "🔹 Engagement Rule:\n• Engage with all links shared in GC.\n"
        "• After engaging, react on each link.\n"
        "• Then type 'AD' which means ALL DONE ✔️ in the group.\n\n"
        "🔹 Penalties:\n• Missed engagement = 24h mute 🔇\n• Repeated misses = ban ✅\n"
        "Stay active, engage genuinely & grow together 🚀"
    )
    await safe_send(GROUP_ID, rules_text)

# --- Message Handlers ---
@dp.message(F.text)
async def handle_text(msg: types.Message):
    if msg.chat.id != GROUP_ID:
        return

    username = msg.from_user.username or msg.from_user.full_name

    # Detect link submissions
    if "x.com/" in msg.text:
        match = re.search(r"x\.com/([A-Za-z0-9_]+)/status", msg.text)
        if match:
            x_user = match.group(1)
            participants[username] = msg.text
            x_handles[username] = x_user
            await safe_send(GROUP_ID, f"✅ Link from @{username} recorded ({x_user})")
        return

    # Detect "AD" / done messages
    if msg.text.lower().strip() in ["ad", "done", "all done", "completed"]:
        if username in participants:
            completed_users.add(username)
            await safe_send(GROUP_ID, f"ENGAGEMENT RECORDED 👍 for @{username}\nTheir X link:\n{participants[username]}")
        else:
            await safe_send(GROUP_ID, "No link found for you earlier ❌")
        return

# --- Startup ---
async def main():
    logging.info("Starting bot...")
    while True:
        try:
            await dp.start_polling(bot)
        except Exception as e:
            logging.error(f"Polling error: {e}")
            await asyncio.sleep(5)  # Retry after short delay

# --- Run Bot & Keep-alive ---
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main())

    # Start FastAPI keep-alive server
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
