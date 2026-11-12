import os
import time
import asyncio
import random
import secrets
import string
import logging
import wave
from datetime import datetime

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.phone import (
    LeaveGroupCallRequest,
    EditGroupCallParticipantRequest,
)
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import (
    InputGroupCall, GroupCallDiscarded,
    InputPeerUser, InputPeerSelf,
    UpdateGroupCallParticipants,
)
from telethon.errors import FloodWaitError, UserAlreadyParticipantError

from pytgcalls import PyTgCalls
from pytgcalls.types import GroupCallConfig
from pytgcalls.exceptions import NoActiveGroupCall, NotInCallError

from config import API_ID, API_HASH

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# State
# { user_id: { account_id: {
#     "client", "engine", "task", "watch_task",
#     "call", "call_id", "chat_id", "entity", "me"
# } } }
# ─────────────────────────────────────────────────────────────────────────────
_active_clients: dict[int, dict[int, dict]] = {}

_bot = None

SILENCE_FILE = "silence.wav"

# ─── Remute tracker ───────────────────────────────────────────────────────────
# bot.py এর _last_mute_at এর মতো — spam prevent করে
_last_mute_at: dict = {}


def _make_remute_handler(
    client: TelegramClient,
    engine,           # PyTgCalls engine
    call: InputGroupCall,
    chat_id: int,
    me_id: int,
    account_id: int,
):
    """
    bot.py এর _make_remute_handler() এর মতো — কিন্তু আরো শক্তিশালী।

    কেউ account টাকে unmute করলে:
    1. engine.mute() → PyTgCalls level এ মুট (UDP stream চালু থাকে)
    2. EditGroupCallParticipantRequest → API level এ মুট

    UDP connection বন্ধ হয় না — শুধু muted=True থাকে।
    """
    async def handler(ev):
        if not isinstance(ev, UpdateGroupCallParticipants):
            return
        for p in ev.participants:
            # আমাদের account কিনা চেক করো
            uid_p = getattr(p.peer, "user_id", None)
            if uid_p != me_id:
                continue
            # Left হয়ে গেলে skip
            if getattr(p, "left", False):
                continue
            # Unmute হয়েছে?
            if not p.muted:
                now = time.monotonic()
                # Spam prevent: 60s এর মধ্যে একবারের বেশি না
                if now - _last_mute_at.get(me_id, 0) < 60:
                    continue
                _last_mute_at[me_id] = now
                log.info(
                    f"[remute] {account_id} unmute হয়েছে → "
                    f"PyTgCalls + API দিয়ে remute করছি"
                )
                # ① PyTgCalls level mute (UDP stream চলতে থাকে)
                try:
                    await engine.mute(chat_id)
                except Exception as e:
                    log.debug(f"[remute] engine.mute: {e}")
                # ② API level mute
                try:
                    await client(EditGroupCallParticipantRequest(
                        call=call,
                        participant=InputPeerSelf(),
                        muted=True,
                    ))
                    log.info(f"[remute] ✅ {account_id} remute সফল")
                except Exception as e:
                    log.debug(f"[remute] api mute: {e}")

    return handler


def set_bot(bot):
    global _bot
    _bot = bot


# ─── Notification ─────────────────────────────────────────────────────────────

def _live_ended_message(active_count: int) -> str:
    now = datetime.now().strftime("%d %b • %I:%M %p")
    return (
        "🔴 **Live Stream Ended**\n"
        "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n\n"
        "Host ended the stream.\n\n"
        f"👥 Active accounts: **{active_count}**\n"
        "⏹️ All disconnected automatically\n"
        f"🕐 {now}\n\n"
        "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
        "Tap [📡 Join Live] for a new stream."
    )


# ─── Silence WAV ──────────────────────────────────────────────────────────────

def _ensure_silence() -> str:
    """
    bot.py এর মতো একটা 60-second silent WAV file তৈরি করো।
    PyTgCalls এই file stream করবে — Telegram server real audio
    packet দেখবে এবং মনে করবে real মানুষ আছে।
    """
    if not os.path.exists(SILENCE_FILE):
        try:
            with wave.open(SILENCE_FILE, "wb") as w:
                w.setnchannels(1)       # mono
                w.setsampwidth(2)       # 16-bit
                w.setframerate(48000)   # 48 kHz (Telegram standard)
                # 60 seconds × 48000 samples × 2 bytes = silent frames
                w.writeframes(b"\x00\x00" * 48000 * 60)
            log.info(f"[silence] ✅ {SILENCE_FILE} তৈরি হয়েছে")
        except Exception as e:
            log.warning(f"[silence] WAV তৈরিতে সমস্যা: {e}")
    return SILENCE_FILE


