import asyncio
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.filters import Command

from database.models import get_all_sessions, set_user_state
from utils.validators import parse_live_link
from utils.keyboards import cancel_keyboard, back_home_keyboard
from utils.telegram_client import join_live_stream, leave_all, get_active_count
from utils.state_filter import InState
from config import MAX_CONCURRENT

router = Router()


# ─── Status text (live progress) ─────────────────────────────────────────────

def _join_status_text(total: int, pending: int, joined: int) -> str:
    return (
        f"🤖 𝗧𝗼𝘁𝗮𝗹 𝗕𝗼𝘁 𝗔𝗰𝗰𝗼𝘂𝗻𝘁 : {total}\n\n"
        f"🛜 𝗣𝗮𝗻𝗱𝗶𝗻𝗴 𝗝𝗼𝗶𝗻 : {max(0, pending)}\n\n"
        f"⏺ 𝗔𝗹𝗿𝗲𝗮𝗱𝘆 𝗝𝗼𝗶𝗻 : {joined}"
    )


# ─── Start: ask for link ──────────────────────────────────────────────────────

@router.callback_query(F.data == "join_live")
@router.message(Command("join"))
async def start_join_live(update):
    msg = update if isinstance(update, Message) else update.message
    user_id = update.from_user.id
    await set_user_state(user_id, "awaiting_live_link_join")
    text = (
        "📡 **Join Live Stream**\n"
        "───── ⚡ ─────\n\n"
        "🔗 Channel/Group link বা @username দিন:\n\n"
        "• `https://t.me/username`\n"
        "• `@username`\n"
        "• `https://t.me/+XXXX` _(private)_"
    )
    if isinstance(update, CallbackQuery):
        await msg.edit_text(text, reply_markup=cancel_keyboard())
        await update.answer()
    else:
        await msg.answer(text, reply_markup=cancel_keyboard())


# ─── Handle link ─────────────────────────────────────────────────────────────

@router.message(F.text, InState("awaiting_live_link_join"))
async def handle_join_link(message: Message):
    user_id = message.from_user.id
    link = message.text.strip()

    link_info = parse_live_link(link)
    if not link_info:
        await message.answer(
            "❌ Invalid link. Example: `@username` বা `https://t.me/username`",
            reply_markup=cancel_keyboard()
        )
        return

    sessions = await get_all_sessions(user_id)
    if not sessions:
        await set_user_state(user_id, "idle")
        await message.answer("⚠️ No active accounts found.", reply_markup=back_home_keyboard())
        return

    await set_user_state(user_id, "idle")

    total   = len(sessions)
    pending = total
    joined  = 0

    # Show initial status
    status_msg = await message.answer(_join_status_text(total, pending, joined))

    results = {"vc": 0, "ch_only": 0, "failed": 0, "banned": 0}
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def _worker(sess):
        nonlocal pending, joined
        async with sem:
            res = await join_live_stream(
                sess["session_string"], link_info,
                user_id=user_id, account_id=sess["id"],
            )
            if res["success"]:
                results["vc"] += 1
                joined += 1
            elif res.get("error") == "no_active_live":
                # Channel joined but no live active yet
                results["ch_only"] += 1
                joined += 1
            elif res.get("banned"):
                results["banned"] += 1
            else:
                results["failed"] += 1
            pending -= 1
            try:
                await status_msg.edit_text(_join_status_text(total, pending, joined))
            except Exception:
                pass

    await asyncio.gather(*[asyncio.create_task(_worker(s)) for s in sessions])

    active_now = get_active_count(user_id)

    # Build result text
    lines = [
        "📡 **Live Join Status**",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    if results["vc"] > 0:
        lines.append(f"✅ Joined VC     : **{results['vc']}** / {total}")
    if results["ch_only"] > 0:
        lines.append(f"📡 Channel only  : **{results['ch_only']}** _(no live active)_")
    if results["failed"] > 0:
        lines.append(f"❌ Failed        : **{results['failed']}**")
    if results["banned"] > 0:
        lines.append(f"⛔ Banned        : **{results['banned']}**")
    if active_now > 0:
        lines.append(f"\n🔄 Keep-alive active: **{active_now}** accounts")

    kb = (
        InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💣 LEAVE VC", callback_data="leave_vc")
        ]])
        if results["vc"] > 0
        else back_home_keyboard()
    )

    await status_msg.edit_text("\n".join(lines), reply_markup=kb)


# ─── Leave VC (inline button) ─────────────────────────────────────────────────

@router.callback_query(F.data == "leave_vc")
async def cb_leave_vc(callback: CallbackQuery):
    user_id = callback.from_user.id
    await callback.message.edit_text("⏳ Leaving VC...")
    result = await leave_all(user_id)
    await callback.message.edit_text(
        f"✅ **Left VC**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✔️ Left    : **{result['left']}**\n"
        f"❌ Failed  : **{result['failed']}**",
        reply_markup=back_home_keyboard()
    )
    await callback.answer()
