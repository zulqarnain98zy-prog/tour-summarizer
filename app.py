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

# --- MODEL FINDER (TEXT) ---
def get_valid_model(api_key):
    try:
        genai.configure(api_key=api_key)
        models = genai.list_models()
        available_names = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        
        # Priority list for text generation
        priority = [
            'models/gemini-1.5-flash',
            'models/gemini-1.5-flash-latest',
            'models/gemini-1.5-pro',
            'models/gemini-1.5-pro-latest',
            'models/gemini-1.0-pro',
            'models/gemini-pro'
        ]
        for m in priority:
            if m in available_names: return m
        return available_names[0] if available_names else None
    except Exception:
        return None

# --- MODEL FINDER (VISION) ---
def get_vision_model(api_key):
    """Specifically finds a model that supports images."""
    try:
        genai.configure(api_key=api_key)
        models = genai.list_models()
        available_names = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        
        # Priority list for VISION (Images)
        priority = [
            'models/gemini-1.5-flash',
            'models/gemini-1.5-flash-latest',
            'models/gemini-1.5-flash-001',
            'models/gemini-1.5-pro',
            'models/gemini-1.5-pro-latest',
            'models/gemini-pro-vision'
        ]
        
        for m in priority:
            if m in available_names: return m
            
        # Fallback to any 1.5 model
        for m in available_names:
            if "1.5" in m: return m
            
        return None
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
    Cherry Blossom, Fireflies, Maple Leaf, Northern Lights, Stargazing, National Park, Nature, Wildlife, Sunrise, Sunset, Dolphin Watching, Whale Watching, Canyon, Flower Viewing, Tulip, Lavender, Spring, Summer, Autumn, Winter, Coastal, Beachfront, 
    Bar Hopping, Dining, Wine Tasting, Cheese, Chocolate, Food, Gourmet, Street Food, Brewery, Distillery, Whiskey, Seafood, Local Food, Late Night Food, 
    ATV, Bouldering, Diving, Fishing, Fruit Picking, Hiking, Island Hopping, Kayaking, Night Fishing, Ski, Snorkeling, Trekking, Caving, Sports, Stadium, Horse Riding, Parasailing, 
    Transfers, Transfers With Tickets, Boat, Catamaran, Charter, Cruise, Ferry, Helicopter, Hop-On Hop-Off Bus, Limousine, Open-top Bus, Speedboat, Yacht, Walking, Bus, Bike, Electric Bike, River Cruise, Longtail Boat, Hot Air Balloon, 
    Hot Spring, Beach, Yoga, Meditation, 
    City, Countryside, Night, Shopping, Sightseeing, Photography, Self-guided, Shore Excursion, Adventure, Discovery, Backstreets, Hidden Gems
    """
    
    prompt = """
    You are an expert travel product manager. Analyze the tour text.
    **CRITICAL:** Output ONLY valid JSON. No Markdown. No code blocks.
    **Language:** English.

    **SELLING POINT RULES:**
    Select relevant tags ONLY from this list: """ + tag_list + """

    **HIGHLIGHTS RULES:**
    Exactly 4 bullet points. Each bullet must be 10-15 words. No full stops.

    **PHOTO CAPTIONS RULES:**
    Create 10 engaging photo captions (1 sentence each) that would fit the tour.

    Structure the JSON exactly like this:
    {
        "basic_info": {
            "city_country": "City, Country",
            "group_type": "1 Group (Private only) OR 1 Group (Join-in only) OR More than 1 (Both)",
            "group_size": "Min/Max pax",
            "duration": "Total time",
            "main_attractions": "Key spots visited",
            "highlights": ["Highlight 1", "Highlight 2", "Highlight 3", "Highlight 4"],
            "what_to_expect": "100-150 words description (max 800 chars)",
            "selling_points": ["Tag 1", "Tag 2", "Tag 3"]
        },
        "start_end": {
            "start_time": "Time(s)",
            "end_time": "Time (Calculated from duration if missing)",
            "join_method": "Meet-up only OR Pick-up only OR Both",
            "meet_pick_points": ["List of locations/addresses"],
            "drop_off": "Location or 'Not mentioned'"
        },
        "itinerary": {
            "steps": ["Stop 1: ...", "Stop 2: ...", "Stop 3: ..."],
            "note": "Mention if transport/food is between stops"
        },
        "photo_data": {
            "captions": ["Caption 1", "Caption 2", "Caption 3", "Caption 4", "Caption 5", "Caption 6", "Caption 7", "Caption 8", "Caption 9", "Caption 10"]
        },
        "policies": {
            "cancellation": "Policy rules",
            "merchant_contact": "Contact info or 'Not found'"
        },
        "inclusions": {
            "included": ["Item 1", "Item 2"],
            "excluded": ["Item 1", "Item 2"]
        },
        "restrictions": {
            "child_policy": "Age/height rules",
            "accessibility": "Details",
            "additional_info": "Key logistics",
            "faq": "Extracted FAQs"
        },
        "seo": {
            "keywords": ["Keyword 1", "Keyword 2", "Keyword 3"]
        },
        "pricing": {
            "details": "Adult/Child prices and unit types"
        },
        "analysis": {
            "ota_search_term": "Product Name City"
        }
    }

    Tour Text:
    """ + text
    return model.generate_content(prompt).text

def call_qa_comparison(klook, merchant, api_key):
    model_name = get_valid_model(api_key)
    if not model_name: raise ValueError("No model.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    prompt = f"""
    Compare Klook Data vs Merchant Data.
    **OBJECTIVE:** Determine if Klook is accurate.
    **SOURCE A (Klook):** {klook}
    **SOURCE B (Merchant):** {merchant}
    **OUTPUT:**
    ### 🛡️ QA VERDICT
    **Status:** [✅ APPROVED / ❌ REJECT / ⚠️ WARNING]
    **Reason:** [Short sentence]
    ### 🔍 Discrepancy Analysis
    | Feature | Klook | Merchant | Impact |
    | :--- | :--- | :--- | :--- |
    | **Price** | | | |
    | **Start Time** | | | |
    | **Inclusions** | | | |
    | **Cancellation**| | | |
    ### 📝 Missing Info
    List missing details.
    ### 💡 Recommendation
    One sentence advice.
    """
    return model.generate_content(prompt).text

def call_gemini_vision_caption(image_bytes, api_key):
    """Generates a caption for an image."""
    model_name = get_vision_model(api_key)
    if not model_name: return "Caption Error: No Vision Model Found (Check API Key)"

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    image_parts = [{"mime_type": "image/jpeg", "data": image_bytes}]
    
    prompt = """
    Write a caption for this photo.
    Strict Rules:
    1. Start with an experiential verb (e.g., Experience, Explore, Discover, Savor, Indulge in, Roam, Enjoy).
    2. Length: 10 to 12 words exactly.
    3. No emojis.
    4. No full stops or punctuation marks.
    5. Single sentence only.
    """
    
    try:
        response = model.generate_content([prompt, image_parts[0]])
        return response.text
    except Exception as e:
        return f"Caption Error: {e}"

# --- SMART ROTATION WRAPPERS ---
def smart_rotation_wrapper(task_type, keys, *args):
    if not keys: return "⚠️ No API keys found."
    random.shuffle(keys)
    max_cycles = 2
    for cycle in range(max_cycles):
        for index, key in enumerate(keys):
            try:
                if task_type == 'summary': return call_gemini_json_summary(args[0], key)
                elif task_type == 'qa': return call_qa_comparison(args[0], args[1], key)
            except (ResourceExhausted, ServiceUnavailable, NotFound, ValueError): continue
            except Exception as e: return f"AI Error: {e}"
        if cycle < max_cycles - 1: time.sleep(5)
    return "⚠️ **All servers busy:** Please wait 1 minute."

def smart_rotation_image_wrapper(keys, image_bytes):
    if not keys: return "⚠️ No Keys"
    random.shuffle(keys)
    for key in keys:
        try:
            return call_gemini_vision_caption(image_bytes, key)
        except Exception: continue
    return "Could not generate caption."

# --- DISPLAY HELPERS ---
def google_map_link(location):
    if not location or location == "Not mentioned": return location
    query = urllib.parse.quote(location)
    return f"[{location}](https://www.google.com/maps/search/?api=1&query={query})"

def render_json_results(json_text, url_input=None):
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        st.error("⚠️ AI Generation Error: Output was not valid JSON. Please try again.")
        st.text(json_text)
        return

    tab_names = [
        "ℹ️ Basic Info", "⏰ Start & End", "🗺️ Itinerary", "📸 Photos", 
        "📜 Policies", "✅ Inclusions", "🚫 Restrictions", "🔍 SEO", 
        "💰 Price", "📊 Analysis"
    ]
    tabs = st.tabs(tab_names)

    with tabs[0]:
        info = data.get("basic_info", {})
        c1, c2 = st.columns(2)
        c1.write(f"**📍 Departs From:** {info.get('city_country', '-')}")
        c2.write(f"**👥 Group Type:** {info.get('group_type', '-')}")
        c1.write(f"**🔢 Group Size:** {info.get('group_size', '-')}")
        c2.write(f"**⏳ Duration:** {info.get('duration', '-')}")
        st.divider()
        st.write(f"**🎡 Main Attractions:** {info.get('main_attractions', '-')}")
        st.subheader("🌟 Highlights")
        highlights = info.get("highlights", [])
        if isinstance(highlights, list):
            for h in highlights: st.write(f"- {h}")
        else: st.write(highlights)
        st.subheader("🏷️ Selling Points")
        points = info.get('selling_points', [])
        if isinstance(points, list): st.write(", ".join([f"`{p}`" for p in points]))
        else: st.write(points)
        st.info(f"**What to Expect:**\n\n{info.get('what_to_expect', '-')}")

    with tabs[1]:
        se = data.get("start_end", {})
        c1, c2 = st.columns(2)
        c1.success(f"**🟢 Start Time:** {se.get('start_time', '-')}")
        c2.error(f"**🔴 End Time:** {se.get('end_time', '-')}")
        st.write(f"**🚕 Method:** {se.get('join_method', '-')}")
        st.write("**📍 Meet-up / Pick-up Points:**")
        points = se.get('meet_pick_points', [])
        if isinstance(points, list):
            for p in points: st.markdown(f"- {google_map_link(p)}")
        else: st.markdown(google_map_link(str(points)))
        st.write(f"**🏁 Drop-off:** {se.get('drop_off', '-')}")

    with tabs[2]:
        itin = data.get("itinerary", {})
        st.caption(f"**Note:** {itin.get('note', '')}")
        steps = itin.get("steps", [])
        if isinstance(steps, list):
            for step in steps: st.write(step)
        else: st.write(steps)

    with tabs[3]:
        st.warning("⚠️ Note: AI cannot crop/resize real photos. Please match these captions to your 4:3 images.")
        captions = data.get("photo_data", {}).get("captions", [])
        for i, cap in enumerate(captions, 1): st.write(f"**{i}.** {cap}")

    with tabs[4]:
        pol = data.get("policies", {})
        st.error(f"**Cancellation Policy:** {pol.get('cancellation', '-')}")
        st.write(f"**📞 Merchant Contact:** {pol.get('merchant_contact', '-')}")

    with tabs[5]:
        inc = data.get("inclusions", {})
        c1, c2 = st.columns(2)
        with c1:
            st.write("✅ **Included:**")
            for x in inc.get("included", []): st.write(f"- {x}")
        with c2:
            st.write("❌ **Not Included:**")
            for x in inc.get("excluded", []): st.write(f"- {x}")

    with tabs[6]:
        res = data.get("restrictions", {})
        st.write(f"**👶 Child Policy:** {res.get('child_policy', '-')}")
        st.write(f"**♿ Accessibility:** {res.get('accessibility', '-')}")
        st.write(f"**📝 Additional Info:** {res.get('additional_info', '-')}")
        with st.expander("View FAQ"): st.write(res.get('faq', 'No FAQ found.'))

    with tabs[7]:
        seo = data.get("seo", {}).get("keywords", [])
        st.write("**🔑 Keywords:**")
        st.code(", ".join(seo))

    with tabs[8]:
        st.write(data.get("pricing", {}).get("details", '-'))

    with tabs[9]:
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

# --- MAIN TABS ---
t1, t2, t3, t4, t5 = st.tabs([
    "🧠 Summarize Activity (Link)", 
    "✍🏻 Summarize Activity (Fallback)", 
    "📂 Summarize Activity (File/PDF)",
    "🖼️ Photo Resizer (8:5)",
    "⚖️ QA Comparison (Testing)"
])

# 1. LINK SUMMARY
with t1:
    url = st.text_input("Paste Tour Link")
    if st.button("Generate Summary", key="btn1"):
        keys = get_all_keys()
        if not keys or not url: st.error("Check Keys/URL")
        else:
            with st.spinner("Processing..."):
                txt = extract_text_from_url(url)
                if txt and "ERROR" not in txt:
                    res = smart_rotation_wrapper('summary', keys, txt)
                    print(f"✅ LINK SUCCESS | {datetime.now()}")
                    if "AI Error" in res: st.error(res)
                    else: render_json_results(res, url_input=url)
                else: st.error("Error reading URL")

# 2. TEXT SUMMARY
with t2:
    txt_in = st.text_area("Paste Text")
    if st.button("Generate", key="btn2"):
        keys = get_all_keys()
        if not keys or len(txt_in)<50: st.error("Paste more text")
        else:
            with st.spinner("Processing..."):
                res = smart_rotation_wrapper('summary', keys, txt_in)
                print(f"✅ TEXT SUCCESS | {datetime.now()}")
                if "AI Error" in res: st.error(res)
                else: render_json_results(res)

# 3. FILE SUMMARY
with t3:
    up_file = st.file_uploader("Upload PDF/Docx", type=["pdf","docx","txt"])
    if st.button("Generate", key="btn3"):
        keys = get_all_keys()
        if not keys or not up_file: st.error("Check File")
        else:
            with st.spinner("Reading..."):
                txt = extract_text_from_file(up_file)
                if "Error" not in txt:
                    res = smart_rotation_wrapper('summary', keys, txt)
                    print(f"✅ FILE SUCCESS | {datetime.now()}")
                    if "AI Error" in res: st.error(res)
                    else: render_json_results(res)
                else: st.error(txt)

# 4. PHOTO RESIZER (8:5) WITH CAPTIONS
with t4:
    st.info("🖼️ Upload photos to crop to **8:5** (1280x800) AND generate AI captions.")
    uploaded_imgs = st.file_uploader("Upload Images", type=['jpg','jpeg','png'], accept_multiple_files=True)
    
    if uploaded_imgs:
        keys = get_all_keys()
        zip_buffer = io.BytesIO()
        processed_images = []
        
        # Process all images
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for img_file in uploaded_imgs:
                # 1. Resize
                processed_bytes, error = resize_image_klook_standard(img_file)
                
                if processed_bytes:
                    file_name = f"resized_{img_file.name}"
                    # Add to zip
                    zip_file.writestr(file_name, processed_bytes)
                    
                    # 2. Generate Caption (Only if keys exist)
                    caption = "No API Key found"
                    if keys:
                        caption = smart_rotation_image_wrapper(keys, processed_bytes)
                        
                    processed_images.append((img_file.name, processed_bytes, caption))
        
        # Show "Download All" if multiple
        if len(processed_images) > 1:
            st.download_button(
                label="⬇️ Download All as ZIP",
                data=zip_buffer.getvalue(),
                file_name="resized_images_1280x800.zip",
                mime="application/zip",
                use_container_width=True
            )
            st.divider()

        # Show individual previews with Captions
        for name, data, cap in processed_images:
            col1, col2 = st.columns([1, 3])
            with col1:
                st.image(data, caption=name, width=200)
            with col2:
                st.download_button(
                    label=f"⬇️ Download {name}",
                    data=data,
                    file_name=f"resized_{name}",
                    mime="image/jpeg"
                )
                st.text_area("AI Caption:", value=cap, height=70, key=f"cap_{name}")
            st.divider()

# 5. QA COMPARISON
with t5:
    st.info("Compare Klook Draft vs Merchant Site")
    c1, c2 = st.columns(2)
    k_txt = c1.text_area("1️⃣ Paste from Klook")
    m_url = c2.text_input("2️⃣ Merchant URL")
    if st.button("Compare", key="btn4"):
        keys = get_all_keys()
        if not keys or not k_txt or not m_url: st.error("Missing Data")
        else:
            with st.spinner("Comparing..."):
                m_txt = extract_text_from_url(m_url)
                if m_txt and "ERROR" not in m_txt:
                    res = smart_rotation_wrapper('qa', keys, k_txt, m_txt)
                    print(f"✅ QA SUCCESS | {datetime.now()}")
                    st.success("Done!")
                    st.markdown("---"); st.markdown(res)
                else: st.error("Error reading Merchant URL")
