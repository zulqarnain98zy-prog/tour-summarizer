import streamlit as st
import cloudscraper
import time
import random
import re
import json
from bs4 import BeautifulSoup
import google.generativeai as genai
import sys
import io
import urllib.parse

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

# --- LOAD KEYS ---
def get_all_keys():
    keys = []
    if "GEMINI_KEYS" in st.secrets:
        keys = st.secrets["GEMINI_KEYS"]
    elif "GEMINI_API_KEY" in st.secrets:
        keys = [st.secrets["GEMINI_API_KEY"]]
    
    # Clean keys (remove empty strings)
    keys = [k for k in keys if k and len(k) > 10]
    return keys

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
        return None, f"Error: {e}"

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
        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        clean_text = '\n'.join(line for line in lines if line)
        return clean_text[:40000] # Limit char count for API safety
    except Exception as e:
        return f"ERROR: {str(e)}"

# --- AI HELPERS ---
def get_valid_model(api_key):
    genai.configure(api_key=api_key)
    return 'models/gemini-1.5-flash' # Force Flash for speed/reliability

def get_vision_model(api_key):
    genai.configure(api_key=api_key)
    return 'models/gemini-1.5-flash'

def call_gemini_summary(text, api_key):
    try:
        model_name = get_valid_model(api_key)
        model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
        
        tag_list = "Interactive, Romantic, Guided, Private, Skip-the-line, Small Group, VIP, Architecture, Cultural, Historical, Museum, Nature, Wildlife, Food, Hiking, Boat, Cruise, Night, Shopping, Sightseeing"
        
        prompt = f"""
        You are a travel product manager.
        **TASK:** Convert the following tour text into strict JSON.
        
        **INPUT TEXT:**
        {text[:30000]}
        
        **REQUIRED JSON STRUCTURE:**
        {{
            "basic_info": {{
                "city_country": "City, Country",
                "group_type": "Private/Join-in",
                "group_size": "Min/Max",
                "duration": "Duration",
                "main_attractions": "Attraction 1, Attraction 2",
                "highlights": ["Highlight 1", "Highlight 2", "Highlight 3", "Highlight 4"],
                "what_to_expect": "Short summary",
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
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI Error: {str(e)}"

def call_gemini_caption(image_bytes, api_key):
    try:
        model_name = get_vision_model(api_key)
        model = genai.GenerativeModel(model_name)
        prompt = "Write a captivating social media caption (10-12 words, experiential verb start, no emojis)."
        response = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": image_bytes}])
        return response.text
    except:
        return "Caption failed."

# --- UI RENDERER ---
def render_output(json_text):
    # 1. SHOW RAW DATA (Diagnostic)
    with st.expander("👀 View Raw Data (Click if Tabs are empty)", expanded=False):
        st.code(json_text)

    # 2. PARSE JSON
    try:
        # Clean markdown
        clean_text = json_text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_text)
    except:
        st.warning("⚠️ Could not format data into Tabs. Please use the 'Raw Data' above.")
        return

    # 3. RENDER TABS
    tabs = st.tabs(["ℹ️ Info", "⏰ Logistics", "🗺️ Itinerary", "📜 Policies", "✅ In/Ex", "🚫 Rules", "🔍 SEO", "💰 Price", "📊 Analysis"])
    
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
        st.write(data.get("policies", {}).get("cancellation"))

    with tabs[4]:
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
        with st.expander("FAQ"): st.write(r.get('faq'))

    with tabs[6]: st.code(str(data.get("seo", {}).get("keywords")))
    with tabs[7]: st.write(data.get("pricing", {}).get("details"))
    with tabs[8]: 
        term = data.get("analysis", {}).get("ota_search_term")
        st.write(f"Search: {term}")
        if term:
            q = urllib.parse.quote(term)
            st.link_button("Search Viator", f"https://www.viator.com/searchResults/all?text={q}")
            st.link_button("Search GYG", f"https://www.getyourguide.com/s?q={q}")

# --- MAIN APP LOGIC ---
t1, t2, t3 = st.tabs(["🧠 Link Summary", "✍🏻 Text Summary", "🖼️ Photo Resizer"])

# TAB 1: LINK
with t1:
    url = st.text_input("Paste Tour Link")
    if st.button("Generate from Link"):
        keys = get_all_keys()
        
        # 1. Check Keys
        if not keys:
            st.error("❌ No API Keys found in Secrets.")
            st.stop()
        
        # 2. Check URL
        if not url:
            st.error("❌ Please enter a URL.")
            st.stop()

        with st.status("🚀 Processing...", expanded=True) as status:
            # 3. Scrape
            status.write("🕷️ Scraping URL...")
            text = extract_text_from_url(url)
            
            if not text or "ERROR" in text:
                status.update(label="❌ Scraping Failed", state="error")
                st.error(f"Could not read website. It might be blocked.\nDetails: {text}")
                st.stop()
            
            status.write(f"✅ Scraped {len(text)} characters.")
            
            # 4. Call AI
            status.write("🧠 Calling AI...")
            try:
                # Random key rotation
                key = random.choice(keys)
                result = call_gemini_summary(text, key)
                
                if "AI Error" in result:
                    status.update(label="❌ AI Failed", state="error")
                    st.error(result)
                    st.stop()
                    
                status.update(label="✅ Complete!", state="complete")
                render_output(result)
                
            except Exception as e:
                st.error(f"System Error: {e}")

# TAB 2: TEXT
with t2:
    raw_text = st.text_area("Paste Tour Text")
    if st.button("Generate from Text"):
        keys = get_all_keys()
        if not keys: st.error("❌ No API Keys"); st.stop()
        if len(raw_text) < 50: st.error("❌ Text too short"); st.stop()
        
        with st.spinner("Generating..."):
            key = random.choice(keys)
            result = call_gemini_summary(raw_text, key)
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
