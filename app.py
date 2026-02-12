import streamlit as st
import cloudscraper
import time
import random
import re
import urllib.parse
import json
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, NotFound, InvalidArgument
from datetime import datetime
import sys
import io
import zipfile
import ssl
import unicodedata
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

# --- NEW IMPORT FOR MERCHANT VALIDATION ---
try:
    import whois
    HAS_WHOIS = True
except ImportError:
    HAS_WHOIS = False

# --- TRY IMPORTING LIBRARIES ---
try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

# --- PDF LIBRARY LOADER ---
HAS_PYPDF = False
HAS_PDFPLUMBER = False

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    pass

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    pass

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Klook Magic Tool", page_icon="⭐", layout="wide")

# --- HIDE STREAMLIT BRANDING ---
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            .stCodeBlock { margin-bottom: 0px !important; }
            div[data-testid="stSidebarUserContent"] { padding-top: 2rem; }
            .timeline-step {
                padding: 10px; margin-bottom: 10px; border-left: 3px solid #ff5722;
                background-color: #f8f9fa; border-radius: 0 5px 5px 0;
            }
            .timeline-time { font-weight: bold; color: #555; font-size: 0.9rem; }
            .timeline-title { font-weight: bold; font-size: 1rem; color: #333; }
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

st.title("⭐ Klook Western Magic Tool")

# --- SESSION STATE INITIALIZATION ---
if 'gen_result' not in st.session_state:
    st.session_state['gen_result'] = None
if 'url_input' not in st.session_state:
    st.session_state['url_input'] = None
if 'scraped_images' not in st.session_state:
    st.session_state['scraped_images'] = []
if 'product_context' not in st.session_state:
    st.session_state['product_context'] = ""
if 'raw_text_content' not in st.session_state:
    st.session_state['raw_text_content'] = ""
if 'merchant_result' not in st.session_state:
    st.session_state['merchant_result'] = None

# --- LOAD KEYS ---
def get_all_keys():
    if "GEMINI_KEYS" in st.secrets:
        return st.secrets["GEMINI_KEYS"]
    elif "GEMINI_API_KEY" in st.secrets:
        return [st.secrets["GEMINI_API_KEY"]]
    return []

# --- MERCHANT CATEGORY OPTIONS ---
MERCHANT_CAT_OPTIONS = """
Farms, Cable Car & Gondola & Skywheel, Aquariums, Hop On Hop Off Bus, Zoos & Animal Parks, Museums & Galleries, Gardens & Parks, Observation Decks & Towers, Cathedral & Churches, Playgrounds, Castles & Palaces, Ancient Ruins, Temples & Shrines, Natural Landscape, Villages, Attractions Pass, Hiking & Trekking Tour, Multiday Tour, Shore Excursion, Walking Tour, Kayaking Tour, Outlet tours, ATV & All Wheel Drive Tour, Ski tour, Food & Drinks Tour, Air Tour, Bicycle Tours, Motorcycle & Scooter & Segway, Bus Tour, Car Tour, Railway Tour, Cruise Tour, Boat Tours, Camping & Glamping, Dining Experiences, Kayaking, Canyoning, Wellness & Health, Fitness & Sports, Surfing, Party Room, Other Water Sports, Other Aerial Activities, Biking & Segway & Scooter, Boats & Yachts & Catamarans, Gliding, PADI Diving, Cooking Classes, Go Karting & Racing, COVID Test, Sightseeing Cruise, Skydiving, Golf, Photography, Lessons & Workshops, Costume & Attire, Beverage Tastings, Nightlife & Pub Crawls, Hot Spring, Rafting, Animal Watching & Interaction, Diving & Snorkeling, Fishing & Catching, Zip-line, Climbing, Indoor Games, Paddleboading, Hot Air Ballon, Flight & Helicopter, Skiing & Snow Sports, Bungee, ATV & All Wheel Drive, Beach/Resort Pass
"""

# --- IMPROVED MERCHANT RISK LOGIC ---
def validate_merchant_risk(text, url, api_key):
    model_name = get_working_model_name(api_key)
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
    
    scraped_content = text
    inferred_name = ""
    
    if url:
        try:
            scraper = cloudscraper.create_scraper()
            base_res = scraper.get(url, timeout=12)
            soup = BeautifulSoup(base_res.content, 'html.parser')
            title = soup.find('title')
            inferred_name = title.get_text().split('|')[0].split('-')[0].strip() if title else url.split('.')[1].capitalize()

            if not text:
                target_url = url
                for link in soup.find_all('a', href=True):
                    if any(w in link['href'].lower() for w in ['about', 'company', 'story', 'legal', 'terms']):
                        target_url = urllib.parse.urljoin(url, link['href'])
                        break
                final_res = scraper.get(target_url, timeout=12)
                final_soup = BeautifulSoup(final_res.content, 'html.parser')
                for s in final_soup(["script", "style"]): s.extract()
                scraped_content = final_soup.get_text(separator=' ')[:15000]
        except: pass

    domain_years = "Unknown"
    if HAS_WHOIS and url:
        try:
            domain_name = urllib.parse.urlparse(url).netloc
            w = whois.whois(domain_name)
            c_date = w.creation_date[0] if isinstance(w.creation_date, list) else w.creation_date
            domain_years = (datetime.now() - c_date).days // 365
        except: pass

    prompt = f"""
    Analyze this merchant for Klook/GYG onboarding.
    URL: {url}
    CONTENT: {scraped_content[:10000]}
    
    TASK:
    1. Identify ALL applicable categories from this list: {MERCHANT_CAT_OPTIONS}
    2. Identify specific RED FLAGS and STRENGTHS (Green Flags).
    3. Return a legitimacy score and recommendation.
    
    Return JSON:
    {{
        "merchant_name": "Extracted Name",
        "legitimacy_score": 1-100,
        "categories_found": ["Cat 1"],
        "red_flags": ["Detail 1"],
        "strengths": ["Detail 1"],
        "recommendation": "Approve/Reject/Waitlist",
        "summary": "Overview"
    }}
    """
    try:
        response = model.generate_content(prompt)
        res_data = json.loads(response.text)
        res_data["domain_age"] = domain_years
        if not res_data.get("merchant_name"): res_data["merchant_name"] = inferred_name
        return res_data
    except: return {"error": "AI Audit Failed", "merchant_name": inferred_name}

def get_working_model_name(api_key):
    genai.configure(api_key=api_key)
    try:
        models = genai.list_models()
        available = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        for pref in ["gemini-1.5-flash", "gemini-1.5-pro"]:
            for m in available:
                if pref in m: return m
        return available[0]
    except: return "models/gemini-1.5-flash"

# --- TABS DEFINITION ---
t1, t2, t3, t4, t5, t6 = st.tabs(["🧠 Link Summary", "✍🏻 Text Summary", "📄 PDF Summary", "🖼️ Photo Resizer", "✍️ Grammar & Word Count", "🛡️ Merchant Validator"])

# (T1-T4 logic remains the same as your original code)

# --- NEW TAB 5: GRAMMAR & WORD COUNT ---
with t5:
    st.header("✍️ American English Grammar Checker")
    gram_text = st.text_area("Paste Text to Check:", height=200, key="gram_input")
    if st.button("✨ Check & Fix"):
        keys = get_all_keys()
        if gram_text and keys:
            with st.spinner("Fixing..."):
                model = genai.GenerativeModel(get_working_model_name(random.choice(keys)))
                prompt = f"Fix grammar and spelling in AMERICAN ENGLISH. Professional travel tone. Only return corrected text.\n\nTEXT: {gram_text}"
                resp = model.generate_content(prompt)
                fixed = resp.text.strip()
                st.divider()
                st.subheader("✅ Corrected Text")
                w_count = len(fixed.split())
                c_count = len(fixed)
                c1, c2 = st.columns(2)
                c1.metric("Word Count", w_count)
                c2.metric("Char Count", c_count)
                st.code(fixed, language="text")

# --- NEW TAB 6: MERCHANT VALIDATOR ---
with t6:
    st.header("🛡️ Merchant Risk Assessment")
    m_url = st.text_input("Merchant Website URL", key="m_url")
    m_text = st.text_area("About Us / Business Text (Optional)", key="m_text")
    
    if st.button("🔍 Run Risk Audit"):
        keys = get_all_keys()
        if keys:
            with st.status("🕵️ Auditing...", expanded=True) as status:
                risk_res = validate_merchant_risk(m_text, m_url, random.choice(keys))
                st.session_state['merchant_result'] = risk_res
                status.update(label="✅ Complete!", state="complete")

    if st.session_state['merchant_result']:
        res = st.session_state['merchant_result']
        m_name = res.get('merchant_name', 'Merchant')
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            st.metric("Legitimacy Score", f"{res.get('legitimacy_score', 0)}/100")
            st.write(f"**Merchant:** {m_name}")
            st.write(f"**Domain Age:** {res.get('domain_age', 'Unknown')} years")
        with col2:
            st.write("🧩 **Categories Detected**")
            for c in res.get('categories_found', []): st.caption(f"✅ {c}")
        with col3:
            st.write("🌐 **OTA Search (Google)**")
            q = urllib.parse.quote(f'"{m_name}"')
            st.link_button("🔵 Find on GYG", f"https://www.google.com/search?q={q}+GetYourGuide")
            st.link_button("🟢 Find on Viator", f"https://www.google.com/search?q={q}+Viator")
        st.divider()
        st.write(f"**AI Verdict:** {res.get('summary', '')}")
        col_flags, col_strengths = st.columns(2)
        with col_flags:
            st.markdown("### 🚩 Red Flags")
            for f in res.get('red_flags', []): st.error(f)
        with col_strengths:
            st.markdown("### ✅ Strengths")
            for s in res.get('strengths', []): st.success(s)

if st.session_state['gen_result']:
    # Assuming render_output is defined in your full script
    pass
