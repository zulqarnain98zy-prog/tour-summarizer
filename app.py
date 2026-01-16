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
            div[data-testid="stSidebarUserContent"] { padding-top: 2rem; }
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
    
    # TONE INSTRUCTIONS MAP
    tone_instructions = {
        "Standard (Neutral)": "Use a clear, factual, and balanced tone. Informative but not emotional.",
        "Exciting (Marketing Hype)": "Use an energetic, persuasive, and 'hype' tone. Use power words like 'unforgettable', 'breathtaking', 'thrilling'. Sell the experience!",
        "Professional (Corporate)": "Use a formal, polished, and premium tone. Focus on reliability, comfort, and service quality. Avoid slang.",
        "Casual (Friendly)": "Use a warm, conversational, and inviting tone. Address the user as 'you'. Use contractions (e.g., 'You'll love' instead of 'Guests will enjoy')."
    }
    selected_tone_instruction = tone_instructions.get(tone, tone_instructions["Standard (Neutral)"])

    intro_prompt = f"""
    You are a travel product manager.
    **TASK:** Convert the tour text into strict JSON.
    **TONE INSTRUCTION:** {selected_tone_instruction}
    **CRITICAL:** Output ONLY raw JSON. No Markdown.
    
    **REQUIRED JSON STRUCTURE:**
    {{
        "basic_info": {{
            "city_country": "City, Country",
            "group_type": "Private/Join-in",
            "group_size": "Min/Max",
            "duration": "Duration",
            "main_attractions": "Attraction 1, Attraction 2",
            "highlights": ["Highlight 1", "Highlight 2", "Highlight 3", "Highlight 4"],
            "what_to_expect": "Short summary written in the requested tone",
            "selling_points": ["Tag 1", "Tag 2"]
        }},
        "start_end": {{
            "start_time": "09:00",
            "end_time": "17:00",
            "join_method": "Pickup/Meetup",
            "meet_pick_points": ["Location A"],
            "drop_off": "Location B"
        }},
        "itinerary": {{ "steps": ["Step 1", "Step 2"] }},
        "policies": {{ "cancellation": "Free cancel...", "merchant_contact": "Email/Phone" }},
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

def call_gemini_caption(image_bytes, api_key):
    model_name = get_working_model_name(api_key)
    if not model_name: return "Error: No Model"
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    prompt = "Write a captivating social media caption (10-12 words, experiential verb start, no emojis)."
    try:
        response = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": image_bytes}])
        return response.text
    except: return "Caption Failed"

# --- HELPER: RENDER COPY BOX ---
def copy_box(label, text, height=None):
    if not text: return
    st.caption(f"**{label}**")
    st.code(str(text), language="text") 

# --- UI RENDERER ---
def render_output(json_text, url_input=None):
    if json_text == "429_LIMIT":
        st.error("⏳ Quota Exceeded. Please wait 1 minute.")
        return
    if not json_text or "Error" in json_text:
        st.error(f"⚠️ {json_text}")
        return

    clean_text = json_text.strip()
    if clean_text.startswith("```json"): clean_text = clean_text[7:]
    if clean_text.endswith("```"): clean_text = clean_text[:-3]
    
    try:
        data = json.loads(clean_text)
    except:
        st.warning("⚠️ Formatting Issue. See 'Raw Response' below.")
        st.code(json_text)
        return

    # --- SIDEBAR: COPY ASSISTANT ---
    with st.sidebar:
        st.header("📋 Quick Copy Dashboard")
        st.info("Click the copy icon 📄 on the top-right of each box.")
        
        info = data.get("basic_info", {})
        inc = data.get("inclusions", {})
        pol = data.get("policies", {})
        res = data.get("restrictions", {})
        seo = data.get("seo", {})

        copy_box("📍 Departure City", info.get('city_country'))
        copy_box("🏷️ Activity Name", info.get('main_attractions'))
        
        # Highlights Formatting
        hl_list = info.get('highlights', [])
        hl_text = "\n".join([f"• {h}" for h in hl_list])
        copy_box("✨ Highlights", hl_text)
        
        copy_box("📝 Description", info.get('what_to_expect'))
        
        # Inclusions Formatting
        inc_list = inc.get('included', [])
        inc_text = "\n".join([f"• {x}" for x in inc_list])
        copy_box("✅ Included", inc_text)

        # Exclusions Formatting
        exc_list = inc.get('excluded', [])
        exc_text = "\n".join([f"• {x}" for x in exc_list])
        copy_box("❌ Excluded", exc_text)

        copy_box("👶 Child Policy", res.get('child_policy'))
        copy_box("🚫 Cancellation", pol.get('cancellation'))
        
        kw_list = seo.get('keywords', [])
        copy_box("🔍 SEO Keywords", ", ".join(kw_list))

        st.divider()
        st.caption("Scroll main page for full analysis details ->")

    # --- MAIN PAGE: 9 TABS (RESTORED) ---
    st.success("✅ Analysis Complete! Use the Sidebar 👈 to copy-paste.")
    
    tab_names = ["ℹ️ Basic Info", "⏰ Start & End", "🗺️ Itinerary", "📜 Policies", "✅ Inclusions", "🚫 Restrictions", "🔍 SEO", "💰 Price", "📊 Analysis"]
    tabs = st.tabs(tab_names)

    with tabs[0]:
        st.write(f"**📍 Location:** {info.get('city_country')}")
        st.write(f"**⏳ Duration:** {info.get('duration')}")
        st.write(f"**👥 Group:** {info.get('group_type')} ({info.get('group_size')})")
        st.divider()
        st.write("**🌟 Highlights:**")
        for h in info.get("highlights", []): st.write(f"- {h}")
        st.info(info.get("what_to_expect"))

    with tabs[1]:
        s = data.get("start_end", {})
        st.write(f"**Start:** {s.get('start_time')} | **End:** {s.get('end_time')}")
        st.write(f"**Method:** {s.get('join_method')}")

    with tabs[2]:
        steps = data.get("itinerary", {}).get("steps", [])
        for step in steps: st.write(step)

    with tabs[3]:
        st.error(f"**Cancellation Policy:** {pol.get('cancellation', '-')}")
        st.write(f"**📞 Merchant Contact:** {pol.get('merchant_contact', '-')}")

    with tabs[4]:
        c1, c2 = st.columns(2)
        with c1: 
            st.write("✅ **Included**")
            for x in inc.get("included", []): st.write(f"- {x}")
        with c2: 
            st.write("❌ **Excluded**")
            for x in inc.get("excluded", []): st.write(f"- {x}")

    with tabs[5]:
        st.write(f"**Child:** {res.get('child_policy')}")
        st.write(f"**Accessibility:** {res.get('accessibility')}")
        with st.expander("View FAQ"): st.write(res.get('faq', 'No FAQ found.'))

    with tabs[6]: st.code(str(seo.get("keywords")))
    with tabs[7]: st.write(data.get("pricing", {}).get("details"))
    
    # --- RESTORED ANALYSIS BUTTONS ---
    with tabs[8]: 
        an = data.get("analysis", {})
        search_term = an.get("ota_search_term", "")
        if not search_term: 
            search_term = info.get('main_attractions', '') # Fallback

        st.write(f"**OTA Search Term:** `{search_term}`")
        if search_term:
            encoded_term = urllib.parse.quote(search_term)
            st.markdown("### 🔎 Find Similar Products")
            c1, c2, c3 = st.columns(3)
            with c1: st.link_button("🟢 Viator", f"https://www.viator.com/searchResults/all?text={encoded_term}")
            with c2: st.link_button("🔵 GetYourGuide", f"https://www.getyourguide.com/s?q={encoded_term}")
            with c3: st.link_button("🟠 Klook", f"https://www.google.com/search?q={urllib.parse.quote('site:klook.com ' + search_term)}")
        
        if url_input:
            try:
                domain = urllib.parse.urlparse(url_input).netloc.replace("www.", "")
                merchant_name = domain.split('.')[0].capitalize()
                st.markdown("---")
                st.markdown(f"### 🏢 Merchant: **{merchant_name}**")
                st.link_button(f"🔎 Competitors", f"https://www.google.com/search?q={urllib.parse.quote('sites like ' + domain)}")
            except: pass

# --- SMART ROTATION ---
def smart_rotation_wrapper(text, keys, tone):
    if not keys: return "⚠️ No API keys found."
    random.shuffle(keys)
    max_retries = 3
    for attempt in range(max_retries):
        for key in keys:
            result = call_gemini_json_summary(text, key, tone)
            if result == "429_LIMIT":
                time.sleep(1)
                continue
            if "Error" not in result: return result
    return "⚠️ Server Busy. Try again."

# --- MAIN APP LOGIC ---
t1, t2, t3 = st.tabs(["🧠 Link Summary", "✍🏻 Text Summary", "🖼️ Photo Resizer"])

# TAB 1: LINK
with t1:
    url = st.text_input("Paste Tour Link")
    tone_link = st.selectbox("Tone", ["Standard (Neutral)", "Exciting (Marketing Hype)", "Professional (Corporate)", "Casual (Friendly)"], key="tone_link")
    
    if st.button("Generate from Link"):
        keys = get_all_keys()
        if not keys: st.error("❌ No API Keys"); st.stop()
        if not url: st.error("❌ Enter URL"); st.stop()

        with st.status("🚀 Processing...", expanded=True) as status:
            status.write("🕷️ Scraping URL...")
            text = extract_text_from_url(url)
            if not text or "ERROR" in text:
                status.update(label="❌ Scrape Failed", state="error")
                st.error(f"Scraper Error: {text}")
                st.stop()
            
            status.write(f"✅ Scraped {len(text)} chars. Calling AI ({tone_link})...")
            result = smart_rotation_wrapper(text, keys, tone_link)
            
            if "Busy" in result or "Error" in result:
                status.update(label="❌ AI Failed", state="error")
                st.error(result)
            else:
                status.update(label="✅ Complete!", state="complete")
                render_output(result, url_input=url)

# TAB 2: TEXT
with t2:
    raw_text = st.text_area("Paste Tour Text")
    tone_text = st.selectbox("Tone", ["Standard (Neutral)", "Exciting (Marketing Hype)", "Professional (Corporate)", "Casual (Friendly)"], key="tone_text")
    
    if st.button("Generate from Text"):
        keys = get_all_keys()
        if not keys: st.error("❌ No Keys"); st.stop()
        if len(raw_text) < 50: st.error("❌ Text too short"); st.stop()
        
        st.info(f"🚀 Processing with {tone_text} tone...")
        result = smart_rotation_wrapper(raw_text, keys, tone_text)
        render_output(result)

# TAB 3: PHOTOS (RESTORED)
with t3:
    st.info("Upload photos to resize to **8:5 (1280x800)**")
    enable_captions = st.checkbox("☑️ Generate AI Captions", value=True)
    c_align = st.selectbox("Crop Focus", ["Center", "Top", "Bottom", "Left", "Right"])
    align_map = {"Center":(0.5,0.5), "Top":(0.5,0.0), "Bottom":(0.5,1.0), "Left":(0.0,0.5), "Right":(1.0,0.5)}
    
    files = st.file_uploader("Upload", accept_multiple_files=True, type=['jpg','png','jpeg'])
    
    if files:
        keys = get_all_keys()
        if st.button("Process Images"):
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                prog_bar = st.progress(0)
                total_files = len(files)
                for i, f in enumerate(files):
                    prog_bar.progress((i + 1) / total_files)
                    b_img, err = resize_image_klook_standard(f, align_map[c_align])
                    if b_img:
                        zf.writestr(f"resized_{f.name}", b_img)
                        c1, c2 = st.columns([1,3])
                        c1.image(b_img, width=150)
                        
                        caption = "AI Disabled"
                        if enable_captions and keys:
                            caption = call_gemini_caption(b_img, random.choice(keys))
                        
                        c2.text_area(f"Caption: {f.name}", value=caption, height=70)
            
            st.success("✅ Done!")
            st.download_button("⬇️ Download ZIP", zip_buf.getvalue(), "images.zip", "application/zip")
