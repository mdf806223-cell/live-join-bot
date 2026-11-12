import asyncio
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError, PhoneNumberBannedError, SessionPasswordNeededError,
    PhoneCodeInvalidError, PhoneCodeExpiredError, ApiIdInvalidError,
    PhoneNumberInvalidError,
)

from config import API_ID, API_HASH
from database.models import (
    upsert_user, set_user_state, get_user_state, add_account
)
from utils.validators import is_valid_phone
from utils.keyboards import cancel_keyboard, home_keyboard

router = Router()
log = logging.getLogger(__name__)

# In-memory temp state per user_id
_pending: dict[int, dict] = {}

# OTP timeout in seconds (5 minutes)
OTP_TIMEOUT = 300

async def _expire_pending(user_id: int, delay: int):
    """
    কিছুক্ষণ পর pending session টা expire করে দেয়।
    যদি ইতিমধ্যে sign-in হয়ে গিয়ে থাকে তাহলে কিছু করে না।
    """
    await asyncio.sleep(delay)
    pending = _pending.get(user_id)
    if pending:
        log.info(f"[add_account] OTP session expired for user {user_id}")
        try:
            await pending["client"].disconnect()
        except Exception:
            pass
        _pending.pop(user_id, None)
        # State যদি এখনো OTP/2FA তে আটকে থাকে তাহলে idle করে দাও
        from database.models import get_user_state as _get_state
        state = await _get_state(user_id)
        if state in ("awaiting_otp", "awaiting_2fa"):
            await set_user_state(user_id, "idle")


@router.callback_query(F.data == "add_account")
@router.message(Command("add"))
async def start_add_account(update):
    msg = update if isinstance(update, Message) else update.message
    user_id = update.from_user.id
    await upsert_user(user_id, update.from_user.username or "")
    await set_user_state(user_id, "awaiting_phone")
    text = (
        "➕ **Add New Account**\n"
        "───── ⚡ ─────\n\n"
        "📞 Please send your phone number:\n"
        "Format: `+8801XXXXXXXXX`"
    )
    if isinstance(update, CallbackQuery):
        await msg.edit_text(text, reply_markup=cancel_keyboard())
        await update.answer()
    else:
        await msg.answer(text, reply_markup=cancel_keyboard())


