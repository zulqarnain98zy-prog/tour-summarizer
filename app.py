import streamlit as st
import cloudscraper
import time
import random
import re
import urllib.parse
import json
from bs4 import BeautifulSoup
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, NotFound
from datetime import datetime
import sys
import io
import zipfile

# --- TRY IMPORTING LIBRARIES ---
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from docx import Document
except ImportError:
    Document = None

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Klook Western Magic Tool", page_icon="⭐", layout="wide")

# --- HIDE STREAMLIT BRANDING ---
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

st.title("⭐ Klook Western Magic Tool")
st.markdown("Use Magic Tool to generate summaries, analysis, or resize photos in seconds!")

# --- LOAD ALL KEYS ---
def get_all_keys():
    if "GEMINI_KEYS" in st.secrets:
        return st.secrets["GEMINI_KEYS"]
    elif "GEMINI_API_KEY" in st.secrets:
        return [st.secrets["GEMINI_API_KEY"]]
    else:
        return []

# --- FILE EXTRACTION LOGIC ---
def extract_text_from_file(uploaded_file):
    try:
        file_type = uploaded_file.type
        if "pdf" in file_type:
            if PdfReader is None: return "⚠️ Error: 'pypdf' missing."
            reader = PdfReader(uploaded_file)
            text = ""
            for page in reader.pages: text += page.extract_text() + "\n"
            return text
        elif "wordprocessingml" in file_type or "docx" in uploaded_file.name:
            if Document is None: return "⚠️ Error: 'python-docx' missing."
            doc = Document(uploaded_file)
            return "\n".join([para.text for para in doc.paragraphs])
        else:
            return uploaded_file.getvalue().decode("utf-8")
    except Exception as e:
        return f"⚠️ Error: {e}"

# --- IMAGE RESIZING LOGIC (8:5) ---
def resize_image_klook_standard(uploaded_file):
    """Resizes and crops an image to 8:5 ratio (1280x800 target)."""
    if Image is None:
        return None, "⚠️ Error: 'Pillow' library missing."
    
    try:
        img = Image.open(uploaded_file)
        
        # Define target size (8:5 ratio)
        target_width = 1280
        target_height = 800
        
        # 1. Resize/Crop to Fill 1280x800
        img_resized = ImageOps.fit(img, (target_width, target_height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        
        # 2. Save to buffer
        buf = io.BytesIO()
        img_format = img.format if img.format else 'JPEG'
        # Convert RGBA to RGB if saving as JPEG
        if img_resized.mode == 'RGBA' and img_format == 'JPEG':
            img_resized = img_resized.convert('RGB')
            
        img_resized.save(buf, format=img_format, quality=90)
        byte_im = buf.getvalue()
        
        return byte_im, None
    except Exception as e:
        return None, f"Error processing image: {e}"

# --- CACHING & SCRAPING ---
@st.cache_data(ttl=86400, show_spinner=False)
def extract_text_from_url(url):
    try:
        scraper = cloudscraper.create_scraper(browser='chrome')
        response = scraper.get(url, timeout=15)
        if response.status_code == 403: return "403"
        if response.status_code != 200: return None
        soup = BeautifulSoup(response.content, 'html.parser')
        
        for script in soup(["script", "style", "nav", "footer", "iframe", "svg", "button", "noscript"]):
            script.extract()
        for details in soup.find_all('details'):
            details.append(soup.new_string('\n')) 
        for tag in soup.find_all(['div', 'section', 'li']):
            cls = " ".join(tag.get('class', [])) if tag.get('class') else ""
            ids = tag.get('id', "")
            if any(x in (cls + ids).lower() for x in ['faq', 'accordion', 'answer', 'content', 'panel', 'collapse']):
                tag.append(soup.new_string('\n'))
            
        text = soup.get_text(separator='\n')
        lines = (line.strip() for line in text.splitlines())
        clean_lines = [line for line in lines if line]
        final_text = '\n'.join(clean_lines)
        return final_text[:35000]
    except Exception:
        return "ERROR"

# --- MODEL FINDER ---
def get_valid_model(api_key):
    try:
        genai.configure(api_key=api_key)
        models = genai.list_models()
        available_names = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        priority = ['models/gemini-1.5-flash', 'models/gemini-1.5-flash-latest', 'models/gemini-1.5-pro']
        for m in priority:
            if m in available_names: return m
        return available_names[0] if available_names else None
    except Exception:
        return None

# --- GENERATION FUNCTIONS ---

def call_gemini_json_summary(text, api_key):
    model_name = get_valid_model(api_key)
    if not model_name: raise ValueError("No model.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
    
    tag_list = """
    Interactive, Romantic, Customizable, Guided, Private, Skip-the-line, Small Group, VIP, All Inclusive, 
    Architecture, Canal, Cultural, Historical, Movie, Museum, Music, Religious Site, Pilgrimage, Spiritual, Temple, UNESCO site, Local Village, Old Town, 
    TV, Movie and TV, Heritage, Downtown, City Highlights, Downtown Highlights, 
    Alpine Route, Coral Reef, Desert, Glacier, Mangrove, Marine Life, Mountain, Rainforest, Safari, Sand Dune, Volcano, Waterfall, River,
