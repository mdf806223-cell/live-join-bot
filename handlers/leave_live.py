import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from database.models import get_all_sessions, set_user_state
from utils.validators import parse_live_link
from utils.keyboards import cancel_keyboard, back_home_keyboard
from utils.telegram_client import leave_live_stream, leave_all
from utils.state_filter import InState
from config import MAX_CONCURRENT

router = Router()


@router.callback_query(F.data == "leave_live")
@router.message(Command("leave"))
async def start_leave_live(update):
    msg = update if isinstance(update, Message) else update.message
    user_id = update.from_user.id
    await set_user_state(user_id, "awaiting_live_link_leave")
    text = (
        "🚪 **Leave Live Stream**\n"
        "───── ⚡ ─────\n\n"
        "🔗 Send the live link to leave,\n"
        "or type **ALL** to leave all active streams:"
    )
    if isinstance(update, CallbackQuery):
        await msg.edit_text(text, reply_markup=cancel_keyboard())
        await update.answer()
    else:
        await msg.answer(text, reply_markup=cancel_keyboard())


@router.message(F.text, InState("awaiting_live_link_leave"))
async def handle_leave_link(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    await set_user_state(user_id, "idle")

    # ── Leave ALL ────────────────────────────────────────────────────────────
    if text.upper() == "ALL":
        status_msg = await message.answer("🚪 Leaving all live streams...")
        result = await leave_all(user_id)
        await status_msg.edit_text(
            f"🚪 **Leave All Complete**\n"
            f"───── ⚡ ─────\n"
            f"✅ Left:    {result['left']}\n"
            f"❌ Failed:  {result['failed']}\n"
            f"🔄 Keep-alive stopped for all accounts.",
            reply_markup=back_home_keyboard()
        )
        return

    # ── Leave specific link ──────────────────────────────────────────────────
    link_info = parse_live_link(text)
    if not link_info:
        await message.answer("❌ Invalid link.", reply_markup=cancel_keyboard())
        await set_user_state(user_id, "awaiting_live_link_leave")
        return

    sessions = await get_all_sessions(user_id)
    if not sessions:
        await message.answer("⚠️ No active accounts.", reply_markup=back_home_keyboard())
        return

    status_msg = await message.answer("🚪 Leaving live stream...")

    left = 0
    failed = 0
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def worker(sess):
        nonlocal left, failed
        async with sem:
            res = await leave_live_stream(
                sess["session_string"],
                link_info,
                user_id=user_id,
                account_id=sess["id"],
            )
            if res["success"]:
                left += 1
            else:
                failed += 1

    await asyncio.gather(*[worker(s) for s in sessions])

    await status_msg.edit_text(
        f"🚪 **Leave Complete**\n"
        f"───── ⚡ ─────\n"
        f"✅ Left:    {left}\n"
        f"❌ Failed:  {failed}\n"
        f"📊 Total:   {len(sessions)}",
        reply_markup=back_home_keyboard()
    )