def _silence_stream():
    """
    bot.py এর _silence_stream() এর মতো।
    PyTgCalls এর Stream object — real WebRTC UDP connection এর
    জন্য silent audio source দেয়।
    """
    from pytgcalls.types.raw import Stream, AudioStream, AudioParameters
    from ntgcalls import MediaSource
    return Stream(
        microphone=AudioStream(
            MediaSource.FILE,
            _ensure_silence(),
            AudioParameters(bitrate=48000, channels=1),
        )
    )


# ─── PyTgCalls Engine ─────────────────────────────────────────────────────────

def _register_stream_loop(engine: PyTgCalls, account_id: int):
    """
    bot.py এর _register_stream_loop() এর মতো।
    60-second WAV শেষ হলে auto-restart করে — connection অটো ধরে রাখে।
    """
    from pytgcalls import filters as tg_filters

    @engine.on_update(tg_filters.stream_end())
    async def _on_stream_end(client_eng, update):
        try:
            await asyncio.sleep(2)
            await client_eng.play(
                update.chat_id,
                _silence_stream(),
                config=GroupCallConfig(auto_start=False),
            )
            log.info(f"[stream] ✅ {account_id} silent stream restart হলো")
        except Exception as e:
            log.warning(f"[stream] {account_id} restart ব্যর্থ: {e}")


async def _get_engine(client: TelegramClient, account_id: int) -> PyTgCalls:
    """
    bot.py এর _get_engine() এর মতো।
    প্রতিটা account এর জন্য একটাই PyTgCalls engine।
    """
    # active_clients এ ইতিমধ্যে engine থাকলে সেটা ব্যবহার করো
    for uid_data in _active_clients.values():
        acc = uid_data.get(account_id)
        if acc and acc.get("engine"):
            eng = acc["engine"]
            if not getattr(eng, "_is_running", False):
                try:
                    await eng.start()
                except Exception:
                    pass
            return eng

    # নতুন engine তৈরি করো
    eng = PyTgCalls(client, workers=2)
    _register_stream_loop(eng, account_id)
    await eng.start()
    return eng


# ─── Client factory ───────────────────────────────────────────────────────────

_DEVICE_MODELS = [
    "Samsung Galaxy S23",
    "Samsung Galaxy S22 Ultra",
    "Xiaomi 13 Pro",
    "OnePlus 11",
    "Google Pixel 7",
    "Realme GT 3",
    "Vivo X90 Pro",
]
_SYSTEM_VERSIONS = ["SDK 33", "SDK 34", "SDK 32"]
_APP_VERSION = "10.0.1"


def make_client(session_string: str = None) -> TelegramClient:
    session = StringSession(session_string) if session_string else StringSession()
    device = secrets.choice(_DEVICE_MODELS)
    system = secrets.choice(_SYSTEM_VERSIONS)
    return TelegramClient(
        session, API_ID, API_HASH,
        device_model=device,
        system_version=system,
        app_version=_APP_VERSION,
        lang_code="en",
        system_lang_code="en-US",
        connection_retries=10,
        retry_delay=3,
        auto_reconnect=True,
        receive_updates=True,
    )


# ─── Entity resolver ──────────────────────────────────────────────────────────

async def _get_entity_and_call(client: TelegramClient, link_info: dict):
    if link_info["type"] == "invite":
        from telethon.tl.functions.messages import (
            ImportChatInviteRequest, CheckChatInviteRequest,
        )
        from telethon.tl.types import ChatInviteAlready
        entity = None
        try:
            invite_info = await client(CheckChatInviteRequest(link_info["hash"]))
            if isinstance(invite_info, ChatInviteAlready):
                entity = invite_info.chat
            else:
                result = await client(ImportChatInviteRequest(link_info["hash"]))
                if result.chats:
                    entity = result.chats[0]
        except UserAlreadyParticipantError:
            dialogs = await client.get_dialogs(limit=50)
            entity = dialogs[0].entity if dialogs else None
        except Exception:
            entity = None
    else:
        try:
            entity = await client.get_entity(link_info["username"])
        except Exception:
            return None, None
        try:
            await client(JoinChannelRequest(entity))
        except UserAlreadyParticipantError:
            pass

    if entity is None:
        return None, None

    try:
        from telethon.tl.functions.channels import GetFullChannelRequest
        full = await client(GetFullChannelRequest(entity))
        call = getattr(full.full_chat, "call", None)
    except Exception:
        call = None

    return entity, call


