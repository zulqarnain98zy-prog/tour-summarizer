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
            
            .timeline-step {
                padding: 10px;
                margin-bottom: 10px;
                border-left: 3px solid #ff5722;
                background-color: #f8f9fa;
                border-radius: 0 5px 5px 0;
            }
            .timeline-icon { font-size: 1.2rem; margin-right: 8px; }
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

# --- LOAD KEYS ---
def get_all_keys():
    if "GEMINI_KEYS" in st.secrets:
        return st.secrets["GEMINI_KEYS"]
    elif "GEMINI_API_KEY" in st.secrets:
        return [st.secrets["GEMINI_API_KEY"]]
    else:
        return []

# --- IMAGE RESIZING LOGIC ---
def resize_image_klook_standard(image_input, alignment=(0.5, 0.5)):
    if Image is None: return None, "⚠️ Error: 'Pillow' library missing."
    try:
        if isinstance(image_input, bytes):
            img = Image.open(io.BytesIO(image_input))
        else:
            img = Image.open(image_input)
            
        target_width = 1280
        target_height = 800
        img_resized = ImageOps.fit(img, (target_width, target_height), method=Image.Resampling.LANCZOS, centering=alignment)
        buf = io.BytesIO()
        img_format = img.format if img.format else 'JPEG'
        if img_resized.mode == 'RGBA' and img_format.upper() == 'JPEG':
            img_resized = img_resized.convert('RGB')
        img_resized.save(buf, format=img_format, quality=90)
        return buf.getvalue(), None
    except Exception as e:
        return None, f"Error processing image: {e}"

# --- SCRAPER (TEXT + IMAGES) ---
@st.cache_data(ttl=3600, show_spinner=False)
def extract_data_from_url(url):
    try:
        scraper = cloudscraper.create_scraper(browser='chrome')
        response = scraper.get(url, timeout=20)
        if response.status_code != 200: return None, f"ERROR: Status Code {response.status_code}"
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 1. EXTRACT IMAGES
        found_images = []
        for img in soup.find_all('img'):
            src = img.get('src')
            if src:
                if src.startswith('//'): src = 'https:' + src
                elif src.startswith('/'): src = urllib.parse.urljoin(url, src)
                
                if not any(x in src.lower() for x in ['logo', 'icon', 'avatar', 'svg', 'blank', 'transparent']):
                    if src not in found_images:
                        found_images.append(src)
        
        found_images = found_images[:15]

        # 2. EXTRACT TEXT
        for script in soup(["script", "style", "noscript", "svg"]): 
            script.extract()
            
        text = soup.get_text(separator=' \n ')
        lines = (line.strip() for line in text.splitlines())
        clean_text = '\n'.join(line for line in lines if line)[:100000] 
        
        return {"text": clean_text, "images": found_images}, None

    except Exception as e: return None, f"ERROR: {str(e)}"

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
    return text.replace("\\", "\\\\")[:95000]

