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
import streamlit.components.v1 as components  # Explicit import for components

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
    
    # --- FIXED CLEAN FUNCTION (Prevents Syntax Errors) ---
    def clean(s):
        text = str(s)
        text = text.replace('"', '&quot;')  # Escape double quotes
        text = text.replace("'", "&#39;")   # Escape single quotes
        text = text.replace("\n", " ")      # Remove newlines
        return text
    
    city = clean(info.get('city_country', ''))
    name = clean(info.get('main_attractions', ''))
    desc = clean(info.get('what_to_expect', ''))
    
    # Highlights formatting
    hl_raw = info.get('highlights', [])
    highlights = "\\n".join([f"• {h}" for h in hl_raw])
    highlights = clean(highlights)

    # Inclusions formatting
    inc_raw = inc.get('included', [])
    inclusions = "\\n".join([f"• {x}" for x in inc_raw])
    inclusions = clean(inclusions)

    html_code = f"""
    <div id="floating-helper" style="
        position: fixed; bottom: 20px; right: 20px; width: 320px;
        background: white; border-radius: 12px; box-shadow: 0 5px 25px rgba(0,0,0,0.3);
        z-index: 999999; font-family: sans-serif; border: 2px solid #ff5722;
        max-height: 80vh; display: flex; flex-direction: column; overflow: hidden;
    ">
        <div style="background: #ff5722; color: white; padding: 12px; font-weight: bold; display: flex; justify-content: space-between; align-items: center; cursor: move;">
            <span>🪄 Magic Float</span>
            <button onclick="document.getElementById('floating-helper').remove()" style="background:none; border:none; color:white; font-size:18px; cursor:pointer;">&times;</button>
        </div>
        <div style="padding: 10px; overflow-y: auto; flex: 1;">
            
            <div style="margin-bottom:10px;">
                <div style="font-size:10px; color:#666; font-weight:bold; margin-bottom:2px;">CITY</div>
                <div onclick="navigator.clipboard.writeText('{city}')" style="background:#f5f5f5; padding:8px; border-radius:4px; font-size:12px; cursor:pointer; border:1px solid #ddd; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="{city}">
                    {city} 📋
                </div>
            </div>

            <div style="margin-bottom:10px;">
                <div style="font-size:10px; color:#666; font-weight:bold; margin-bottom:2px;">NAME</div>
                <div onclick="navigator.clipboard.writeText('{name}')" style="background:#f5f5f5; padding:8px; border-radius:4px; font-size:12px; cursor:pointer; border:1px solid #ddd; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="{name}">
                    {name} 📋
                </div>
            </div>

            <div style="margin-bottom:10px;">
                <div style="font-size:10px; color:#666; font-weight:bold; margin-bottom:2px;">HIGHLIGHTS</div>
                <div onclick="navigator.clipboard.writeText('{highlights}')" style="background:#f5f5f5; padding:8px; border-radius:4px; font-size:12px; cursor:pointer; border:1px solid #ddd; white-space:pre-wrap; max-height:80px; overflow-y:auto;" title="Click to Copy">
                    {highlights} 📋
                </div>
            </div>
            
            <div style="margin-bottom:10px;">
                <div style="font-size:10px; color:#666; font-weight:bold; margin-bottom:2px;">DESCRIPTION</div>
                <div onclick="navigator.clipboard.writeText('{desc}')" style="background:#f5f5f5; padding:8px; border-radius:4px; font-size:12px; cursor:pointer; border:1px solid #ddd; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                    Click to Copy Description 📋
                </div>
            </div>
            
             <div style="margin-bottom:10px;">
                <div style="font-size:10px; color:#666; font-weight:bold; margin-bottom:2px;">INCLUDED</div>
                <div onclick="navigator.clipboard.writeText('{inclusions}')" style="background:#f5f5f5; padding:8px; border-radius:4px; font-size:12px; cursor:pointer; border:1px solid #ddd; white-space:pre-wrap; max-height:60px; overflow-y:auto;">
                    {inclusions} 📋
                </div>
            </div>

        </div>
        <div style="background:#eee; padding:5px; text-align:center; font-size:10px; color:#888;">
            Click boxes to Copy
        </div>
    </div>
    """
    components.html(html_code, height=0)

# --- UI RENDERER ---
def render_output(json_text):
    if json_text == "429_LIMIT":
        st.error("⏳ Quota Exceeded."); return
    if not json_text or "Error" in json_text:
        st.error(f"⚠️ {json_text}"); return

    clean_text = json_text.strip()
    if clean_text.startswith("```json"): clean_text = clean_text[7:]
    if clean_text.endswith("```"): clean_text = clean_text[:-3]
    
    try:
        data = json.loads(clean_text)
    except:
        st.warning("⚠️ Formatting Issue.")
        return

    # --- LAUNCH FLOATING WINDOW BUTTON ---
    if st.button("🚀 Launch Floating Window"):
        render_floating_window(data)
        st.toast("Floating Window Active! Look at bottom-right.", icon="🎈")

    # --- STANDARD TABS ---
    info = data.get("basic_info", {})
    st.success(f"✅ Generated: {info.get('main_attractions')}")
    
    t1, t2, t3, t4, t5 = st.tabs(["Overview", "Itinerary", "Policies", "Inclusions", "SEO"])
    
    with t1:
        st.code(info.get('city_country'), language="text")
        st.code(info.get('main_attractions'), language="text")
        hl_text = "\n".join([f"• {h}" for h in info.get('highlights', [])])
        st.text_area("Highlights", value=hl_text, height=150)
        st.text_area("Description", value=info.get('what_to_expect'), height=150)

    with t2:
        steps = data.get("itinerary", {}).get("steps", [])
        st.write(steps)

    with t3:
        st.write(data.get("policies", {}))

    with t4:
        inc = data.get("inclusions", {})
        c1, c2 = st.columns(2)
        with c1: st.write("✅ Included", inc.get("included"))
        with c2: st.write("❌ Excluded", inc.get("excluded"))
        
    with t5:
        st.code(", ".join(data.get("seo", {}).get("keywords", [])), language="text")

# --- SMART ROTATION ---
def smart_rotation_wrapper(text, keys, tone):
    if not keys: return "⚠️ No API keys found."
    random.shuffle(keys)
    for key in keys:
        result = call_gemini_json_summary(text, key, tone)
        if "Error" not in result: return result
    return "⚠️ Server Busy."

# --- MAIN APP LOGIC ---
t1, t2 = st.tabs(["Link Summary", "Text Summary"])

with t1:
    url = st.text_input("Paste Tour Link")
    tone_link = st.selectbox("Tone", ["Standard (Neutral)", "Exciting (Marketing Hype)", "Professional (Corporate)"], key="t1")
    if st.button("Generate from Link"):
        keys = get_all_keys()
        if keys and url:
            text = extract_text_from_url(url)
            result = smart_rotation_wrapper(text, keys, tone_link)
            render_output(result)

with t2:
    raw = st.text_area("Paste Text")
    tone_text = st.selectbox("Tone", ["Standard (Neutral)", "Exciting (Marketing Hype)", "Professional (Corporate)"], key="t2")
    if st.button("Generate from Text"):
        keys = get_all_keys()
        if keys and len(raw) > 50:
            result = smart_rotation_wrapper(raw, keys, tone_text)
            render_output(result)
