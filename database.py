import sqlite3
import json
from datetime import datetime
from pathlib import Path

# Creează directorul pentru baza de date
DB_PATH = Path("data")
DB_PATH.mkdir(exist_ok=True)
DB_FILE = DB_PATH / "sessions.db"

def init_database():
    """Inițializează baza de date SQLite"""
    conn = sqlite3.connect(str(DB_FILE))
    cursor = conn.cursor()
    
    # Tabel pentru sesiuni
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabel pentru conversații/transcrieri
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transcriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            video_name TEXT,
            original_language TEXT,
            target_language TEXT,
            transcription TEXT,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    ''')
    
    # Tabel pentru mesaje de conversație
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    ''')
    
    # Tabel pentru chei API și statusul lor
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key TEXT UNIQUE,
            status TEXT DEFAULT 'active',
            last_used TIMESTAMP,
            error_count INTEGER DEFAULT 0,
            last_error TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

def get_connection():
    """Returnează conexiunea la baza de date"""
    return sqlite3.connect(str(DB_FILE))

# ============ SESIUNI ============

def create_session(session_id: str):
    """Creează o sesiune nouă"""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO sessions (session_id) VALUES (?)",
            (session_id,)
        )
        conn.commit()
    finally:
        conn.close()

def session_exists(session_id: str) -> bool:
    """Verifică dacă sesiunea există"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM sessions WHERE session_id = ?",
        (session_id,)
    )
    result = cursor.fetchone()
    conn.close()
    return result is not None

def delete_session(session_id: str):
    """Șterge o sesiune și toate datele asociate"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    cursor.execute("DELETE FROM transcriptions WHERE session_id = ?", (session_id,))
    cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()

# ============ MESAJE ============

def save_message(session_id: str, role: str, content: str):
    """Salvează un mesaj în conversație"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
        (session_id, role, content)
    )
    conn.commit()
    conn.close()

def get_messages(session_id: str) -> list:
    """Obține toate mesajele pentru o sesiune"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY created_at",
        (session_id,)
    )
    messages = [{"role": row[0], "content": row[1], "time": row[2]} for row in cursor.fetchall()]
    conn.close()
    return messages

def clear_messages(session_id: str):
    """Șterge toate mesajele pentru o sesiune"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()

# ============ TRANSCRIERI ============

def save_transcription(session_id: str, video_name: str, original_lang: str, 
                       target_lang: str, transcription: str, status: str = "completed"):
    """Salvează o transcriere"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO transcriptions 
        (session_id, video_name, original_language, target_language, transcription, status)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (session_id, video_name, original_lang, target_lang, transcription, status))
    conn.commit()
    transcription_id = cursor.lastrowid
    conn.close()
    return transcription_id

def get_transcriptions(session_id: str) -> list:
    """Obține toate transcrierile pentru o sesiune"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, video_name, original_language, target_language, 
               transcription, status, created_at 
        FROM transcriptions 
        WHERE session_id = ? 
        ORDER BY created_at DESC
    ''', (session_id,))
    
    transcriptions = []
    for row in cursor.fetchall():
        transcriptions.append({
            "id": row[0],
            "video_name": row[1],
            "original_language": row[2],
            "target_language": row[3],
            "transcription": row[4],
            "status": row[5],
            "created_at": row[6]
        })
    conn.close()
    return transcriptions

# ============ API KEYS ============

def add_api_key(api_key: str):
    """Adaugă o cheie API"""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO api_keys (api_key, status) VALUES (?, 'active')",
            (api_key,)
        )
        conn.commit()
    finally:
        conn.close()

def get_active_api_keys() -> list:
    """Obține toate cheile API active"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT api_key FROM api_keys WHERE status = 'active' ORDER BY error_count ASC"
    )
    keys = [row[0] for row in cursor.fetchall()]
    conn.close()
    return keys

def get_all_api_keys() -> list:
    """Obține toate cheile API cu statusul lor"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT api_key, status, last_used, error_count, last_error 
        FROM api_keys ORDER BY id
    ''')
    keys = []
    for row in cursor.fetchall():
        keys.append({
            "key": row[0][:10] + "..." + row[0][-4:] if len(row[0]) > 14 else row[0],
            "full_key": row[0],
            "status": row[1],
            "last_used": row[2],
            "error_count": row[3],
            "last_error": row[4]
        })
    conn.close()
    return keys

def mark_key_expired(api_key: str, error_message: str):
    """Marchează o cheie ca expirată"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE api_keys 
        SET status = 'expired', 
            error_count = error_count + 1,
            last_error = ?,
            last_used = CURRENT_TIMESTAMP
        WHERE api_key = ?
    ''', (error_message, api_key))
    conn.commit()
    conn.close()

def mark_key_active(api_key: str):
    """Marchează o cheie ca activă"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE api_keys 
        SET status = 'active', 
            last_used = CURRENT_TIMESTAMP
        WHERE api_key = ?
    ''', (api_key,))
    conn.commit()
    conn.close()

def reset_api_key_status(api_key: str):
    """Resetează statusul unei chei API"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE api_keys 
        SET status = 'active', error_count = 0, last_error = NULL
        WHERE api_key = ?
    ''', (api_key,))
    conn.commit()
    conn.close()

def delete_api_key(api_key: str):
    """Șterge o cheie API"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM api_keys WHERE api_key = ?", (api_key,))
    conn.commit()
    conn.close()

# Inițializează baza de date la import
init_database()