# ─── Live-ended watcher ───────────────────────────────────────────────────────

async def _watch_live_ended(client: TelegramClient, call_id: int, user_id: int):
    async def handler(update):
        try:
            call = getattr(update, "call", None)
            if isinstance(call, GroupCallDiscarded) and call.id == call_id:
                log.info(f"[watch] Call {call_id} ended → user {user_id}")
                await _on_live_ended(user_id)
        except Exception as e:
            log.warning(f"[watch] handler error: {e}")

    client.add_event_handler(handler, events.Raw)
    try:
        while True:
            await asyncio.sleep(60)
            if user_id not in _active_clients:
                break
    except asyncio.CancelledError:
        pass
    finally:
        try:
            client.remove_event_handler(handler)
        except Exception:
            pass


async def _on_live_ended(user_id: int):
    accounts = dict(_active_clients.pop(user_id, {}))
    active_count = len(accounts)
    for acc_id, active in accounts.items():
        try:
            active["task"].cancel()
            active["watch_task"].cancel()
            await asyncio.gather(
                asyncio.shield(active["task"]),
                asyncio.shield(active["watch_task"]),
                return_exceptions=True,
            )
            # Remute handler সরাও
            remute_handler = active.get("remute_handler")
            if remute_handler:
                try:
                    active["client"].remove_event_handler(remute_handler)
                except Exception:
                    pass
            me = active.get("me")
            if me:
                _last_mute_at.pop(me.id, None)
            # engine দিয়ে properly leave করো
            engine = active.get("engine")
            chat_id = active.get("chat_id")
            if engine and chat_id:
                try:
                    await engine.leave_call(chat_id)
                except Exception:
                    pass
            await active["client"].disconnect()
        except Exception:
            pass

    if _bot and active_count > 0:
        from utils.keyboards import home_keyboard
        try:
            await _bot.send_message(
                user_id,
                _live_ended_message(active_count),
                reply_markup=home_keyboard(),
            )
        except Exception as e:
            log.warning(f"[on_live_ended] notify failed: {e}")


# ─── Watchdog / Keep-alive (bot.py এর watchdog style) ────────────────────────

async def _keepalive_loop(
    engine: PyTgCalls,
    chat_id: int,
    call: InputGroupCall,
    client: TelegramClient,
    account_id: int,
    user_id: int,
):
    """
    bot.py এর _watchdog_loop() এর মতো।

    পার্থক্য:
    - আগের ZIP বটে শুধু EditGroupCallParticipantRequest পাঠাতো
      (fake — real UDP connection ছিল না)
    - এখন engine.calls চেক করে দেখে account call এ আছে কিনা
    - না থাকলে engine.play() দিয়ে real WebRTC সহ rejoin করে
    - PyTgCalls নিজেই real UDP audio packet পাঠায় → Telegram
      কখনো kick করে না
    """
    log.info(f"[watchdog] Started — account {account_id}")
    fail_count = 0
    MAX_FAILS  = 10
    me = None

    try:
        me = await client.get_me()
    except Exception as e:
        log.warning(f"[watchdog] initial get_me failed: {e}")

    while True:
        try:
            await asyncio.sleep(random.uniform(20, 40))

            # ── Call এ আছে কিনা চেক করো ──────────────────────────────
            try:
                active_calls = await engine.calls
                in_call = chat_id in active_calls
            except Exception:
                in_call = True  # চেক করতে না পারলে assume in-call

            if in_call:
                # ✅ আছে — শুধু presence ping পাঠাও
                if me:
                    try:
                        participant_peer = InputPeerUser(
                            user_id=me.id,
                            access_hash=me.access_hash,
                        )
                        await asyncio.wait_for(
                            client(EditGroupCallParticipantRequest(
                                call=call,
                                participant=participant_peer,
                                muted=True,
                                video_stopped=True,
                                raise_hand=False,
                                volume=1,
                            )),
                            timeout=20,
                        )
                        fail_count = 0
                        log.debug(f"[watchdog] ✓ presence ping — {account_id}")
                    except Exception as e:
                        log.debug(f"[watchdog] presence ping skip: {e}")
                continue

            # ── Call এ নেই → Rejoin ──────────────────────────────────
            log.info(
                f"[watchdog] {account_id} call এ নেই → "
                f"PyTgCalls দিয়ে rejoin করছি..."
            )
            try:
                # আগে properly leave করার চেষ্টা করো
                try:
                    await engine.leave_call(chat_id)
                except Exception:
                    pass

                await asyncio.sleep(1)

                # me refresh করো
                if me is None:
                    me = await asyncio.wait_for(client.get_me(), timeout=15)

                join_as = InputPeerUser(
                    user_id=me.id,
                    access_hash=me.access_hash,
                )
                # ✅ Real WebRTC UDP সহ rejoin — silent stream দিয়ে
                await engine.play(
                    chat_id,
                    _silence_stream(),
                    config=GroupCallConfig(join_as=join_as, auto_start=False),
                )
                # Mute করো
                try:
                    await engine.mute(chat_id)
                except Exception:
                    pass
                try:
                    await client(EditGroupCallParticipantRequest(
                        call=call,
                        participant=InputPeerSelf(),
                        muted=True,
                    ))
                except Exception:
                    pass

                fail_count = 0
                log.info(f"[watchdog] ✅ {account_id} rejoin সফল!")

            except NoActiveGroupCall:
                log.info(f"[watchdog] {account_id} live শেষ হয়ে গেছে")
                break
            except Exception as e:
                log.warning(f"[watchdog] {account_id} rejoin ব্যর্থ: {e}")
                fail_count += 1
                if fail_count >= MAX_FAILS:
                    break
                await asyncio.sleep(random.uniform(10, 20))

        except asyncio.CancelledError:
            log.info(f"[watchdog] Cancelled — {account_id}")
            break
        except Exception as e:
            log.warning(f"[watchdog] unexpected error {account_id}: {e}")
            fail_count += 1
            if fail_count >= MAX_FAILS:
                break
            await asyncio.sleep(10)

    log.info(f"[watchdog] Exited — {account_id}")


