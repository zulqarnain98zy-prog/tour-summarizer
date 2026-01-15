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
st.markdown("Use Magic Tool to generate summaries or resize photos in seconds!")

# --- LOAD ALL KEYS ---
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
        
        if response.status_code != 200:
            return f"ERROR: Status Code {response.status_code}"
            
        soup = BeautifulSoup(response.content, 'html.parser')
        for script in soup(["script", "style", "nav", "footer", "iframe", "svg", "button", "noscript"]):
            script.extract()
            
        text = soup.get_text(separator='\n')
        lines = (line.strip() for line in text.splitlines())
        clean_text = '\n'.join(line for line in lines if line)
        return clean_text[:30000]
    except Exception as e:
        return f"ERROR: {str(e)}"

# --- SMART MODEL FINDER ---
def get_working_model_name(api_key):
    genai.configure(api_key=api_key)
    try:
        models = genai.list_models()
        available_models = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        
        # Priority: Flash -> Flash-8b -> Pro
        priority_list = [
            "gemini-1.5-flash",
            "gemini-1.5-flash-latest",
            "gemini-1.5-flash-001",
            "gemini-1.5-pro",
        ]
        
        for pref in priority_list:
            for model in available_models:
                if pref in model:
                    return model
        return available_models[0] if available_models else None
    except Exception:
        return "models/gemini-1.5-flash"

# --- TEXT SANITIZER ---
def sanitize_text(text):
    if not text: return ""
    text = text.encode('utf-8', 'ignore').decode('utf-8')
    text = text.replace("\\", "\\\\")
    return text[:25000]

# --- GENERATION FUNCTIONS ---

def call_gemini_json_summary(text, api_key):
    model_name = get_working_model_name(api_key)
    if not model_name: return "Error: No available Gemini models found."
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
    
    tag_list = "Interactive, Romantic, Guided, Private, Skip-the-line, Small Group, VIP, Architecture, Cultural, Historical, Museum, Nature, Wildlife, Food, Hiking, Boat, Cruise, Night, Shopping, Sightseeing"
    
    intro_prompt = """
    You are a travel product manager.
    **TASK:** Convert the tour text into strict JSON.
    **CRITICAL:** Output ONLY raw JSON. No Markdown.
    
    **REQUIRED JSON STRUCTURE:**
    {
        "basic_info": {
            "city_country": "City, Country",
            "group_type": "Private/Join-in",
            "group_size": "Min/Max",
            "duration": "Duration",
            "main_attractions": "Attraction 1, Attraction 2",
            "highlights": ["Highlight 1", "Highlight 2", "Highlight 3", "Highlight 4"],
            "what_to_expect": "Short summary",
            "selling_points": ["Tag 1", "Tag 2"]
        },
        "start_end": {
            "start_time": "09:00",
            "end_time": "17:00",
            "join_method": "Pickup/Meetup",
            "meet_pick_points": ["Location A"],
            "drop_off": "Location B"
        },
        "itinerary": { "steps": ["Step 1", "Step 2"] },
        "policies": { "cancellation": "Free cancel...", "merchant_contact": "Email/Phone" },
        "inclusions": { "included": ["Item A"], "excluded": ["Item B"] },
        "restrictions": { "child_policy": "Details", "accessibility": "Details", "faq": "Details" },
        "seo": { "keywords": ["Key 1", "Key 2"] },
        "pricing": { "details": "Price info" },
        "analysis": { "ota_search_term": "Product Name" }
    }

    **INPUT TEXT:**
    """
    
    clean_input = sanitize_text(text)
    final_prompt = intro_prompt + clean_input
    
    try:
        response = model.generate_content(final_prompt)
        return response.text
    except ResourceExhausted:
        return "429_LIMIT"
    except Exception as e:
        return f"AI Error: {str(e)}"

def call_gemini_caption(image_bytes, api_key):
    model_name = get_working_model_name(api_key)
    if not model_name: return "Error: No Model"
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    prompt = "Write a captivating social media caption (10-12 words, experiential verb start, no emojis)."
    try:
        response = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": image_bytes}])
        return response.text
    except ResourceExhausted:
        return "Caption skipped (Rate Limit)"
    except:
        return "Caption failed."

