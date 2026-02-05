import streamlit as st
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
import tempfile
import os
import time
from io import BytesIO
import json

# Încearcă să importe biblioteca Gemini
GEMINI_AVAILABLE = False
GEMINI_VERSION = None

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
    GEMINI_VERSION = "old"
except ImportError:
    st.error("❌ google-generativeai nu este instalat")

# Import python-docx
try:
    from docx import Document
    from docx.shared import Inches, Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False
    st.warning("⚠️ python-docx nu este disponibil")

# ==================== CONFIGURARE ====================

st.set_page_config(
    page_title="🎬 AI Video Transcriber",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# LIMITE FIȘIERE
MAX_FILE_SIZE_MB = 200  # Limita Gemini API
CHUNK_SIZE_MB = 190  # Dimensiune chunk pentru fișiere mari

# CSS
st.markdown("""
<style>
    .main-header {
        text-align: center;
        padding: 2rem;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 15px;
        margin-bottom: 2rem;
        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
    }
    .main-header h1 {
        margin: 0;
        font-size: 2.5rem;
    }
    .main-header p {
        margin: 0.5rem 0 0 0;
        opacity: 0.95;
    }
    .session-info {
        background-color: #e7f3ff;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #0066cc;
        margin-bottom: 1rem;
    }
    .api-key-status {
        padding: 0.5rem;
        border-radius: 5px;
        margin: 0.5rem 0;
    }
    .api-active {
        background-color: #d4edda;
        color: #155724;
    }
    .api-expired {
        background-color: #f8d7da;
        color: #721c24;
    }
    .transcription-box {
        background-color: #f8f9fa;
        padding: 1.5rem;
        border-radius: 10px;
        border: 1px solid #dee2e6;
        max-height: 500px;
        overflow-y: auto;
        font-family: 'Courier New', monospace;
        white-space: pre-wrap;
    }
    .warning-box {
        background-color: #fff3cd;
        border: 1px solid #ffc107;
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
    }
    .stButton > button {
        transition: all 0.3s;
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 5px 15px rgba(0,0,0,0.2);
    }
</style>
""", unsafe_allow_html=True)

# ==================== DATABASE ====================

DB_PATH = Path("data")
DB_PATH.mkdir(exist_ok=True)
DB_FILE = DB_PATH / "sessions.db"

def check_and_migrate_database():
    """Verifică și migrează baza de date dacă e nevoie"""
    conn = sqlite3.connect(str(DB_FILE))
    cursor = conn.cursor()
    
    try:
        # Verifică dacă există coloanele noi în tabelul transcriptions
        cursor.execute("PRAGMA table_info(transcriptions)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # Adaugă coloanele lipsă
        if 'source_language' not in columns:
            cursor.execute("""
                ALTER TABLE transcriptions 
                ADD COLUMN source_language TEXT DEFAULT 'Auto-detect'
            """)
            conn.commit()
        
        if 'target_language' not in columns:
            cursor.execute("""
                ALTER TABLE transcriptions 
                ADD COLUMN target_language TEXT DEFAULT 'Română'
            """)
            conn.commit()
        
        if 'status' not in columns:
            cursor.execute("""
                ALTER TABLE transcriptions 
                ADD COLUMN status TEXT DEFAULT 'completed'
            """)
            conn.commit()
            
    except Exception as e:
        pass
    finally:
        conn.close()

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
    
    # Tabel pentru transcrieri - versiunea completă
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transcriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            video_name TEXT,
            source_language TEXT DEFAULT 'Auto-detect',
            target_language TEXT DEFAULT 'Română',
            transcription TEXT,
            status TEXT DEFAULT 'completed',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    ''')
    
    # Tabel pentru mesaje conversație
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
    
    # Tabel pentru tracking chei API
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_key_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_index INTEGER,
            status TEXT,
            error_message TEXT,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    
    # Verifică și migrează dacă e nevoie
    check_and_migrate_database()

# ==================== SESSION MANAGEMENT ====================

def generate_session_id():
    return str(uuid.uuid4())[:8]

def get_session_id_from_url():
    """Obține session ID din query params"""
    params = st.query_params
    return params.get("session", None)

def set_session_id_in_url(session_id):
    """Setează session ID în URL"""
    st.query_params["session"] = session_id

def init_session():
    """Inițializează sau restaurează sesiunea"""
    url_session_id = get_session_id_from_url()
    
    if url_session_id and session_exists(url_session_id):
        st.session_state.session_id = url_session_id
        
        if 'session_loaded' not in st.session_state:
            st.session_state.messages = get_messages(url_session_id)
            st.session_state.transcriptions = get_transcriptions(url_session_id)
            st.session_state.session_loaded = True
    else:
        if 'session_id' not in st.session_state:
            new_session_id = generate_session_id()
            st.session_state.session_id = new_session_id
            create_session(new_session_id)
            set_session_id_in_url(new_session_id)
            st.session_state.messages = []
            st.session_state.transcriptions = []
            st.session_state.session_loaded = True
    
    if 'current_api_key_index' not in st.session_state:
        st.session_state.current_api_key_index = 0

def session_exists(session_id):
    """Verifică dacă sesiunea există în DB"""
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists
    except:
        return False

def create_session(session_id):
    """Creează o sesiune nouă în DB"""
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO sessions (session_id) VALUES (?)",
            (session_id,)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"Eroare la crearea sesiunii: {e}")

def delete_session_data(session_id):
    """Șterge toate datele unei sesiuni"""
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM transcriptions WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"Eroare la ștergerea datelor: {e}")

# ==================== API KEY MANAGEMENT ====================

def get_api_keys_from_secrets():
    """Obține cheile API din Streamlit secrets"""
    keys = []
    
    try:
        if "GEMINI_API_KEYS" in st.secrets:
            secret_keys = st.secrets["GEMINI_API_KEYS"]
            if isinstance(secret_keys, list):
                keys.extend(secret_keys)
            elif isinstance(secret_keys, str):
                keys.extend([k.strip() for k in secret_keys.split(",") if k.strip()])
        
        if "GEMINI_API_KEY" in st.secrets:
            single_key = st.secrets["GEMINI_API_KEY"]
            if single_key and single_key not in keys:
                keys.append(single_key)
                
    except Exception as e:
        pass
    
    return keys

def test_api_key(api_key):
    """Testează dacă o cheie API funcționează"""
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content('Say "OK"')
        return True, "✅ Cheie validă"
    except Exception as e:
        error_msg = str(e)
        if "quota" in error_msg.lower() or "billing" in error_msg.lower():
            return False, "❌ Cheie expirată (quota/billing)"
        elif "api key" in error_msg.lower() or "api_key" in error_msg.lower():
            return False, "❌ Cheie invalidă"
        else:
            return False, f"❌ Eroare: {error_msg[:100]}"

def get_working_api_key(keys):
    """Găsește prima cheie funcțională din listă"""
    if not keys:
        return None, None, "Nu există chei API configurate"
    
    for i, key in enumerate(keys):
        valid, msg = test_api_key(key)
        if valid:
            return key, i, msg
        
        log_api_key_usage(i, "failed", msg)
    
    return None, None, "Toate cheile API sunt expirate sau invalide"

def log_api_key_usage(key_index, status, error_msg=None):
    """Loghează folosirea unei chei API"""
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO api_key_usage (key_index, status, error_message) VALUES (?, ?, ?)",
            (key_index, status, error_msg)
        )
        conn.commit()
        conn.close()
    except:
        pass

# ==================== DATABASE OPERATIONS ====================

def save_message(session_id, role, content):
    """Salvează un mesaj în conversație"""
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"Eroare salvare mesaj: {e}")

def get_messages(session_id):
    """Obține mesajele unei sesiuni"""
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY created_at",
            (session_id,)
        )
        messages = [{"role": row[0], "content": row[1], "time": row[2]} for row in cursor.fetchall()]
        conn.close()
        return messages
    except:
        return []

def save_transcription(session_id, video_name, source_lang, target_lang, transcription):
    """Salvează o transcriere"""
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(transcriptions)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'source_language' in columns and 'target_language' in columns:
            cursor.execute(
                '''INSERT INTO transcriptions 
                   (session_id, video_name, source_language, target_language, transcription, status) 
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (session_id, video_name, source_lang, target_lang, transcription, 'completed')
            )
        else:
            cursor.execute(
                '''INSERT INTO transcriptions 
                   (session_id, video_name, transcription) 
                   VALUES (?, ?, ?)''',
                (session_id, video_name, transcription)
            )
        
        conn.commit()
        transcription_id = cursor.lastrowid
        conn.close()
        return transcription_id
    except Exception as e:
        st.error(f"Eroare salvare transcriere: {e}")
        return None

def get_transcriptions(session_id):
    """Obține transcrierile unei sesiuni"""
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(transcriptions)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'source_language' in columns and 'target_language' in columns:
            cursor.execute(
                '''SELECT id, video_name, source_language, target_language, 
                   transcription, status, created_at 
                   FROM transcriptions 
                   WHERE session_id = ? 
                   ORDER BY created_at DESC''',
                (session_id,)
            )
            
            transcriptions = []
            for row in cursor.fetchall():
                transcriptions.append({
                    "id": row[0],
                    "video_name": row[1],
                    "source_language": row[2],
                    "target_language": row[3],
                    "transcription": row[4],
                    "status": row[5],
                    "created_at": row[6]
                })
        else:
            cursor.execute(
                '''SELECT id, video_name, transcription, created_at 
                   FROM transcriptions 
                   WHERE session_id = ? 
                   ORDER BY created_at DESC''',
                (session_id,)
            )
            
            transcriptions = []
            for row in cursor.fetchall():
                transcriptions.append({
                    "id": row[0],
                    "video_name": row[1],
                    "source_language": "Auto-detect",
                    "target_language": "Română",
                    "transcription": row[2],
                    "status": "completed",
                    "created_at": row[3]
                })
        
        conn.close()
        return transcriptions
    except Exception as e:
        st.error(f"Eroare citire transcrieri: {e}")
        return []

# ==================== VIDEO PROCESSING ====================

SUPPORTED_FORMATS = ['mp4', 'mpeg', 'mov', 'avi', 'mkv', 'webm', 'flv', 'wmv']

LANGUAGES = {
    "Română": "Romanian",
    "Engleză": "English",
    "Spaniolă": "Spanish",
    "Franceză": "French",
    "Germană": "German",
    "Italiană": "Italian",
    "Portugheză": "Portuguese",
    "Rusă": "Russian",
    "Chineză": "Chinese",
    "Japoneză": "Japanese",
    "Coreeană": "Korean",
    "Arabă": "Arabic",
    "Hindusă": "Hindi",
    "Turcă": "Turkish",
    "Auto-detect": "auto"
}

def validate_file_size(file):
    """Validează dimensiunea fișierului"""
    file_size_mb = file.size / (1024 * 1024)
    return file_size_mb <= MAX_FILE_SIZE_MB, file_size_mb

def upload_video_to_gemini(video_path, progress_callback=None):
    """Încarcă video pe serverele Google"""
    try:
        if progress_callback:
            progress_callback(0.3, "📤 Încărcare video pe serverele Google...")
        
        # Verifică dimensiunea fișierului
        file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
        if file_size_mb > MAX_FILE_SIZE_MB:
            return None, f"❌ Fișierul este prea mare ({file_size_mb:.1f}MB). Limita este {MAX_FILE_SIZE_MB}MB"
        
        # Upload fișier
        video_file = genai.upload_file(path=video_path)
        
        if progress_callback:
            progress_callback(0.5, "⏳ Procesare video...")
        
        # Așteaptă procesarea
        max_wait = 120  # maxim 2 minute
        wait_time = 0
        while video_file.state.name == "PROCESSING" and wait_time < max_wait:
            time.sleep(2)
            wait_time += 2
            video_file = genai.get_file(video_file.name)
            
            if progress_callback:
                progress = 0.5 + (0.2 * (wait_time / max_wait))
                progress_callback(progress, f"⏳ Procesare video... ({wait_time}s)")
        
        if video_file.state.name == "FAILED":
            return None, "❌ Procesarea video a eșuat. Încercați un fișier mai mic sau alt format."
        
        if wait_time >= max_wait:
            return None, "❌ Timeout la procesarea video. Încercați un fișier mai mic."
        
        if progress_callback:
            progress_callback(0.7, "✅ Video încărcat cu succes!")
        
        return video_file, None
        
    except Exception as e:
        error_msg = str(e)
        if "size" in error_msg.lower() or "too large" in error_msg.lower():
            return None, f"❌ Fișierul este prea mare. Limita maximă este {MAX_FILE_SIZE_MB}MB"
        return None, f"❌ Eroare upload: {error_msg}"

def transcribe_video(video_file, source_lang, target_lang, api_key, progress_callback=None):
    """Transcrie video folosind Gemini"""
    try:
        if progress_callback:
            progress_callback(0.8, "🤖 Transcriere cu AI...")
        
        genai.configure(api_key=api_key)
        
        # Folosește modelul potrivit în funcție de durată
        # gemini-1.5-flash pentru videouri scurte (mai rapid)
        # gemini-1.5-pro pentru videouri lungi (mai precis)
        model = genai.GenerativeModel('gemini-1.5-pro')
        
        # Construiește prompt
        source = LANGUAGES.get(source_lang, "auto")
        target = LANGUAGES.get(target_lang, "Romanian")
        
        prompt = f"""
Analizează acest video și transcrie tot conținutul audio/vocal.

INSTRUCȚIUNI:
1. Limba sursă: {source} {'(detectează automat limba vorbită)' if source == 'auto' else ''}
2. Limba țintă pentru transcriere: {target}
3. Transcrie COMPLET tot ce se vorbește
4. Include timestamps pentru fiecare segment important
5. {'TRADUCE în ' + target if source != target and source != 'auto' else 'Păstrează limba originală'}
6. Formatează clar și profesional

FORMAT DORIT:
[MM:SS] - Text transcris
[MM:SS] - Continuare text...

Începe transcrierea:
"""
        
        # Generează cu timeout mai mare pentru videouri mari
        generation_config = genai.types.GenerationConfig(
            temperature=0.3,
            max_output_tokens=8192,
        )
        
        response = model.generate_content(
            [video_file, prompt],
            generation_config=generation_config,
            request_options={"timeout": 600}  # 10 minute timeout
        )
        
        if progress_callback:
            progress_callback(1.0, "✅ Transcriere completă!")
        
        return response.text, None
        
    except Exception as e:
        error_msg = str(e)
        if "quota" in error_msg.lower():
            return None, "❌ Quota API depășită pentru această cheie"
        elif "timeout" in error_msg.lower():
            return None, "❌ Timeout - videoul este prea lung. Încercați cu un video mai scurt."
        elif "size" in error_msg.lower():
            return None, f"❌ Videoul depășește limita. Maxim {MAX_FILE_SIZE_MB}MB"
        else:
            return None, f"❌ Eroare transcriere: {error_msg}"

def cleanup_video_file(video_file):
    """Șterge video de pe serverele Google"""
    try:
        genai.delete_file(video_file.name)
    except:
        pass

# ==================== WORD EXPORT ====================

def create_word_document(transcription, video_name, source_lang, target_lang):
    """Creează document Word cu transcrierea"""
    if not DOCX_AVAILABLE:
        return None
    
    try:
        doc = Document()
        
        title = doc.add_heading('Transcriere Video', 0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        doc.add_paragraph()
        info = doc.add_paragraph()
        info.add_run('Informații Document\n').bold = True
        info.add_run(f'📹 Video: {video_name}\n')
        info.add_run(f'🌐 Limba sursă: {source_lang}\n')
        info.add_run(f'🎯 Limba țintă: {target_lang}\n')
        info.add_run(f'📅 Data: {datetime.now().strftime("%d.%m.%Y %H:%M")}\n')
        
        doc.add_paragraph('─' * 60)
        
        doc.add_heading('Conținut Transcris', level=1)
        
        for line in transcription.split('\n'):
            if line.strip():
                para = doc.add_paragraph(line)
                para.paragraph_format.space_after = Pt(6)
        
        doc.add_paragraph()
        doc.add_paragraph('─' * 60)
        footer = doc.add_paragraph()
        footer.add_run('Generat cu AI Video Transcriber - Powered by Google Gemini').italic = True
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        doc_io = BytesIO()
        doc.save(doc_io)
        doc_io.seek(0)
        
        return doc_io
    except Exception as e:
        st.error(f"Eroare creare document Word: {e}")
        return None

# ==================== UI COMPONENTS ====================

def render_sidebar():
    """Sidebar cu configurări"""
    with st.sidebar:
        st.markdown("## ⚙️ Configurare")
        
        st.markdown(f"""
        <div class="session-info">
            <strong>📋 ID Sesiune:</strong> {st.session_state.session_id}<br>
            <strong>🔗 Link permanent:</strong><br>
            <code>?session={st.session_state.session_id}</code><br>
            <small>💡 Salvează acest link pentru a reveni la conversație</small>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("### 🔑 Status Chei API")
        
        keys = get_api_keys_from_secrets()
        
        if not keys:
            st.error("❌ Nu există chei API în Secrets!")
            st.markdown("""
            **Configurare în Streamlit Cloud:**
            1. Settings → Secrets
            2. Adaugă:
            ```
            GEMINI_API_KEYS = ["key1", "key2"]
            # sau
            GEMINI_API_KEY = "your-key"
            ```
            """)
            
            st.markdown("---")
            st.markdown("**SAU** adaugă temporar aici:")
            temp_key = st.text_input("Cheie API temporară:", type="password", key="temp_api_input")
            if st.button("Testează și folosește", key="test_api_btn"):
                if temp_key:
                    valid, msg = test_api_key(temp_key)
                    if valid:
                        if 'temp_api_keys' not in st.session_state:
                            st.session_state.temp_api_keys = []
                        st.session_state.temp_api_keys.append(temp_key)
                        st.success("✅ Cheie adăugată temporar!")
                        st.rerun()
                    else:
                        st.error(msg)
        else:
            st.success(f"✅ {len(keys)} chei disponibile din Secrets")
            
            if st.button("🔄 Testează toate cheile", key="test_all_keys"):
                with st.spinner("Testare..."):
                    for i, key in enumerate(keys):
                        valid, msg = test_api_key(key)
                        if valid:
                            st.success(f"Cheie {i+1}: {msg}")
                        else:
                            st.error(f"Cheie {i+1}: {msg}")
        
        if 'temp_api_keys' in st.session_state and st.session_state.temp_api_keys:
            st.info(f"📌 {len(st.session_state.temp_api_keys)} chei temporare active")
        
        st.markdown("---")
        
        # Info limită fișier
        st.markdown(f"""
        <div class="warning-box">
            <strong>⚠️ Limite fișiere:</strong><br>
            • Maxim {MAX_FILE_SIZE_MB}MB per video<br>
            • Formate: {', '.join(SUPPORTED_FORMATS[:5])}...<br>
            • Videouri lungi pot dura mai mult
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🔄 Reset conversație", use_container_width=True, key="reset_conv"):
                delete_session_data(st.session_state.session_id)
                st.session_state.messages = []
                st.session_state.transcriptions = []
                st.success("✅ Date resetate!")
                st.rerun()
        
        with col2:
            if st.button("🆕 Sesiune nouă", use_container_width=True, key="new_session"):
                new_id = generate_session_id()
                create_session(new_id)
                st.session_state.session_id = new_id
                st.session_state.messages = []
                st.session_state.transcriptions = []
                st.session_state.session_loaded = True
                if 'temp_api_keys' in st.session_state:
                    del st.session_state.temp_api_keys
                set_session_id_in_url(new_id)
                st.rerun()

def render_upload_tab():
    """Tab pentru upload video"""
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("### 📤 Încarcă Video")
        
        # File uploader cu limită specificată
        uploaded_file = st.file_uploader(
            f"Selectează fișier video (max {MAX_FILE_SIZE_MB}MB)",
            type=SUPPORTED_FORMATS,
            help=f"Formate suportate: {', '.join(SUPPORTED_FORMATS)}. Limită: {MAX_FILE_SIZE_MB}MB",
            key="video_uploader"
        )
        
        if uploaded_file:
            # Validează dimensiunea
            is_valid, file_size_mb = validate_file_size(uploaded_file)
            
            if not is_valid:
                st.error(f"""
                ❌ **Fișierul este prea mare!**
                • Dimensiune: {file_size_mb:.1f}MB
                • Limită maximă: {MAX_FILE_SIZE_MB}MB
                • Sugestii: Comprimați videoul sau folosiți un serviciu de compresie online
                """)
                
                # Sugestii pentru compresie
                with st.expander("💡 Cum să reduci dimensiunea video-ului"):
                    st.markdown("""
                    **Opțiuni pentru reducerea dimensiunii:**
                    
                    1. **Online (gratuit):**
                       - [CloudConvert](https://cloudconvert.com/video-compressor)
                       - [FreeConvert](https://www.freeconvert.com/video-compressor)
                       - [Clideo](https://clideo.com/compress-video)
                    
                    2. **Software desktop:**
                       - HandBrake (gratuit, toate platformele)
                       - VLC Media Player (gratuit)
                    
                    3. **Comenzi FFmpeg:**
                       ```bash
                       ffmpeg -i input.mp4 -vcodec h264 -acodec mp3 output.mp4
                       ```
                    
                    4. **Sfaturi:**
                       - Reduceți rezoluția (ex: 1080p → 720p)
                       - Reduceți bitrate-ul
                       - Tăiați părțile nenecesare
                    """)
                return
            
            # Afișează video și info
            st.video(uploaded_file)
            
            # Info despre fișier
            col_info1, col_info2 = st.columns(2)
            with col_info1:
                st.success(f"✅ **Dimensiune OK:** {file_size_mb:.1f}MB")
            with col_info2:
                st.info(f"📁 **Nume:** {uploaded_file.name}")
    
    with col2:
        st.markdown("### 🌐 Setări Limbă")
        
        source_lang = st.selectbox(
            "Limba sursă (din video)",
            options=list(LANGUAGES.keys()),
            index=list(LANGUAGES.keys()).index("Auto-detect"),
            key="source_lang"
        )
        
        target_lang = st.selectbox(
            "Limba țintă (transcriere)",
            options=[k for k in LANGUAGES.keys() if k != "Auto-detect"],
            index=0,  # Română
            key="target_lang"
        )
        
        # Estimare timp procesare
        if uploaded_file:
            file_size_mb = uploaded_file.size / (1024 * 1024)
            estimated_time = max(1, int(file_size_mb / 10))  # Aproximativ 10MB/minut
            st.info(f"⏱️ Timp estimat: {estimated_time}-{estimated_time*2} minute")
    
    if uploaded_file:
        # Re-validează înainte de procesare
        is_valid, file_size_mb = validate_file_size(uploaded_file)
        
        if is_valid and st.button("🚀 Începe Transcrierea", use_container_width=True, type="primary", key="start_transcribe"):
            # Obține cheile API
            keys = get_api_keys_from_secrets()
            
            # Adaugă cheile temporare dacă există
            if 'temp_api_keys' in st.session_state:
                keys = st.session_state.temp_api_keys + keys
            
            if not keys:
                st.error("❌ Nu există chei API disponibile!")
                return
            
            # Găsește o cheie funcțională
            working_key, key_index, msg = get_working_api_key(keys)
            
            if not working_key:
                st.error(f"❌ {msg}")
                return
            
            # Progress
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            def update_progress(value, text):
                progress_bar.progress(value)
                status_text.text(text)
            
            try:
                # 1. Salvează video temporar
                update_progress(0.1, "📁 Salvare fișier...")
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp:
                    tmp.write(uploaded_file.getbuffer())
                    tmp_path = tmp.name
                
                # 2. Upload pe Google
                video_file, error = upload_video_to_gemini(tmp_path, update_progress)
                
                if error:
                    st.error(error)
                    os.unlink(tmp_path)
                    return
                
                # 3. Transcrie
                transcription, error = transcribe_video(
                    video_file, source_lang, target_lang, 
                    working_key, update_progress
                )
                
                if error:
                    st.error(error)
                    # Încearcă cu altă cheie dacă aceasta a eșuat
                    if "quota" in error.lower() and key_index < len(keys) - 1:
                        st.warning("⚠️ Încerc cu altă cheie API...")
                        for next_key in keys[key_index + 1:]:
                            valid, _ = test_api_key(next_key)
                            if valid:
                                transcription, error = transcribe_video(
                                    video_file, source_lang, target_lang,
                                    next_key, update_progress
                                )
                                if not error:
                                    break
                    
                    if error:
                        cleanup_video_file(video_file)
                        os.unlink(tmp_path)
                        return
                
                # 4. Cleanup
                cleanup_video_file(video_file)
                os.unlink(tmp_path)
                
                # 5. Salvează în DB
                save_transcription(
                    st.session_state.session_id,
                    uploaded_file.name,
                    source_lang,
                    target_lang,
                    transcription
                )
                
                # Log succes
                log_api_key_usage(key_index, "success", None)
                
                update_progress(1.0, "✅ Transcriere completă!")
                st.success("🎉 Video transcris cu succes!")
                
                # Afișează rezultatul
                st.markdown("### 📝 Transcriere")
                st.markdown(f"""
                <div class="transcription-box">
{transcription}
                </div>
                """, unsafe_allow_html=True)
                
                # Butoane descărcare
                col1, col2 = st.columns(2)
                
                with col1:
                    word_doc = create_word_document(
                        transcription, uploaded_file.name,
                        source_lang, target_lang
                    )
                    if word_doc:
                        st.download_button(
                            "📥 Descarcă Word (.docx)",
                            word_doc,
                            f"transcriere_{uploaded_file.name.split('.')[0]}.docx",
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            key="download_word"
                        )
                
                with col2:
                    st.download_button(
                        "📥 Descarcă Text (.txt)",
                        transcription,
                        f"transcriere_{uploaded_file.name.split('.')[0]}.txt",
                        mime="text/plain",
                        key="download_txt"
                    )
                
                # Salvează în mesaje pentru chat
                save_message(
                    st.session_state.session_id,
                    "assistant",
                    f"✅ Am transcris video-ul '{uploaded_file.name}' ({file_size_mb:.1f}MB) din {source_lang} în {target_lang}"
                )
                
            except Exception as e:
                st.error(f"❌ Eroare neașteptată: {e}")

def render_history_tab():
    """Tab cu istoricul transcrierilor"""
    st.markdown("### 📜 Istoric Transcrieri")
    
    transcriptions = get_transcriptions(st.session_state.session_id)
    
    if not transcriptions:
        st.info("📭 Nu există transcrieri încă. Încarcă un video pentru a începe!")
    else:
        for i, trans in enumerate(transcriptions):
            with st.expander(
                f"🎬 {trans['video_name']} - {trans['created_at']}",
                expanded=False
            ):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.write(f"**Limba sursă:** {trans.get('source_language', 'Auto-detect')}")
                with col2:
                    st.write(f"**Limba țintă:** {trans.get('target_language', 'Română')}")
                with col3:
                    st.write(f"**Status:** {trans.get('status', 'completed')}")
                
                st.markdown("**Transcriere:**")
                st.text_area(
                    "text",
                    trans['transcription'],
                    height=300,
                    key=f"trans_{trans['id']}_{i}",
                    label_visibility="collapsed"
                )
                
                # Descărcări
                col1, col2 = st.columns(2)
                with col1:
                    word_doc = create_word_document(
                        trans['transcription'],
                        trans['video_name'],
                        trans.get('source_language', 'Auto-detect'),
                        trans.get('target_language', 'Română')
                    )
                    if word_doc:
                        st.download_button(
                            "📥 Word",
                            word_doc,
                            f"transcriere_{trans['id']}.docx",
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            key=f"word_{trans['id']}_{i}"
                        )
                
                with col2:
                    st.download_button(
                        "📥 Text",
                        trans['transcription'],
                        f"transcriere_{trans['id']}.txt",
                        mime="text/plain",
                        key=f"txt_{trans['id']}_{i}"
                    )

def render_chat_tab():
    """Tab pentru chat cu AI"""
    st.markdown("### 💬 Conversație cu AI")
    st.caption("Întreabă despre transcrieri sau cere ajutor")
    
    # Afișează mesajele
    messages = get_messages(st.session_state.session_id)
    
    for msg in messages:
        with st.chat_message(msg['role']):
            st.markdown(msg['content'])
    
    # Input mesaj nou
    if prompt := st.chat_input("Scrie un mesaj...", key="chat_input"):
        # Salvează și afișează mesajul utilizatorului
        with st.chat_message("user"):
            st.markdown(prompt)
        save_message(st.session_state.session_id, "user", prompt)
        
        # Generează răspuns
        with st.chat_message("assistant"):
            with st.spinner("Generez răspuns..."):
                # Obține cheile
                keys = get_api_keys_from_secrets()
                if 'temp_api_keys' in st.session_state:
                    keys = st.session_state.temp_api_keys + keys
                
                if not keys:
                    st.error("❌ Nu există chei API!")
                    return
                
                # Găsește cheie funcțională
                working_key, _, _ = get_working_api_key(keys)
                if not working_key:
                    st.error("❌ Toate cheile API sunt invalide!")
                    return
                
                try:
                    genai.configure(api_key=working_key)
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    
                    # Context cu transcrieri recente
                    recent_trans = get_transcriptions(st.session_state.session_id)[:3]
                    context = ""
                    if recent_trans:
                        context = "Context - Transcrieri recente:\n"
                        for t in recent_trans:
                            context += f"- {t['video_name']}: {t['transcription'][:200]}...\n"
                    
                    # Generează răspuns
                    full_prompt = f"""
                    {context}
                    
                    Utilizator: {prompt}
                    
                    Răspunde în română, util și concis. Dacă întrebarea e despre transcrieri, folosește contextul.
                    """
                    
                    response = model.generate_content(full_prompt)
                    response_text = response.text
                    
                    st.markdown(response_text)
                    save_message(st.session_state.session_id, "assistant", response_text)
                    
                except Exception as e:
                    st.error(f"❌ Eroare: {e}")

# ==================== MAIN APP ====================

def main():
    # Inițializare
    init_database()
    init_session()
    
    # Sidebar
    render_sidebar()
    
    # Header
    st.markdown("""
    <div class="main-header">
        <h1>🎬 AI Video Transcriber</h1>
        <p>Transcrie orice video în orice limbă folosind Google Gemini AI</p>
        <p style="font-size: 0.9rem; opacity: 0.8;">Limită fișier: {MAX_FILE_SIZE_MB}MB | Formate: MP4, AVI, MOV, MKV și altele</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Verificare sistem
    if not GEMINI_AVAILABLE:
        st.error("❌ Google Generative AI nu este instalat corect!")
        st.stop()
    
    # Tabs
    tab1, tab2, tab3 = st.tabs(["📤 Încarcă Video", "📜 Istoric", "💬 Chat AI"])
    
    with tab1:
        render_upload_tab()
    
    with tab2:
        render_history_tab()
    
    with tab3:
        render_chat_tab()

if __name__ == "__main__":
    main()
