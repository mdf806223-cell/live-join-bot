import sqlite3
import aiosqlite
from config import DATABASE_PATH


async def get_db():
    return await aiosqlite.connect(DATABASE_PATH)


async def init_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                created_at  TEXT DEFAULT (datetime('now')),
                state       TEXT DEFAULT 'idle'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL,
                phone        TEXT NOT NULL,
                name         TEXT,
                status       TEXT DEFAULT 'active',
                added_at     TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        INTEGER NOT NULL,
                account_id     INTEGER NOT NULL,
                session_string TEXT NOT NULL,
                export_ready   INTEGER DEFAULT 1,
                FOREIGN KEY (user_id)    REFERENCES users(user_id),
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
        """)
        await db.commit()