# --- GEMINI CALLS ---
def call_gemini_json_summary(text, api_key):
    model_name = get_working_model_name(api_key)
    if not model_name: return "Error: No available Gemini models found."
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
    
    intro_prompt = f"""
    You are a content specialist for Klook.
    **TASK:** Convert tour text into strict JSON matching Klook's backend structure.
    
    **STRICT FORMATTING RULES:**
    1. **Highlights:** Exactly **4-5 bullet points**. Each point **10-12 words**. No full stops.
    2. **What to Expect:** Single paragraph (**100-120 words**).
    3. **Policies:** Bullet points.
    4. **FAQ:** Look for "Q&A" or "FAQ" headers. Combine Q&A into a single paragraph or "Q: ... A: ..." list.
    5. **PHONE NUMBER:** Format 'merchant_contact' as **+X-XXX-XXX-XXXX**. Detect country code from location.
    6. **Output:** ONLY raw JSON.
    
    **REQUIRED JSON STRUCTURE:**
    {{
        "basic_info": {{
            "city_country": "City, Country",
            "group_type": "Private/Join-in",
            "duration": "Duration",
            "main_attractions": "Tour Name",
            "highlights": ["Highlight 1", "Highlight 2", "Highlight 3", "Highlight 4"],
            "what_to_expect": "Single paragraph.",
            "selling_points": ["Tag 1", "Tag 2"]
        }},
        "klook_itinerary": {{
            "start": {{ "time": "09:00", "location": "Meeting Point Name" }},
            "segments": [
                {{ "type": "Attraction", "time": "10:00", "name": "Name", "details": "Details", "location_search": "Search Term" }}
            ],
            "end": {{ "time": "17:00", "location": "Drop off" }}
        }},
        "policies": {{ "cancellation": "Policy", "merchant_contact": "+X-XXX-XXX-XXXX" }},
        "inclusions": {{ "included": ["Item 1"], "excluded": ["Item 2"] }},
        "restrictions": {{ "child_policy": "Details", "accessibility": "Details", "faq": ["FAQ content"] }},
        "seo": {{ "keywords": ["Key 1"] }},
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

# --- EMAIL DRAFTER (GAP ANALYSIS) ---
def call_gemini_email_draft(json_data, api_key):
    model_name = get_working_model_name(api_key)
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""
    You are a Klook Onboarding Specialist. 
    **TASK:** Draft a concise email to the Merchant (Supplier).
    **GOAL:** ONLY Request MISSING or VAGUE information. Do NOT summarize the tour details we already found.
    
    **RULES:**
    1. **NO SUMMARY:** Do not list the "Highlights", "Description", or "Inclusions" unless you are asking a specific question about them.
    2. **MANDATORY CHECKS:** Always ask to verify the final **Duration** and **Selling Price** if not explicitly clear.
    3. **DETECT MISSING:** Look at the JSON. If fields are null, empty, or "TBA", ask for them.
    4. **ACTIVITY LOGIC:** - If Water Activity: Ask about weather policy & life jackets.
       - If Food: Ask about dietary options.
       - If Hiking/Adventure: Ask about difficulty & age limits.
       - If Transport: Ask about luggage limits.
    5. **TONE:** Professional, direct, bullet points.
    
    **INPUT DATA:**
    {json.dumps(json_data)}
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except: return "Error generating email."

def call_gemini_caption(image_bytes, api_key):
    model_name = get_working_model_name(api_key)
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
        
    # --- DEFINE VARIABLES ---
    info = data.get("basic_info", {})
    inc = data.get("inclusions", {})
    pol = data.get("policies", {})
    seo = data.get("seo", {})

    # --- SIDEBAR ---
    with st.sidebar:
        st.header("📋 Copy Dashboard")
        
        copy_box("📍 Location", info.get('city_country'))
        copy_box("🏷️ Name", info.get('main_attractions'))
        
        hl_list = info.get('highlights', [])
        hl_text = "\n".join([f"• {h}" for h in hl_list])
        copy_box("✨ Highlights", hl_text)
        
        copy_box("📝 Description", info.get('what_to_expect'))
        
        inc_list = inc.get('included', [])
        inc_text = "\n".join([f"• {x}" for x in inc_list])
        copy_box("✅ Included", inc_text)

        copy_box("❌ Excluded", "\n".join([f"• {x}" for x in inc.get('excluded', [])]))
        copy_box("📞 Phone", pol.get('merchant_contact'))
        
        st.divider()

    # --- MAIN PAGE ---
    st.success("✅ Analysis Complete! Use the Sidebar 👈 to copy-paste.")
    
    # TABS
    tab_names = ["ℹ️ Basic Info", "⏰ Start & End", "🗺️ Klook Itinerary", "📜 Policies", "✅ Inclusions", "🚫 Restrictions", "🔍 SEO", "💰 Price", "📊 Analysis", "📧 Supplier Email", "🔧 Automation"]
    tabs = st.tabs(tab_names)

    with tabs[0]:
        st.write(f"**📍 Location:** {info.get('city_country')}")
        st.write(f"**⏳ Duration:** {info.get('duration')}")
        st.write(f"**👥 Group:** {info.get('group_type')}")
        st.divider()
        st.write("**🌟 Highlights:**")
        for h in info.get("highlights", []): st.write(f"- {h}")
        st.info(info.get("what_to_expect"))

    with tabs[1]:
        itin = data.get("klook_itinerary", {})
        start = itin.get("start", {})
        end = itin.get("end", {})
        c1, c2 = st.columns(2)
        with c1:
            st.success("🏁 **START**")
            st.write(f"Time: **{start.get('time')}**")
            st.write(f"Loc: {start.get('location')}")
        with c2:
            st.error("🏁 **END**")
            st.write(f"Time: **{end.get('time')}**")
            st.write(f"Loc: {end.get('location')}")

    with tabs[2]:
        itin = data.get("klook_itinerary", {})
        start = itin.get("start", {})
        end = itin.get("end", {})
        segments = itin.get("segments", [])

        st.markdown(f"""<div class="timeline-step" style="border-left-color: #4CAF50;"><span class="timeline-time">{start.get('time')}</span><br><span class="timeline-title">🏁 Departure Info</span><br><span style="font-size:0.9rem">{start.get('location')}</span></div>""", unsafe_allow_html=True)

        for seg in segments:
            sType = seg.get('type', 'Attraction')
            sName = seg.get('name', 'Activity')
            sTime = seg.get('time', '')
            sDet = seg.get('details', '')
            
            # --- MAP LOGIC RESTORED ---
            sLoc = seg.get('location_search', '')
            map_btn = ""
            if sLoc:
                query = urllib.parse.quote(sLoc)
                link = f"https://www.google.com/maps/search/?api=1&query={query}"
                map_btn = f' | <a href="{link}" target="_blank" style="text-decoration:none; color:#2196F3;">📍 Map</a>'
            
            icon = "🎡"
            color = "#ff5722"
            if "Transport" in sType: icon="🚌"; color="#2196F3"
            if "Meal" in sType: icon="🍽️"; color="#9C27B0"
            st.markdown(f"""<div class="timeline-step" style="border-left-color: {color};"><span class="timeline-time">{sTime}</span> <br><span class="timeline-title">{icon} {sType}: {sName}</span> {map_btn}<br><span style="font-size:0.9rem; color:#666;">{sDet}</span></div>""", unsafe_allow_html=True)

        st.markdown(f"""<div class="timeline-step" style="border-left-color: #F44336;"><span class="timeline-time">{end.get('time')}</span><br><span class="timeline-title">🏁 Return Info</span><br><span style="font-size:0.9rem">{end.get('location')}</span></div>""", unsafe_allow_html=True)

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
        res = data.get("restrictions", {})
        st.write(f"**Child:** {res.get('child_policy')}")
        st.write(f"**Accessibility:** {res.get('accessibility')}")
        
        faq = res.get('faq')
        with st.expander("View FAQ", expanded=True):
            if isinstance(faq, list):
                for f in faq: st.write(f"- {f}")
            else:
                st.info(faq or 'No FAQ found.')

    with tabs[6]: st.code(str(seo.get("keywords")))
    with tabs[7]: st.write(data.get("pricing", {}).get("details"))
    
    with tabs[8]: 
        an = data.get("analysis", {})
        search_term = an.get("ota_search_term", "")
        if not search_term: search_term = info.get('main_attractions', '')
        
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

    with tabs[9]:
        st.header("📧 Draft Supplier Email")
        if st.button("📝 Draft Email"):
            keys = get_all_keys()
            if keys:
                with st.spinner("Analyzing Gaps..."):
                    email = call_gemini_email_draft(data, keys[0])
                    st.text_area("Email Draft", value=email, height=300)
    
    with tabs[10]:
        st.header("🔧 Automation Data")
        st.code(json.dumps(data, indent=4), language="json")

# --- SMART ROTATION ---
def smart_rotation_wrapper(text, keys):
    if not keys: return "⚠️ No API keys found."
    random.shuffle(keys)
    max_retries = 3
    for attempt in range(max_retries):
        for key in keys:
            result = call_gemini_json_summary(text, key)
            if result == "429_LIMIT":
                time.sleep(1)
                continue
            if "Error" not in result: return result
    return "⚠️ Server Busy. Try again."

# --- MAIN APP LOGIC ---
t1, t2, t3 = st.tabs(["🧠 Link Summary", "✍🏻 Text Summary", "🖼️ Photo Resizer"])

with t1:
    url = st.text_input("Paste Tour Link")
    if st.button("Generate from Link"):
        keys = get_all_keys()
        if not keys: st.error("❌ No API Keys"); st.stop()
        if not url: st.error("❌ Enter URL"); st.stop()

        with st.status("🚀 Processing...", expanded=True) as status:
            status.write("🕷️ Scraping URL & Images...")
            data_dict, err = extract_data_from_url(url)
            
            if err or not data_dict:
                status.update(label="❌ Scrape Failed", state="error")
                st.error(err)
                st.stop()
            
            st.session_state['scraped_images'] = data_dict['images']
            
            status.write(f"✅ Found {len(data_dict['images'])} images & {len(data_dict['text'])} chars. Calling AI...")
            result = smart_rotation_wrapper(data_dict['text'], keys)
            
            if "Busy" not in result and "Error" not in result:
                st.session_state['gen_result'] = result
                st.session_state['url_input'] = url
            
            if "Busy" in result or "Error" in result:
                status.update(label="❌ AI Failed", state="error")
                st.error(result)
            else:
                status.update(label="✅ Complete!", state="complete")

with t2:
    raw_text = st.text_area("Paste Tour Text")
    if st.button("Generate from Text"):
        keys = get_all_keys()
        if not keys: st.error("❌ No Keys"); st.stop()
        result = smart_rotation_wrapper(raw_text, keys)
        if "Busy" not in result and "Error" not in result:
            st.session_state['gen_result'] = result

# --- PHOTO RESIZER TAB ---
with t3:
    st.info("Upload photos OR use photos scraped from the link.")
    enable_captions = st.checkbox("☑️ Generate AI Captions", value=True)
    c_align = st.selectbox("Crop Focus", ["Center", "Top", "Bottom", "Left", "Right"])
    align_map = {"Center":(0.5,0.5), "Top":(0.5,0.0), "Bottom":(0.5,1.0), "Left":(0.0,0.5), "Right":(1.0,0.5)}
    
    # 1. FILE UPLOADER
    files = st.file_uploader("Upload Files", accept_multiple_files=True, type=['jpg','png','jpeg'])
    
    # 2. SCRAPED IMAGES SELECTOR
    selected_scraped = []
    if st.session_state['scraped_images']:
        st.divider()
        st.write(f"**🌐 Found {len(st.session_state['scraped_images'])} images from website:**")
        cols = st.columns(5)
        for i, img_url in enumerate(st.session_state['scraped_images']):
            with cols[i % 5]:
                st.image(img_url, use_column_width=True)
                if st.checkbox("Select", key=f"img_{i}"):
                    selected_scraped.append(img_url)

    if st.button("Process Selected Images"):
        keys = get_all_keys()
        total_items = (files if files else []) + selected_scraped
        
        if not total_items:
            st.warning("⚠️ No images selected.")
        else:
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                
                prog_bar = st.progress(0)
                total_count = len(total_items)
                
                for idx, item in enumerate(total_items):
                    prog_bar.progress((idx + 1) / total_count)
                    
                    if hasattr(item, 'read'): # FileUpload
                        fname = item.name
                        b_img, err = resize_image_klook_standard(item, align_map[c_align])
                    else: # URL
                        fname = f"web_image_{idx}.jpg"
                        try:
                            headers = {'User-Agent': 'Mozilla/5.0'}
                            resp = requests.get(item, headers=headers, timeout=10)
                            b_img, err = resize_image_klook_standard(resp.content, align_map[c_align])
                        except: b_img = None
                    
                    if b_img:
                        zf.writestr(f"resized_{fname}", b_img)
                        
                        c1, c2 = st.columns([1, 2])
                        with c1:
                            st.image(b_img, caption=fname, use_column_width=True)
                        with c2:
                            caption_text = ""
                            if enable_captions and keys:
                                caption_text = call_gemini_caption(b_img, random.choice(keys))
                            st.text_area(f"Caption for {fname}", value=caption_text, height=100)
                            st.download_button(
                                label=f"⬇️ Download {fname}",
                                data=b_img,
                                file_name=f"resized_{fname}",
                                mime="image/jpeg"
                            )
                        st.divider()

            st.success("✅ All images processed!")
            st.download_button("⬇️ Download All (ZIP)", zip_buf.getvalue(), "klook_images.zip", "application/zip")

# --- ALWAYS RENDER IF DATA EXISTS ---
if st.session_state['gen_result']:
    render_output(st.session_state['gen_result'], st.session_state['url_input'])