# --- UI RENDERER ---
def render_output(json_text, url_input=None):
    # FORCE DISPLAY OF RAW TEXT (DEBUGGING)
    st.info("✅ Raw Response Received from AI:")
    st.code(json_text) 

    if json_text == "429_LIMIT":
        st.error("⏳ Quota Exceeded. Please wait 1 minute or check API usage.")
        return

    if not json_text or "Error" in json_text:
        st.error(f"⚠️ {json_text}")
        return

    clean_text = json_text.strip()
    if clean_text.startswith("```json"): clean_text = clean_text[7:]
    if clean_text.endswith("```"): clean_text = clean_text[:-3]
    clean_text = clean_text.strip()
    
    try:
        data = json.loads(clean_text)
    except:
        st.warning("⚠️ Formatting Issue. The AI output wasn't valid JSON. See 'Raw Response' above.")
        return

    # --- RENDER TABS ---
    tab_names = [
        "ℹ️ Basic Info", "⏰ Start & End", "🗺️ Itinerary", 
        "📜 Policies", "✅ Inclusions", "🚫 Restrictions", "🔍 SEO", 
        "💰 Price", "📊 Analysis"
    ]
    tabs = st.tabs(tab_names)

    with tabs[0]:
        i = data.get("basic_info", {})
        st.write(f"**📍 Location:** {i.get('city_country')}")
        st.write(f"**⏳ Duration:** {i.get('duration')}")
        st.write(f"**👥 Group:** {i.get('group_type')} ({i.get('group_size')})")
        st.divider()
        st.write("**🌟 Highlights:**")
        for h in i.get("highlights", []): st.write(f"- {h}")
        st.info(i.get("what_to_expect"))

    with tabs[1]:
        s = data.get("start_end", {})
        st.write(f"**Start:** {s.get('start_time')} | **End:** {s.get('end_time')}")
        st.write(f"**Method:** {s.get('join_method')}")
        st.write(f"**Points:** {s.get('meet_pick_points')}")

    with tabs[2]:
        steps = data.get("itinerary", {}).get("steps", [])
        for step in steps: st.write(step)

    with tabs[3]:
        pol = data.get("policies", {})
        st.error(f"**Cancellation Policy:** {pol.get('cancellation', '-')}")
        st.write(f"**📞 Merchant Contact:** {pol.get('merchant_contact', '-')}")

    with tabs[4]:
        inc = data.get("inclusions", {})
        c1, c2 = st.columns(2)
        with c1: 
            st.write("✅ **Included**")
            for x in data.get("inclusions", {}).get("included", []): st.write(f"- {x}")
        with c2: 
            st.write("❌ **Excluded**")
            for x in data.get("inclusions", {}).get("excluded", []): st.write(f"- {x}")

    with tabs[5]:
        r = data.get("restrictions", {})
        st.write(f"**Child:** {r.get('child_policy')}")
        st.write(f"**Accessibility:** {r.get('accessibility')}")
        with st.expander("View FAQ"): st.write(r.get('faq', 'No FAQ found.'))

    with tabs[6]: st.code(str(data.get("seo", {}).get("keywords")))
    with tabs[7]: st.write(data.get("pricing", {}).get("details"))
    
    with tabs[8]: 
        an = data.get("analysis", {})
        search_term = an.get("ota_search_term", "")
        st.write(f"**OTA Search Term:** `{search_term}`")
        
        if search_term:
            encoded_term = urllib.parse.quote(search_term)
            st.markdown("### 🔎 Find Similar Products")
            col1, col2, col3 = st.columns(3)
            with col1: st.link_button("🟢 Search on Viator", f"https://www.viator.com/searchResults/all?text={encoded_term}")
            with col2: st.link_button("🔵 Search on GetYourGuide", f"https://www.getyourguide.com/s?q={encoded_term}")
            with col3: 
                klook_query = f'site:klook.com "{search_term}"'
                st.link_button("🟠 Search on Klook", f"https://www.google.com/search?q={urllib.parse.quote(klook_query)}")
            col4, col5, col6 = st.columns(3)
            with col4: st.link_button("🦉 Search on TripAdvisor", f"https://www.tripadvisor.com/Search?q={encoded_term}")
            with col5: 
                fh_query = f'"{search_term}" FareHarbor'
                st.link_button("⚓ Find on FareHarbor", f"https://www.google.com/search?q={urllib.parse.quote(fh_query)}")
            with col6: 
                rezdy_query = f'"{search_term}" Rezdy'
                st.link_button("📅 Find on Rezdy", f"https://www.google.com/search?q={urllib.parse.quote(rezdy_query)}")

        if url_input:
            try:
                parsed_url = urllib.parse.urlparse(url_input)
                domain = parsed_url.netloc
                clean_domain = domain.replace("www.", "")
                merchant_name = clean_domain.split('.')[0].capitalize()
                st.markdown("---")
                st.markdown(f"### 🏢 Analyze Merchant: **{merchant_name}**")
                m_col1, m_col2 = st.columns(2)
                with m_col1:
                    query = f"sites like {clean_domain}"
                    st.link_button(f"🔎 Find Competitors to {merchant_name}", f"https://www.google.com/search?q={urllib.parse.quote(query)}")
                with m_col2:
                    query_reviews = f"{merchant_name} website reviews scam legit"
                    st.link_button(f"⭐ Check {merchant_name} Reliability", f"https://www.google.com/search?q={urllib.parse.quote(query_reviews)}")
                st.write("")
                st.caption("Check if they sell on OTAs (via Google Search):")
                m_col3, m_col4 = st.columns(2)
                with m_col3:
                    query_viator = f"{merchant_name} on Viator"
                    st.link_button(f"🟢 Find {merchant_name} on Viator", f"https://www.google.com/search?q={urllib.parse.quote(query_viator)}")
                with m_col4:
                    query_gyg = f"{merchant_name} on Get Your Guide"
                    st.link_button(f"🔵 Find {merchant_name} on GetYourGuide", f"https://www.google.com/search?q={urllib.parse.quote(query_gyg)}")
            except Exception: pass

