from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from database.models import (
    get_accounts, get_account, delete_account, set_account_status,
    set_user_state, get_session_string
)
from utils.keyboards import account_card_keyboard, back_home_keyboard, confirm_keyboard, cancel_keyboard
from utils.telegram_client import make_client

router = Router()

STATUS_EMOJI = {"active": "✅", "banned": "⛔", "logged_out": "🔴"}


def account_card_text(acc: dict) -> str:
    emoji = STATUS_EMOJI.get(acc["status"], "❓")
    return (
        f"┌──────────────────────────┐\n"
        f"│ 👤 {acc['name'] or 'Unknown':<23}│\n"
        f"│ 📞 {acc['phone']:<23}│\n"
        f"│ {emoji} Status: {acc['status'].capitalize():<17}│\n"
        f"└──────────────────────────┘"
    )


@router.callback_query(F.data == "account_list")
@router.message(Command("list"))
async def show_account_list(update):
    msg = update if isinstance(update, Message) else update.message
    user_id = update.from_user.id
    accounts = await get_accounts(user_id)

    if not accounts:
        text = "📋 **Account List**\n───── ⚡ ─────\n\n⚠️ No accounts added yet."
        kb = back_home_keyboard()
        if isinstance(update, CallbackQuery):
            await msg.edit_text(text, reply_markup=kb)
            await update.answer()
        else:
            await msg.answer(text, reply_markup=kb)
        return

    if isinstance(update, CallbackQuery):
        await update.answer()

    await msg.answer(
        f"📋 **Account List** — {len(accounts)} account(s)\n───── ⚡ ─────"
    )
    for acc in accounts:
        await msg.answer(
            account_card_text(acc),
            reply_markup=account_card_keyboard(acc["id"])
        )


@router.callback_query(F.data.startswith("rename_"))
async def cb_rename(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    acc = await get_account(user_id, account_id)
    if not acc:
        await callback.answer("Account not found.", show_alert=True)
        return
    await set_user_state(user_id, f"rename_{account_id}")
    await callback.message.answer(
        f"✏️ **Rename Account**\n"
        f"Current name: **{acc['name']}**\n\n"
        f"Send the new name:",
        reply_markup=cancel_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("logout_"))
async def cb_logout(callback: CallbackQuery):
    # logout_{account_id} — split limit=1 দিয়ে নিরাপদে নাও
    account_id = int(callback.data.split("_", 1)[1])
    user_id = callback.from_user.id
    acc = await get_account(user_id, account_id)
    if not acc:
        await callback.answer("Account not found.", show_alert=True)
        return
    await callback.message.edit_text(
        f"🗑️ **Logout Confirmation**\n\n"
        f"Remove **{acc['name']}** (`{acc['phone']}`) ?\n"
        f"This cannot be undone.",
        reply_markup=confirm_keyboard("logout", account_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_logout_"))
async def cb_confirm_logout(callback: CallbackQuery):
    # confirm_logout_{account_id}
    account_id = int(callback.data.split("_", 2)[2])
    user_id = callback.from_user.id

    session_str = await get_session_string(user_id, account_id)

    # Revoke session on Telegram then disconnect
    if session_str:
        client = make_client(session_str)
        try:
            await client.connect()
            await client.log_out()
        except Exception:
            pass
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    await delete_account(user_id, account_id)
    await callback.message.edit_text(
        "✅ Account logged out and removed.",
        reply_markup=back_home_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("account_detail_"))
async def cb_account_detail(callback: CallbackQuery):
    account_id = int(callback.data.split("_", 2)[2])
    user_id = callback.from_user.id
    acc = await get_account(user_id, account_id)
    if not acc:
        await callback.answer("Not found.", show_alert=True)
        return
    await callback.message.edit_text(
        account_card_text(acc),
        reply_markup=account_card_keyboard(account_id)
    )
    await callback.answer()
