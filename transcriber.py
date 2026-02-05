import streamlit as st
from google import genai
from google.genai import types
import tempfile
import os
import time
from typing import Tuple, Optional
from api_manager import api_manager

class VideoTranscriber:
    """Gestionează transcrierea video folosind Gemini"""
    
    SUPPORTED_FORMATS = ['mp4', 'mpeg', 'mov', 'avi', 'mkv', 'webm', 'flv', 'wmv']
    MAX_FILE_SIZE_MB = 100  # Limita pentru upload
    
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
        "Poloneză": "Polish",
        "Olandeză": "Dutch",
        "Suedeză": "Swedish",
        "Auto-detect": "auto-detect"
    }
    
    def __init__(self):
        self.client = None
    
    def initialize_client(self, api_key: str):
        """Inițializează clientul Gemini"""
        self.client = genai.Client(api_key=api_key)
    
    def upload_video_to_gemini(self, video_file, progress_callback=None) -> Tuple[Optional[object], Optional[str]]:
        """
        Încarcă video-ul pe serverele Google.
        Returnează (file_object, None) sau (None, error_message)
        """
        try:
            if progress_callback:
                progress_callback(0.1, "Salvare fișier temporar...")
            
            # Salvează fișierul temporar
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{video_file.name.split('.')[-1]}") as tmp_file:
                tmp_file.write(video_file.getvalue())
                tmp_path = tmp_file.name
            
            if progress_callback:
                progress_callback(0.3, "Încărcare pe serverele Google...")
            
            # Încarcă pe Google folosind noul API
            with open(tmp_path, 'rb') as f:
                video_file_obj = self.client.files.upload(file=f)
            
            if progress_callback:
                progress_callback(0.5, "Procesare video...")
            
            # Așteaptă procesarea
            while video_file_obj.state == types.FileState.PROCESSING:
                time.sleep(2)
                video_file_obj = self.client.files.get(name=video_file_obj.name)
                
            if video_file_obj.state == types.FileState.FAILED:
                return None, f"❌ Procesarea video a eșuat"
            
            # Șterge fișierul temporar
            os.unlink(tmp_path)
            
            if progress_callback:
                progress_callback(0.7, "Video încărcat cu succes!")
            
            return video_file_obj, None
            
        except Exception as e:
            return None, f"❌ Eroare la încărcarea video: {str(e)}"
    
    def transcribe(self, video_file_obj, source_lang: str, target_lang: str, 
                   progress_callback=None) -> Tuple[Optional[str], Optional[str]]:
        """
        Transcrie video-ul în limba țintă.
        Returnează (transcription, None) sau (None, error_message)
        """
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                if progress_callback:
                    progress_callback(0.8, "Transcriere în curs...")
                
                # Construiește prompt-ul
                prompt = self._build_prompt(source_lang, target_lang)
                
                # Generează transcrierea folosind noul API
                response = self.client.models.generate_content(
                    model='gemini-2.0-flash-exp',
                    contents=[video_file_obj, prompt],
                    config=types.GenerateContentConfig(
                        temperature=0.3,
                        max_output_tokens=8192
                    )
                )
                
                if progress_callback:
                    progress_callback(1.0, "Transcriere completă!")
                
                return response.text, None
                
            except Exception as e:
                error_msg = str(e)
                
                # Verifică dacă trebuie să schimbe cheia
                should_retry, message = api_manager.handle_api_error(e)
                
                if should_retry:
                    retry_count += 1
                    # Reinițializează cu noua cheie
                    new_key, _ = api_manager.get_working_key()
                    if new_key:
                        self.initialize_client(new_key)
                        st.warning(message)
                        continue
                
                return None, message
        
        return None, "❌ S-au epuizat toate încercările de transcriere."
    
    def _build_prompt(self, source_lang: str, target_lang: str) -> str:
        """Construiește prompt-ul pentru transcriere"""
        
        source = self.LANGUAGES.get(source_lang, "auto-detect")
        target = self.LANGUAGES.get(target_lang, "Romanian")
        
        prompt = f"""
Analizează acest video și transcrie tot conținutul audio/vocal.

INSTRUCȚIUNI:
1. Limba sursă: {source} {'(detectează automat limba)' if source == 'auto-detect' else ''}
2. Limba țintă pentru transcriere: {target}
3. Transcrie COMPLET tot ce se vorbește în video
4. Folosește formatare clară cu timestamps dacă sunt mai mulți vorbitori
5. Indică pauzele lungi sau sunetele non-verbale relevante între [paranteze]
6. Dacă limba sursă nu este {target}, TRADUCE în {target}

FORMAT DORIT:
[00:00] - Vorbitorul/Context: Text transcris...
[00:30] - [pauză]
[00:35] - Continuare text...

Începe transcrierea:
"""
        return prompt
    
    def cleanup_uploaded_file(self, video_file_obj):
        """Șterge fișierul încărcat de pe serverele Google"""
        try:
            self.client.files.delete(name=video_file_obj.name)
        except:
            pass

# Instanță globală
transcriber = VideoTranscriber()