# --- SMART ROTATION (RETRY LOGIC) ---
def smart_rotation_wrapper(text, keys):
    if not keys: return "⚠️ No API keys found."
    random.shuffle(keys)
    
    max_retries = 3
    for attempt in range(max_retries):
        for key in keys:
            result = call_gemini_json_summary(text, key)
            if result == "429_LIMIT":
                time.sleep(2) # Pause briefly before trying next key
                continue
            if "Error" not in result:
                return result # Success!
    
    return "⚠️ Server Busy (429). Please wait 30 seconds and try again."

# --- MAIN APP LOGIC ---
t1, t2, t3 = st.tabs(["🧠 Link Summary", "✍🏻 Text Summary", "🖼️ Photo Resizer"])

# TAB 1: LINK
with t1:
    url = st.text_input("Paste Tour Link")
    if st.button("Generate from Link"):
        keys = get_all_keys()
        if not keys: st.error("❌ No API Keys found."); st.stop()
        if not url: st.error("❌ Please enter a URL."); st.stop()

        with st.status("🚀 Processing...", expanded=True) as status:
            status.write("🕷️ Scraping URL...")
            text = extract_text_from_url(url)
            
            if not text or "ERROR" in text:
                status.update(label="❌ Scraping Failed", state="error")
                st.error(f"Scraper Error: {text}")
                st.stop()
            
            status.write(f"✅ Scraped {len(text)} characters.")
            status.write("🧠 Calling AI (Auto-Retry Enabled)...")
            
            result = smart_rotation_wrapper(text, keys)
            
            if "Busy" in result or "Error" in result:
                status.update(label="❌ AI Failed", state="error")
                st.error(result)
            else:
                status.update(label="✅ Complete!", state="complete")
                render_output(result, url_input=url)

# TAB 2: TEXT
with t2:
    raw_text = st.text_area("Paste Tour Text")
    if st.button("Generate from Text"):
        keys = get_all_keys()
        if not keys: st.error("❌ No API Keys"); st.stop()
        if len(raw_text) < 50: st.error("❌ Text too short (min 50 chars)"); st.stop()
        
        # REMOVED HIDDEN TRY-EXCEPT BLOCKS
        # This allows you to see the real error if it crashes
        st.info("🚀 Processing Text...")
        result = smart_rotation_wrapper(raw_text, keys)
        render_output(result)

# TAB 3: PHOTOS
with t3:
    st.info("Upload photos to resize to **8:5 (1280x800)** + Generate Captions")
    c_align = st.selectbox("Crop Focus", ["Center", "Top", "Bottom", "Left", "Right"])
    align_map = {"Center":(0.5,0.5), "Top":(0.5,0.0), "Bottom":(0.5,1.0), "Left":(0.0,0.5), "Right":(1.0,0.5)}
    
    files = st.file_uploader("Upload", accept_multiple_files=True, type=['jpg','png','jpeg'])
    
    if files:
        keys = get_all_keys()
        if st.button("Process Images"):
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in files:
                    b_img, err = resize_image_klook_standard(f, align_map[c_align])
                    if b_img:
                        zf.writestr(f"resized_{f.name}", b_img)
                        col1, col2 = st.columns([1,3])
                        col1.image(b_img, width=150)
                        
                        caption = "No Key"
                        if keys: caption = call_gemini_caption(b_img, random.choice(keys))
                        col2.text_area(f"Caption for {f.name}", value=caption, height=70)
            
            st.download_button("⬇️ Download All ZIP", zip_buf.getvalue(), "images.zip", "application/zip")
