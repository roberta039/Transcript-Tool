import streamlit as st
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
import tempfile
import os
import time
from io import BytesIO

# Încearcă să importe biblioteca Gemini
GEMINI_AVAILABLE = False
GEMINI_VERSION = None

try:
    from google import genai
    GEMINI_AVAILABLE = True
    GEMINI_VERSION = "new"
    st.success("✅ Folosim google-genai (versiunea nouă)")
except ImportError:
    try:
        import google.generativeai as genai
        GEMINI_AVAILABLE = True
        GEMINI_VERSION = "old"
        st.warning("⚠️ Folosim google-generativeai (versiunea veche)")
    except ImportError:
        st.error("❌ Nu s-a putut importa nicio versiune de Gemini API")

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

# CSS
st.markdown("""
<style>
    .main-header {
        text-align: center;
        padding: 1rem;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 10px;
        margin-bottom: 2rem;
    }
    .info-box {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

# ==================== DATABASE ====================

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
    
    # Tabel pentru transcrieri
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transcriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            video_name TEXT,
            transcription TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    ''')
    
    # Tabel pentru API keys
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key TEXT UNIQUE,
            status TEXT DEFAULT 'active',
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# ==================== FUNCȚII HELPER ====================

def generate_session_id():
    return str(uuid.uuid4())[:8]

def get_or_create_session():
    """Obține sau creează o sesiune"""
    if 'session_id' not in st.session_state:
        st.session_state.session_id = generate_session_id()
        
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO sessions (session_id) VALUES (?)",
            (st.session_state.session_id,)
        )
        conn.commit()
        conn.close()
    
    return st.session_state.session_id

def save_api_key(api_key):
    """Salvează o cheie API"""
    conn = sqlite3.connect(str(DB_FILE))
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO api_keys (api_key) VALUES (?)",
            (api_key,)
        )
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def get_active_api_keys():
    """Obține cheile API active"""
    conn = sqlite3.connect(str(DB_FILE))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT api_key FROM api_keys WHERE status = 'active'"
    )
    keys = [row[0] for row in cursor.fetchall()]
    conn.close()
    return keys

def save_transcription(session_id, video_name, transcription):
    """Salvează o transcriere"""
    conn = sqlite3.connect(str(DB_FILE))
    cursor = conn.cursor()
    cursor.execute(
        '''INSERT INTO transcriptions 
           (session_id, video_name, transcription) 
           VALUES (?, ?, ?)''',
        (session_id, video_name, transcription)
    )
    conn.commit()
    conn.close()

def get_transcriptions(session_id):
    """Obține transcrierile pentru o sesiune"""
    conn = sqlite3.connect(str(DB_FILE))
    cursor = conn.cursor()
    cursor.execute(
        '''SELECT video_name, transcription, created_at 
           FROM transcriptions 
           WHERE session_id = ? 
           ORDER BY created_at DESC''',
        (session_id,)
    )
    results = cursor.fetchall()
    conn.close()
    return results

# ==================== GEMINI API ====================

def test_api_key(api_key):
    """Testează dacă o cheie API funcționează"""
    if not GEMINI_AVAILABLE:
        return False, "Gemini API nu este disponibil"
    
    try:
        if GEMINI_VERSION == "new":
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model='gemini-2.0-flash-exp',
                contents='Say "OK"'
            )
        else:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content('Say "OK"')
        
        return True, "Cheie validă"
    except Exception as e:
        return False, str(e)

def transcribe_with_gemini(video_path, api_key):
    """Transcrie un video folosind Gemini"""
    if not GEMINI_AVAILABLE:
        return None, "Gemini API nu este disponibil"
    
    try:
        if GEMINI_VERSION == "new":
            client = genai.Client(api_key=api_key)
            
            # Upload video
            with open(video_path, 'rb') as f:
                video_file = client.files.upload(file=f)
            
            # Așteaptă procesarea
            time.sleep(2)
            
            # Transcrie
            response = client.models.generate_content(
                model='gemini-2.0-flash-exp',
                contents=[
                    video_file,
                    "Transcrie complet acest video în română. Include timestamps."
                ]
            )
            
            return response.text, None
            
        else:  # old version
            genai.configure(api_key=api_key)
            
            # Upload video
            video_file = genai.upload_file(path=video_path)
            
            # Așteaptă procesarea
            while video_file.state.name == "PROCESSING":
                time.sleep(2)
                video_file = genai.get_file(video_file.name)
            
            if video_file.state.name == "FAILED":
                return None, "Procesarea video a eșuat"
            
            # Transcrie
            model = genai.GenerativeModel('gemini-1.5-pro')
            response = model.generate_content(
                [video_file, "Transcrie complet acest video în română. Include timestamps."]
            )
            
            return response.text, None
            
    except Exception as e:
        return None, str(e)

def create_word_document(transcription, video_name):
    """Creează un document Word"""
    if not DOCX_AVAILABLE:
        return None
    
    doc = Document()
    
    # Titlu
    doc.add_heading('Transcriere Video', 0)
    
    # Info
    doc.add_paragraph(f'Video: {video_name}')
    doc.add_paragraph(f'Data: {datetime.now().strftime("%d.%m.%Y %H:%M")}')
    
    # Separator
    doc.add_paragraph('─' * 50)
    
    # Transcriere
    doc.add_heading('Transcriere', level=1)
    doc.add_paragraph(transcription)
    
    # Salvează în BytesIO
    doc_io = BytesIO()
    doc.save(doc_io)
    doc_io.seek(0)
    
    return doc_io

# ==================== INTERFAȚĂ ====================

def render_sidebar():
    """Bara laterală"""
    with st.sidebar:
        st.markdown("## ⚙️ Configurare")
        
        # Info sesiune
        session_id = get_or_create_session()
        st.info(f"📋 Sesiune: {session_id}")
        
        st.markdown("---")
        
        # API Keys
        st.markdown("### 🔑 Chei API")
        
        # Verifică cheile din secrets
        if "GEMINI_API_KEY" in st.secrets:
            save_api_key(st.secrets["GEMINI_API_KEY"])
            st.success("✅ Cheie din secrets detectată")
        
        # Afișează cheile existente
        keys = get_active_api_keys()
        if keys:
            st.success(f"✅ {len(keys)} chei disponibile")
        else:
            st.warning("⚠️ Nu există chei API")
        
        # Adaugă cheie nouă
        new_key = st.text_input(
            "Adaugă cheie API",
            type="password",
            placeholder="AIza..."
        )
        
        if st.button("➕ Adaugă Cheie"):
            if new_key:
                # Testează cheia
                valid, msg = test_api_key(new_key)
                if valid:
                    if save_api_key(new_key):
                        st.success("✅ Cheie adăugată!")
                        st.rerun()
                else:
                    st.error(f"❌ Cheie invalidă: {msg}")
        
        st.markdown("---")
        
        # Reset
        if st.button("🔄 Reset Sesiune"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

def render_main():
    """Conținut principal"""
    
    # Header
    st.markdown("""
    <div class="main-header">
        <h1>🎬 AI Video Transcriber</h1>
        <p>Transcrie video-uri folosind Gemini AI</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Verificări sistem
    col1, col2, col3 = st.columns(3)
    with col1:
        if GEMINI_AVAILABLE:
            st.success(f"✅ Gemini API ({GEMINI_VERSION})")
        else:
            st.error("❌ Gemini API")
    
    with col2:
        if DOCX_AVAILABLE:
            st.success("✅ Export Word")
        else:
            st.warning("⚠️ Export Word")
    
    with col3:
        if get_active_api_keys():
            st.success("✅ API Keys")
        else:
            st.error("❌ API Keys")
    
    st.markdown("---")
    
    # Tabs
    tab1, tab2 = st.tabs(["📤 Încarcă Video", "📜 Istoric"])
    
    with tab1:
        # Upload video
        uploaded_file = st.file_uploader(
            "Selectează video",
            type=['mp4', 'avi', 'mov', 'mkv', 'webm']
        )
        
        if uploaded_file:
            st.video(uploaded_file)
            
            col1, col2 = st.columns(2)
            with col1:
                st.info(f"📁 {uploaded_file.name}")
            with col2:
                st.info(f"📏 {uploaded_file.size / 1024 / 1024:.2f} MB")
            
            if st.button("🚀 Transcrie", type="primary", use_container_width=True):
                
                # Verifică API key
                keys = get_active_api_keys()
                if not keys:
                    st.error("❌ Adaugă o cheie API în sidebar!")
                    return
                
                # Progress
                progress = st.progress(0)
                status = st.empty()
                
                try:
                    # Salvează video temporar
                    status.text("📁 Salvare fișier...")
                    progress.progress(20)
                    
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp:
                        tmp.write(uploaded_file.getbuffer())
                        tmp_path = tmp.name
                    
                    # Transcrie
                    status.text("🤖 Transcriere cu AI...")
                    progress.progress(50)
                    
                    transcription, error = transcribe_with_gemini(tmp_path, keys[0])
                    
                    # Șterge fișierul temporar
                    os.unlink(tmp_path)
                    
                    if error:
                        st.error(f"❌ Eroare: {error}")
                        return
                    
                    # Salvează în DB
                    status.text("💾 Salvare...")
                    progress.progress(90)
                    
                    save_transcription(
                        st.session_state.session_id,
                        uploaded_file.name,
                        transcription
                    )
                    
                    # Finalizare
                    progress.progress(100)
                    status.text("✅ Completat!")
                    
                    st.success("🎉 Transcriere finalizată!")
                    
                    # Afișează rezultatul
                    st.text_area("Transcriere:", transcription, height=300)
                    
                    # Descărcare
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.download_button(
                            "📥 Descarcă TXT",
                            transcription,
                            f"{uploaded_file.name}.txt",
                            mime="text/plain"
                        )
                    
                    with col2:
                        if DOCX_AVAILABLE:
                            doc = create_word_document(transcription, uploaded_file.name)
                            if doc:
                                st.download_button(
                                    "📥 Descarcă Word",
                                    doc,
                                    f"{uploaded_file.name}.docx",
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                                )
                    
                except Exception as e:
                    st.error(f"❌ Eroare: {e}")
    
    with tab2:
        # Istoric
        st.markdown("### 📜 Istoric Transcrieri")
        
        transcriptions = get_transcriptions(st.session_state.session_id)
        
        if not transcriptions:
            st.info("Nu există transcrieri încă.")
        else:
            for video_name, text, created_at in transcriptions:
                with st.expander(f"🎬 {video_name} - {created_at}"):
                    st.text_area("", text, height=200, key=f"hist_{created_at}")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.download_button(
                            "📥 TXT",
                            text,
                            f"{video_name}.txt",
                            key=f"txt_{created_at}"
                        )
                    with col2:
                        if DOCX_AVAILABLE:
                            doc = create_word_document(text, video_name)
                            if doc:
                                st.download_button(
                                    "📥 Word",
                                    doc,
                                    f"{video_name}.docx",
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    key=f"doc_{created_at}"
                                )

# ==================== MAIN ====================

def main():
    # Inițializare DB
    init_database()
    
    # Render
    render_sidebar()
    render_main()

if __name__ == "__main__":
    main()
