import streamlit as st
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

# Configurare pagină
st.set_page_config(
    page_title="🎬 AI Video Transcriber",
    page_icon="🎬",
    layout="wide"
)

st.title("🎬 AI Video Transcriber")
st.write("Test - Aplicația se încarcă!")

# Test 1: Verifică dacă SQLite funcționează
try:
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    cursor.execute('SELECT SQLITE_VERSION()')
    version = cursor.fetchone()
    st.success(f"✅ SQLite funcționează: v{version[0]}")
    conn.close()
except Exception as e:
    st.error(f"❌ Eroare SQLite: {e}")

# Test 2: Verifică importul google-genai
try:
    from google import genai
    st.success("✅ google-genai importat cu succes")
except ImportError as e:
    st.error(f"❌ Eroare import google-genai: {e}")
    st.info("Încearcă cu google-generativeai vechiul...")
    try:
        import google.generativeai as genai_old
        st.warning("⚠️ Folosim versiunea veche google-generativeai")
    except ImportError as e2:
        st.error(f"❌ Nici versiunea veche nu funcționează: {e2}")

# Test 3: Verifică python-docx
try:
    from docx import Document
    st.success("✅ python-docx importat cu succes")
except ImportError as e:
    st.error(f"❌ Eroare import python-docx: {e}")

# Test 4: Session state
if 'counter' not in st.session_state:
    st.session_state.counter = 0

if st.button("Test Counter"):
    st.session_state.counter += 1
    st.write(f"Counter: {st.session_state.counter}")

# Test 5: File uploader
uploaded_file = st.file_uploader("Test upload", type=['mp4', 'avi'])
if uploaded_file:
    st.write(f"Fișier încărcat: {uploaded_file.name}")
    st.video(uploaded_file)

st.write("---")
st.write("Dacă vezi acest mesaj, aplicația de bază funcționează!")
