import streamlit as st
import cloudscraper
import time
import random
import re
import urllib.parse
import json
from bs4 import BeautifulSoup
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, NotFound, InvalidArgument
from datetime import datetime
import sys
import io
import zipfile

# --- TRY IMPORTING IMAGE LIBRARY ---
try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Klook Magic Tool", page_icon="⭐", layout="wide")

# --- HIDE STREAMLIT BRANDING ---
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .stCodeBlock { margin-bottom: 0px !important; }
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

st.title("⭐ Klook Western Magic Tool")

# --- LOAD KEYS ---
def get_all_keys():
    if "GEMINI_KEYS" in st.secrets:
        return st.secrets["GEMINI_KEYS"]
    elif "GEMINI_API_KEY" in st.secrets:
        return [st.secrets["GEMINI_API_KEY"]]
    else:
        return []

# --- IMAGE RESIZING LOGIC ---
def resize_image_klook_standard(uploaded_file, alignment=(0.5, 0.5)):
    if Image is None: return None, "⚠️ Error: 'Pillow' library missing."
    try:
        img = Image.open(uploaded_file)
        target_width = 1280
        target_height = 800
        img_resized = ImageOps.fit(img, (target_width, target_height), method=Image.Resampling.LANCZOS, centering=alignment)
        buf = io.BytesIO()
        img_format = img.format if img.format else 'JPEG'
        if img_resized.mode == 'RGBA' and img_format == 'JPEG':
            img_resized = img_resized.convert('RGB')
        img_resized.save(buf, format=img_format, quality=90)
        return buf.getvalue(), None
    except Exception as e:
        return None, f"Error processing image: {e}"

# --- SCRAPER ---
@st.cache_data(ttl=86400, show_spinner=False)
def extract_text_from_url(url):
    try:
        scraper = cloudscraper.create_scraper(browser='chrome')
        response = scraper.get(url, timeout=20)
        if response.status_code != 200: return f"ERROR: Status Code {response.status_code}"
        soup = BeautifulSoup(response.content, 'html.parser')
        for script in soup(["script", "style", "nav", "footer", "iframe", "svg", "button", "noscript"]): script.extract()
        text = soup.get_text(separator='\n')
        lines = (line.strip() for line in text.splitlines())
        return '\n'.join(line for line in lines if line)[:30000]
    except Exception as e: return f"ERROR: {str(e)}"

# --- SMART MODEL FINDER ---
def get_working_model_name(api_key):
    genai.configure(api_key=api_key)
    try:
        models = genai.list_models()
        available_models = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        priority_list = ["gemini-1.5-flash", "gemini-1.5-flash-latest", "gemini-1.5-pro"]
        for pref in priority_list:
            for model in available_models:
                if pref in model: return model
        return available_models[0] if available_models else None
    except: return "models/gemini-1.5-flash"

def sanitize_text(text):
    if not text: return ""
    text = text.encode('utf-8', 'ignore').decode('utf-8')
    return text.replace("\\", "\\\\")[:25000]

# --- GEMINI CALLS ---
def call_gemini_json_summary(text, api_key, tone="Standard"):
    model_name = get_working_model_name(api_key)
    if not model_name: return "Error: No available Gemini models found."
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
    
    # TONE MAP
    tone_instructions = {
        "Standard (Neutral)": "Use a clear, factual, and balanced tone.",
        "Exciting (Marketing Hype)": "Use an energetic, persuasive tone. Use power words.",
        "Professional (Corporate)": "Use a formal, polished, and premium tone.",
        "Casual (Friendly)": "Use a warm, conversational tone. Address the user as 'you'."
    }
    tone_instr = tone_instructions.get(tone, tone_instructions["Standard (Neutral)"])

    intro_prompt = f"""
    You are a travel product manager.
    **TASK:** Convert text to JSON.
    **TONE:** {tone_instr}
    **CRITICAL:** Output ONLY raw JSON.
    
    **REQUIRED JSON STRUCTURE:**
    {{
        "basic_info": {{
            "city_country": "City, Country",
            "group_type": "Private/Join-in",
            "group_size": "Min/Max",
            "duration": "Duration",
            "main_attractions": "Attraction 1, Attraction 2",
            "highlights": ["Highlight 1", "Highlight 2"],
            "what_to_expect": "Short summary",
            "selling_points": ["Tag 1", "Tag 2"]
        }},
        "start_end": {{ "start_time": "09:00", "end_time": "17:00", "join_method": "Pickup/Meetup" }},
        "itinerary": {{ "steps": ["Step 1", "Step 2"] }},
        "policies": {{ "cancellation": "Free cancel...", "merchant_contact": "Contact Info" }},
        "inclusions": {{ "included": ["Item A"], "excluded": ["Item B"] }},
        "restrictions": {{ "child_policy": "Details", "accessibility": "Details", "faq": "Details" }},
        "seo": {{ "keywords": ["Key 1", "Key 2"] }},
        "pricing": {{ "details": "Price info" }},
        "analysis": {{ "ota_search_term": "Product Name" }}
    }}
    **INPUT TEXT:**
    """
    try:
        response = model.generate_content(intro_prompt + sanitize_text(text))
        return response.text
    except ResourceExhausted: return "429_LIMIT"
    except Exception as e: return f"AI Error: {str(e)}"

# --- FLOATING WINDOW INJECTOR (THE MAGIC) ---
def render_floating_window(data):
    info = data.get("basic_info", {})
    inc = data.get("inclusions", {})
    pol = data.get("policies", {})
    
    # Prepare text for JS (escape quotes)
    def clean(s): return str(s).replace('
