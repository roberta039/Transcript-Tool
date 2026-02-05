import streamlit as st
import google.generativeai as genai
from typing import Tuple, Optional
import database as db

class APIKeyManager:
    """Gestionează cheile API Gemini cu rotație automată"""
    
    # Erori care indică expirarea/invalidarea cheii
    EXPIRY_ERRORS = [
        "API_KEY_INVALID",
        "QUOTA_EXCEEDED", 
        "PERMISSION_DENIED",
        "API key expired",
        "API key not valid",
        "quota",
        "billing",
        "exceeded"
    ]
    
    def __init__(self):
        self.current_key = None
        self.current_key_index = 0
        self._load_keys_from_secrets()
    
    def _load_keys_from_secrets(self):
        """Încarcă cheile din Streamlit secrets"""
        try:
            if "GEMINI_API_KEYS" in st.secrets:
                keys = st.secrets["GEMINI_API_KEYS"]
                if isinstance(keys, list):
                    for key in keys:
                        db.add_api_key(key)
                elif isinstance(keys, str):
                    for key in keys.split(","):
                        db.add_api_key(key.strip())
            
            # Cheie singulară
            if "GEMINI_API_KEY" in st.secrets:
                db.add_api_key(st.secrets["GEMINI_API_KEY"])
                
        except Exception as e:
            pass  # Nu există secrets configurate
    
    def get_available_keys(self) -> list:
        """Returnează lista de chei disponibile"""
        return db.get_active_api_keys()
    
    def get_all_keys_status(self) -> list:
        """Returnează toate cheile cu statusul lor"""
        return db.get_all_api_keys()
    
    def add_user_key(self, api_key: str) -> bool:
        """Adaugă o cheie de la utilizator"""
        if api_key and len(api_key) > 10:
            db.add_api_key(api_key)
            return True
        return False
    
    def is_expiry_error(self, error_message: str) -> bool:
        """Verifică dacă eroarea indică expirarea cheii"""
        error_lower = str(error_message).lower()
        return any(err.lower() in error_lower for err in self.EXPIRY_ERRORS)
    
    def get_working_key(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Încearcă să găsească o cheie funcțională.
        Returnează (cheie, None) dacă găsește una funcțională
        Returnează (None, mesaj_eroare) dacă nu găsește
        """
        keys = self.get_available_keys()
        
        if not keys:
            return None, "❌ Nu există chei API disponibile. Adăugați o cheie în câmpul de mai jos."
        
        errors = []
        for key in keys:
            try:
                # Testează cheia
                genai.configure(api_key=key)
                model = genai.GenerativeModel('gemini-1.5-flash')
                
                # Test simplu
                response = model.generate_content("Test. Răspunde doar cu 'OK'.")
                
                if response:
                    self.current_key = key
                    db.mark_key_active(key)
                    return key, None
                    
            except Exception as e:
                error_msg = str(e)
                errors.append(f"Cheie {key[:10]}...: {error_msg[:50]}")
                
                if self.is_expiry_error(error_msg):
                    db.mark_key_expired(key, error_msg)
                    
        return None, f"❌ Toate cheile au eșuat:\n" + "\n".join(errors)
    
    def configure_genai(self, api_key: str):
        """Configurează biblioteca genai cu cheia specificată"""
        genai.configure(api_key=api_key)
        self.current_key = api_key
    
    def handle_api_error(self, error: Exception) -> Tuple[bool, str]:
        """
        Gestionează o eroare API.
        Returnează (should_retry, message)
        """
        error_msg = str(error)
        
        if self.is_expiry_error(error_msg):
            if self.current_key:
                db.mark_key_expired(self.current_key, error_msg)
            
            # Încearcă următoarea cheie
            new_key, error = self.get_working_key()
            if new_key:
                return True, f"⚠️ Cheia anterioară a expirat. S-a schimbat la o cheie nouă."
            else:
                return False, error
        
        return False, f"❌ Eroare API: {error_msg}"

# Instanță globală
api_manager = APIKeyManager()