# ─── Join ─────────────────────────────────────────────────────────────────────

async def join_live_stream(
    session_string: str,
    link_info: dict,
    user_id: int,
    account_id: int,
) -> dict:
    result = {"success": False, "error": None, "banned": False}
    client = make_client(session_string)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            result.update(error="not_authorized", banned=True)
            await client.disconnect()
            return result

        entity, call = await _get_entity_and_call(client, link_info)

        if entity is None:
            result["error"] = "entity_not_found"
            await client.disconnect()
            return result

        if call is None:
            result["error"] = "no_active_live"
            await client.disconnect()
            return result

        from telethon.utils import get_peer_id
        chat_id = get_peer_id(entity)
        input_call = InputGroupCall(id=call.id, access_hash=call.access_hash)

        me = await client.get_me()
        join_as = InputPeerUser(user_id=me.id, access_hash=me.access_hash)

        # ✅ PyTgCalls engine তৈরি করো (real WebRTC UDP connection)
        engine = await _get_engine(client, account_id)

        # ✅ Silent stream দিয়ে join করো
        # এটাই bot.py এর মূল trick: real audio packet পাঠায়
        # Telegram server মনে করে real মানুষ — কখনো kick করে না
        try:
            await engine.play(
                chat_id,
                _silence_stream(),
                config=GroupCallConfig(join_as=join_as, auto_start=False),
            )
        except Exception as e:
            log.warning(f"[join] {account_id} silent stream ব্যর্থ ({e}), retry...")
            await engine.play(
                chat_id,
                None,
                config=GroupCallConfig(join_as=join_as, auto_start=False),
            )

        # Mute করো (join এর পরপরই)
        try:
            await engine.mute(chat_id)
        except Exception:
            pass
        try:
            await client(EditGroupCallParticipantRequest(
                call=input_call,
                participant=InputPeerSelf(),
                muted=True,
            ))
        except Exception:
            pass

        # ✅ Remute handler register করো
        # কেউ unmute করলে auto remute হবে, UDP চালু থাকবে
        remute_handler = _make_remute_handler(
            client, engine, input_call, chat_id, me.id, account_id
        )
        client.add_event_handler(remute_handler, events.Raw(UpdateGroupCallParticipants))

        is_first = user_id not in _active_clients or len(_active_clients[user_id]) == 0

        keepalive_task = asyncio.create_task(
            _keepalive_loop(engine, chat_id, input_call, client, account_id, user_id)
        )
        watch_task = asyncio.create_task(
            _watch_live_ended(client, call.id, user_id)
        ) if is_first else asyncio.create_task(asyncio.sleep(float("inf")))

        _active_clients.setdefault(user_id, {})[account_id] = {
            "client":         client,
            "engine":         engine,
            "task":           keepalive_task,
            "watch_task":     watch_task,
            "call":           input_call,
            "call_id":        call.id,
            "chat_id":        chat_id,
            "entity":         entity,
            "me":             me,
            "remute_handler": remute_handler,
        }

        result["success"] = True
        log.info(f"[join] ✅ {account_id} live join সফল (real UDP stream active)")

    except NoActiveGroupCall:
        result["error"] = "no_active_live"
        await client.disconnect()
    except FloodWaitError as e:
        result["error"] = f"flood_wait_{e.seconds}"
        await client.disconnect()
    except Exception as e:
        err = str(e).lower()
        if any(k in err for k in ("banned", "deactivated", "restricted")):
            result["banned"] = True
        result["error"] = str(e)
        try:
            await client.disconnect()
        except Exception:
            pass

    return result


