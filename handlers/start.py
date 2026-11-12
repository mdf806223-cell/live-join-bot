from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command

from database.models import upsert_user, count_accounts, set_user_state
from utils.keyboards import home_keyboard

router = Router()


def home_text(username: str, counts: dict) -> str:
    # FIX: truncate username to 18 chars max to prevent box layout breaking
    display_name = (username or "")[:18]
    return (
        "╔══════════════════════════════╗\n"
        "║   📡  LIVE JOIN BOT v1.0     ║\n"
        "║  ─────────────────────────── ║\n"
        f"║  👤 User: @{display_name:<18}║\n"
        f"║  📊 Total Accounts: {counts['total']:<9}║\n"
        f"║  ✅ Active: {counts['active']:<18}║\n"
        "║  ─────────────────────────── ║\n"
        "╚══════════════════════════════╝\n\n"
        "Select an option below:\n\n"
        "╔► 𝙳𝙴𝚅𝙴𝙻𝙾𝙿𝙴𝙳 𝙱𝚈 ◄╗\n"
        "   @DARKXHACKERR"
    )


@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    await upsert_user(user.id, user.username or "")
    await set_user_state(user.id, "idle")
    counts = await count_accounts(user.id)
    await message.answer(
        home_text(user.username or str(user.id), counts),
        reply_markup=home_keyboard()
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message):
    await set_user_state(message.from_user.id, "idle")
    await message.answer("❌ Operation cancelled.", reply_markup=home_keyboard())


@router.callback_query(F.data == "home")
async def cb_home(callback: CallbackQuery):
    user = callback.from_user
    await set_user_state(user.id, "idle")
    counts = await count_accounts(user.id)
    await callback.message.edit_text(
        home_text(user.username or str(user.id), counts),
        reply_markup=home_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery):
    user = callback.from_user
    await set_user_state(user.id, "idle")
    counts = await count_accounts(user.id)
    await callback.message.edit_text(
        home_text(user.username or str(user.id), counts),
        reply_markup=home_keyboard()
    )
    await callback.answer("Cancelled.")
