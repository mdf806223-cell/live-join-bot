import aiosqlite
from config import DATABASE_PATH


# ─── Users ────────────────────────────────────────────────────────────────────

async def upsert_user(user_id: int, username: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, username) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username=excluded.username
        """, (user_id, username))
        await db.commit()


async def set_user_state(user_id: int, state: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE users SET state=? WHERE user_id=?", (state, user_id))
        await db.commit()


async def get_user_state(user_id: int) -> str:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT state FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else "idle"


# ─── Accounts ─────────────────────────────────────────────────────────────────

async def add_account(user_id: int, phone: str, name: str, session_string: str) -> int:
    from utils.crypto import encrypt
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cur = await db.execute(
            "INSERT INTO accounts (user_id, phone, name, status) VALUES (?, ?, ?, 'active')",
            (user_id, phone, name)
        )
        account_id = cur.lastrowid
        enc_session = encrypt(session_string)
        await db.execute(
            "INSERT INTO sessions (user_id, account_id, session_string) VALUES (?, ?, ?)",
            (user_id, account_id, enc_session)
        )
        await db.commit()
        return account_id


async def get_accounts(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM accounts WHERE user_id=? ORDER BY added_at DESC", (user_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_account(user_id: int, account_id: int) -> dict | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM accounts WHERE id=? AND user_id=?", (account_id, user_id)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def rename_account(user_id: int, account_id: int, new_name: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE accounts SET name=? WHERE id=? AND user_id=?",
            (new_name, account_id, user_id)
        )
        await db.commit()


async def set_account_status(user_id: int, account_id: int, status: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE accounts SET status=? WHERE id=? AND user_id=?",
            (status, account_id, user_id)
        )
        await db.commit()


async def delete_account(user_id: int, account_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM sessions WHERE account_id=? AND user_id=?", (account_id, user_id))
        await db.execute("DELETE FROM accounts WHERE id=? AND user_id=?", (account_id, user_id))
        await db.commit()


async def get_session_string(user_id: int, account_id: int) -> str | None:
    from utils.crypto import decrypt
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT session_string FROM sessions WHERE account_id=? AND user_id=?",
            (account_id, user_id)
        ) as cur:
            row = await cur.fetchone()
            return decrypt(row[0]) if row else None


async def get_all_sessions(user_id: int) -> list[dict]:
    """Return decrypted sessions with account info for a user."""
    from utils.crypto import decrypt
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT a.id, a.phone, a.name, a.status, s.session_string
            FROM accounts a
            JOIN sessions s ON s.account_id = a.id
            WHERE a.user_id=? AND a.status='active'
        """, (user_id,)) as cur:
            rows = await cur.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["session_string"] = decrypt(d["session_string"])
                result.append(d)
            return result


async def count_accounts(user_id: int) -> dict:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM accounts WHERE user_id=?", (user_id,)
        ) as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM accounts WHERE user_id=? AND status='active'", (user_id,)
        ) as cur:
            active = (await cur.fetchone())[0]
    return {"total": total, "active": active}
