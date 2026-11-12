import asyncio
import random
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from database.models import get_all_sessions, set_user_state
from utils.validators import parse_live_link
from utils.keyboards import cancel_keyboard, back_home_keyboard
from utils.telegram_client import raise_hand
from utils.state_filter import InState
from config import HAND_RAISE_DELAY_MIN, HAND_RAISE_DELAY_MAX

router = Router()

_active_live: dict[int, dict] = {}


def _progress_bar(done: int, total: int, width: int = 18) -> str:
    filled = int(width * done / total) if total else 0
    bar = "█" * filled + "░" * (width - filled)
    pct = int(100 * done / total) if total else 0
    return f"[{bar}] {pct}%"


@router.callback_query(F.data == "hand_raise")
@router.message(Command("raise"))
async def start_hand_raise(update):
    msg = update if isinstance(update, Message) else update.message
    user_id = update.from_user.id
    await set_user_state(user_id, "awaiting_live_link_raise")
    text = (
        "✋ **Hand Raise**\n"
        "───── ⚡ ─────\n\n"
        "⚠️ Raises hands SLOWLY, one by one.\n\n"
        "🔗 Send the live stream link:"
    )
    if isinstance(update, CallbackQuery):
        await msg.edit_text(text, reply_markup=cancel_keyboard())
        await update.answer()
    else:
        await msg.answer(text, reply_markup=cancel_keyboard())


@router.message(F.text, InState("awaiting_live_link_raise"))
async def handle_raise_link(message: Message):
    user_id = message.from_user.id
    link = message.text.strip()
    link_info = parse_live_link(link)
    if not link_info:
        await message.answer("❌ Invalid link.", reply_markup=cancel_keyboard())
        return

    sessions = await get_all_sessions(user_id)
    if not sessions:
        await set_user_state(user_id, "idle")
        await message.answer("⚠️ No active accounts found.", reply_markup=back_home_keyboard())
        return

    _active_live[user_id] = link_info
    await set_user_state(user_id, "idle")

    total = len(sessions)
    status_msg = await message.answer(
        f"✋ **Hand Raise Progress**\n"
        f"───── ⚡ ─────\n"
        f"{_progress_bar(0, total)}\n"
        f"✅ Raised: 0 / {total}\n"
        f"⏳ Starting..."
    )

    raised = 0
    failed = 0

    for i, sess in enumerate(sessions):
        res = await raise_hand(
            sess["session_string"],
            link_info,
            user_id=user_id,
            account_id=sess["id"],
        )
        if res["success"]:
            raised += 1
        else:
            failed += 1

        done = i + 1
        try:
            await status_msg.edit_text(
                f"✋ **Hand Raise Progress**\n"
                f"───── ⚡ ─────\n"
                f"{_progress_bar(done, total)}\n"
                f"✅ Raised: {raised} / {total}\n"
                f"❌ Failed: {failed}\n"
                f"⏳ In progress..."
            )
        except Exception:
            pass

        if i < total - 1:
            delay = random.uniform(HAND_RAISE_DELAY_MIN, HAND_RAISE_DELAY_MAX)
            await asyncio.sleep(delay)

    await status_msg.edit_text(
        f"✋ **Hand Raise Complete!**\n"
        f"───── ⚡ ─────\n"
        f"{_progress_bar(total, total)}\n"
        f"✅ Raised: {raised} / {total}\n"
        f"❌ Failed: {failed}",
        reply_markup=back_home_keyboard()
    )