@router.message(F.text)
async def handle_text_states(message: Message):
    user_id = message.from_user.id
    state = await get_user_state(user_id)

    # ── State: awaiting phone ────────────────────────────────────────────────
    if state == "awaiting_phone":
        phone = message.text.strip()
        if not is_valid_phone(phone):
            await message.answer(
                "❌ Invalid phone number format.\nUse: `+8801XXXXXXXXX`",
                reply_markup=cancel_keyboard()
            )
            return

        wait_msg = await message.answer("⏳ Sending OTP code, please wait...")
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        try:
            await asyncio.wait_for(client.connect(), timeout=30)

            if not client.is_connected():
                await wait_msg.edit_text(
                    "❌ Could not connect to Telegram. Check API_ID/API_HASH.",
                    reply_markup=home_keyboard()
                )
                await set_user_state(user_id, "idle")
                return

            result = await asyncio.wait_for(
                client.send_code_request(phone), timeout=30
            )

            # আগে যদি কোনো pending থাকে, সেটা disconnect করে দাও
            old = _pending.pop(user_id, None)
            if old:
                try:
                    await old["client"].disconnect()
                except Exception:
                    pass

            _pending[user_id] = {
                "phone": phone,
                "client": client,
                "phone_code_hash": result.phone_code_hash,
                "expire_task": asyncio.create_task(_expire_pending(user_id, OTP_TIMEOUT)),
            }
            await set_user_state(user_id, "awaiting_otp")
            await wait_msg.edit_text(
                f"✅ OTP sent to `{phone}`\n\n"
                "📩 Please enter the OTP code you received\n"
                f"_(Expires in {OTP_TIMEOUT // 60} minutes)_\n"
                "_(Enter digits only, e.g: `12345`)_",
                reply_markup=cancel_keyboard()
            )

        except asyncio.TimeoutError:
            try:
                await client.disconnect()
            except Exception:
                pass
            await wait_msg.edit_text(
                "❌ Connection timed out. Check your server internet connection.",
                reply_markup=home_keyboard()
            )
            await set_user_state(user_id, "idle")

        except ApiIdInvalidError:
            try:
                await client.disconnect()
            except Exception:
                pass
            await wait_msg.edit_text(
                "❌ **API_ID or API_HASH is invalid!**\n"
                "Please check your `config.py` and restart the bot.",
                reply_markup=home_keyboard()
            )
            await set_user_state(user_id, "idle")

        except PhoneNumberInvalidError:
            try:
                await client.disconnect()
            except Exception:
                pass
            await wait_msg.edit_text(
                "❌ Invalid phone number. Use international format: `+8801XXXXXXXXX`",
                reply_markup=cancel_keyboard()
            )

        except FloodWaitError as e:
            try:
                await client.disconnect()
            except Exception:
                pass
            await wait_msg.edit_text(
                f"⚠️ Flood wait! Try again in **{e.seconds} seconds**.",
                reply_markup=home_keyboard()
            )
            await set_user_state(user_id, "idle")

        except PhoneNumberBannedError:
            try:
                await client.disconnect()
            except Exception:
                pass
            await wait_msg.edit_text(
                "❌ This phone number is **banned** by Telegram.",
                reply_markup=home_keyboard()
            )
            await set_user_state(user_id, "idle")

        except Exception as e:
            log.exception(f"[add_account] send_code_request error for {user_id}: {e}")
            try:
                await client.disconnect()
            except Exception:
                pass
            await wait_msg.edit_text(
                f"❌ Error: `{e}`",
                reply_markup=home_keyboard()
            )
            await set_user_state(user_id, "idle")

    # ── State: awaiting OTP ──────────────────────────────────────────────────
    elif state == "awaiting_otp":
        code = message.text.strip().replace(" ", "")
        pending = _pending.get(user_id)
        if not pending:
            await set_user_state(user_id, "idle")
            await message.answer("⚠️ Session expired. Please start over.", reply_markup=home_keyboard())
            return

        client: TelegramClient = pending["client"]

        if not client.is_connected():
            try:
                await asyncio.wait_for(client.connect(), timeout=30)
            except Exception as e:
                pending.get("expire_task", asyncio.current_task()).cancel()
                _pending.pop(user_id, None)
                await set_user_state(user_id, "idle")
                await message.answer(
                    f"❌ Reconnect failed: `{e}`\nPlease start over.",
                    reply_markup=home_keyboard()
                )
                return

        try:
            await client.sign_in(
                phone=pending["phone"],
                code=code,
                phone_code_hash=pending["phone_code_hash"]
            )
            me = await client.get_me()
            session_str = client.session.save()
            await add_account(user_id, pending["phone"], me.first_name, session_str)
            # Expire task cancel করো — সফলভাবে add হয়ে গেছে
            pending.get("expire_task", asyncio.current_task()).cancel()
            _pending.pop(user_id, None)
            await client.disconnect()
            await set_user_state(user_id, "idle")
            await message.answer(
                f"✅ **Account Added Successfully!**\n"
                f"───── ⚡ ─────\n"
                f"👤 Name: **{me.first_name}**\n"
                f"📞 Phone: `{pending['phone']}`",
                reply_markup=home_keyboard()
            )

        except SessionPasswordNeededError:
            await set_user_state(user_id, "awaiting_2fa")
            await message.answer(
                "🔐 **Two-Step Verification is enabled.**\n\n"
                "🔑 Please enter your **2FA password**:",
                reply_markup=cancel_keyboard()
            )

        except (PhoneCodeInvalidError, PhoneCodeExpiredError):
            await message.answer(
                "❌ Invalid or expired OTP. Please try again:",
                reply_markup=cancel_keyboard()
            )

        except Exception as e:
            log.exception(f"[add_account] sign_in error for {user_id}: {e}")
            try:
                await client.disconnect()
            except Exception:
                pass
            pending.get("expire_task", asyncio.current_task()).cancel()
            _pending.pop(user_id, None)
            await set_user_state(user_id, "idle")
            await message.answer(f"❌ Error: `{e}`", reply_markup=home_keyboard())

    # ── State: awaiting 2FA ──────────────────────────────────────────────────
    elif state == "awaiting_2fa":
        password = message.text.strip()
        pending = _pending.get(user_id)
        if not pending:
            await set_user_state(user_id, "idle")
            await message.answer("⚠️ Session expired. Please start over.", reply_markup=home_keyboard())
            return

        client: TelegramClient = pending["client"]

        if not client.is_connected():
            try:
                await asyncio.wait_for(client.connect(), timeout=30)
            except Exception as e:
                pending.get("expire_task", asyncio.current_task()).cancel()
                _pending.pop(user_id, None)
                await set_user_state(user_id, "idle")
                await message.answer(
                    f"❌ Reconnect failed: `{e}`\nPlease start over.",
                    reply_markup=home_keyboard()
                )
                return

        try:
            await client.sign_in(password=password)
            me = await client.get_me()
            session_str = client.session.save()
            await add_account(user_id, pending["phone"], me.first_name, session_str)
            # Expire task cancel করো — সফলভাবে add হয়ে গেছে
            pending.get("expire_task", asyncio.current_task()).cancel()
            _pending.pop(user_id, None)
            await client.disconnect()
            await set_user_state(user_id, "idle")
            await message.answer(
                f"✅ **Account Added Successfully!**\n"
                f"───── ⚡ ─────\n"
                f"👤 Name: **{me.first_name}**\n"
                f"📞 Phone: `{pending['phone']}`",
                reply_markup=home_keyboard()
            )
        except Exception as e:
            log.exception(f"[add_account] 2fa error for {user_id}: {e}")
            try:
                await client.disconnect()
            except Exception:
                pass
            pending.get("expire_task", asyncio.current_task()).cancel()
            _pending.pop(user_id, None)
            await set_user_state(user_id, "idle")
            await message.answer(f"❌ Wrong password or error: `{e}`", reply_markup=home_keyboard())

    # ── State: awaiting rename ───────────────────────────────────────────────
    elif state.startswith("rename_"):
        account_id = int(state.split("_")[1])
        from database.models import rename_account
        new_name = message.text.strip()
        await rename_account(user_id, account_id, new_name)
        await set_user_state(user_id, "idle")
        await message.answer(
            f"✅ Account renamed to **{new_name}**.",
            reply_markup=home_keyboard()
        )