# ─── Leave ────────────────────────────────────────────────────────────────────

async def _cleanup_active(user_id: int, account_id: int, active: dict):
    active["task"].cancel()
    active["watch_task"].cancel()
    await asyncio.gather(
        asyncio.shield(active["task"]),
        asyncio.shield(active["watch_task"]),
        return_exceptions=True,
    )
    _active_clients.get(user_id, {}).pop(account_id, None)

    # Remute handler সরিয়ে দাও
    remute_handler = active.get("remute_handler")
    if remute_handler:
        try:
            active["client"].remove_event_handler(remute_handler)
        except Exception:
            pass
    # _last_mute_at থেকেও সরাও
    me = active.get("me")
    if me:
        _last_mute_at.pop(me.id, None)

    # Engine দিয়ে properly leave করো
    engine = active.get("engine")
    chat_id = active.get("chat_id")
    if engine and chat_id:
        try:
            await engine.leave_call(chat_id)
        except (NotInCallError, Exception):
            pass
    try:
        await active["client"].disconnect()
    except Exception:
        pass


async def leave_live_stream(
    session_string: str,
    link_info: dict,
    user_id: int = None,
    account_id: int = None,
) -> dict:
    result = {"success": False, "error": None}
    active = (
        _active_clients.get(user_id, {}).get(account_id)
        if user_id and account_id else None
    )

    if active:
        try:
            engine  = active.get("engine")
            chat_id = active.get("chat_id")
            if engine and chat_id:
                await engine.leave_call(chat_id)
            result["success"] = True
        except Exception as e:
            result["error"] = str(e)
        finally:
            await _cleanup_active(user_id, account_id, active)
    else:
        # Fallback: direct API call
        client = make_client(session_string)
        try:
            await client.connect()
            _, call_obj = await _get_entity_and_call(client, link_info)
            if call_obj is None:
                result["error"] = "no_active_call"
                return result
            call = InputGroupCall(id=call_obj.id, access_hash=call_obj.access_hash)
            await client(LeaveGroupCallRequest(call=call, source=0))
            result["success"] = True
        except Exception as e:
            result["error"] = str(e)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    return result


async def leave_all(user_id: int) -> dict:
    accounts = dict(_active_clients.get(user_id, {}))
    left = failed = 0
    for acc_id, active in accounts.items():
        try:
            engine  = active.get("engine")
            chat_id = active.get("chat_id")
            if engine and chat_id:
                await engine.leave_call(chat_id)
            left += 1
        except Exception:
            failed += 1
        await _cleanup_active(user_id, acc_id, active)
    _active_clients.pop(user_id, None)
    return {"left": left, "failed": failed}


# ─── Hand raise ───────────────────────────────────────────────────────────────

async def raise_hand(
    session_string: str,
    link_info: dict,
    user_id: int = None,
    account_id: int = None,
) -> dict:
    result = {"success": False, "error": None}
    active = (
        _active_clients.get(user_id, {}).get(account_id)
        if user_id and account_id else None
    )
    client = active["client"] if active else make_client(session_string)
    should_disconnect = active is None

    try:
        if not client.is_connected():
            await client.connect()

        if active:
            call = active["call"]
        else:
            _, call_obj = await _get_entity_and_call(client, link_info)
            if call_obj is None:
                result["error"] = "no_active_call"
                return result
            call = InputGroupCall(id=call_obj.id, access_hash=call_obj.access_hash)

        me = await client.get_me()
        await client(EditGroupCallParticipantRequest(
            call=call, participant=me, muted=True, raise_hand=True,
        ))
        result["success"] = True

    except Exception as e:
        result["error"] = str(e)
    finally:
        if should_disconnect:
            try:
                await client.disconnect()
            except Exception:
                pass

    return result


# ─── Validate ─────────────────────────────────────────────────────────────────

async def validate_session(session_string: str) -> bool:
    client = make_client(session_string)
    try:
        await client.connect()
        return await client.is_user_authorized()
    except Exception:
        return False
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


def get_active_count(user_id: int) -> int:
    return len(_active_clients.get(user_id, {}))
