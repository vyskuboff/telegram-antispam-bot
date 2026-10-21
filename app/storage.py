import json
import sqlite3
from contextlib import contextmanager

from app.config import DATA_DIR


DB_FILE = DATA_DIR / "state.db"


@contextmanager
def connection():
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_users (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                attempts INTEGER DEFAULT 0,
                message_id INTEGER,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS last_block (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                token TEXT,
                messages TEXT,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        conn.execute("CREATE TABLE IF NOT EXISTS stop_words (word TEXT PRIMARY KEY)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS private_contacts (
                user_id INTEGER PRIMARY KEY,
                first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                forwarded_messages INTEGER NOT NULL DEFAULT 1
            )
        """)

        # Backward-compatible migration from v4. Existing contacts already had
        # their first message forwarded, so their counter starts at 1.
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(private_contacts)").fetchall()
        }
        if "forwarded_messages" not in columns:
            conn.execute(
                "ALTER TABLE private_contacts "
                "ADD COLUMN forwarded_messages INTEGER NOT NULL DEFAULT 1"
            )


def add_pending_user(chat_id, user_id):
    with connection() as conn:
        conn.execute(
            "REPLACE INTO pending_users(chat_id, user_id, attempts, message_id) VALUES (?, ?, 0, NULL)",
            (chat_id, user_id),
        )


def get_pending_user(chat_id, user_id):
    with connection() as conn:
        return conn.execute(
            "SELECT * FROM pending_users WHERE chat_id=? AND user_id=?", (chat_id, user_id)
        ).fetchone()


def list_pending_users():
    with connection() as conn:
        return conn.execute("SELECT chat_id, user_id FROM pending_users").fetchall()


def update_pending_attempt(chat_id, user_id, attempts, message_id):
    with connection() as conn:
        conn.execute(
            "UPDATE pending_users SET attempts=?, message_id=? WHERE chat_id=? AND user_id=?",
            (attempts, message_id, chat_id, user_id),
        )


def delete_pending_user(chat_id, user_id):
    with connection() as conn:
        conn.execute(
            "DELETE FROM pending_users WHERE chat_id=? AND user_id=?", (chat_id, user_id)
        )


def load_last_block():
    result = {}
    with connection() as conn:
        rows = conn.execute("SELECT * FROM last_block").fetchall()
    for row in rows:
        try:
            messages = {int(k): int(v) for k, v in json.loads(row["messages"] or "{}").items()}
        except (ValueError, TypeError, AttributeError):
            messages = {}
        result[(row["chat_id"], row["user_id"])] = {
            "token": row["token"], "messages": messages
        }
    return result


def save_last_block_entry(chat_id, user_id, token, messages):
    with connection() as conn:
        conn.execute(
            "REPLACE INTO last_block(chat_id, user_id, token, messages) VALUES (?, ?, ?, ?)",
            (chat_id, user_id, token, json.dumps(messages)),
        )


def delete_last_block_entry(chat_id, user_id):
    with connection() as conn:
        conn.execute(
            "DELETE FROM last_block WHERE chat_id=? AND user_id=?", (chat_id, user_id)
        )


def get_stop_words():
    with connection() as conn:
        return [row[0] for row in conn.execute("SELECT word FROM stop_words ORDER BY word COLLATE NOCASE")]


def add_stop_word_db(word):
    with connection() as conn:
        return conn.execute("INSERT OR IGNORE INTO stop_words(word) VALUES (?)", (word,)).rowcount > 0


def delete_stop_word_db(word):
    with connection() as conn:
        return conn.execute("DELETE FROM stop_words WHERE word=?", (word,)).rowcount > 0



def register_private_contact_message(user_id, max_forwarded=3):
    """Reserve one of the first N private-message forwarding slots atomically.

    Returns the 1-based message number to forward, or None when the user has
    already exhausted all forwarding slots.
    """
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        inserted = conn.execute(
            """
            INSERT OR IGNORE INTO private_contacts(user_id, forwarded_messages)
            VALUES (?, 1)
            """,
            (user_id,),
        )
        if inserted.rowcount > 0:
            return 1

        updated = conn.execute(
            """
            UPDATE private_contacts
            SET forwarded_messages = forwarded_messages + 1
            WHERE user_id=? AND forwarded_messages < ?
            """,
            (user_id, max_forwarded),
        )
        if updated.rowcount == 0:
            return None

        row = conn.execute(
            "SELECT forwarded_messages FROM private_contacts WHERE user_id=?",
            (user_id,),
        ).fetchone()
        return int(row["forwarded_messages"])


def backup_database(destination):
    with connection() as source:
        with sqlite3.connect(destination) as target:
            source.backup(target)
