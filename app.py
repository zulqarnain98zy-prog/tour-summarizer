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
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

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

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

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
if 'product_context' not in st.session_state:
    st.session_state['product_context'] = ""

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

# --- CUSTOM SSL ADAPTER ---
class LegacySSLAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False):
        ctx = ssl.create_default_context()
        ctx.set_ciphers('DEFAULT@SECLEVEL=1') 
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=ctx
        )

# --- SCRAPER ---
@st.cache_data(ttl=3600, show_spinner=False)
def extract_data_from_url(url):
    try:
        scraper = cloudscraper.create_scraper(browser='chrome')
        scraper.mount('https://', LegacySSLAdapter())
        
        response = scraper.get(url, timeout=20)
        if response.status_code != 200: return None, f"ERROR: Status Code {response.status_code}"
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # EXTRACT IMAGES
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

        # EXTRACT TEXT
        for script in soup(["script", "style", "noscript", "svg"]): 
            script.extract()
        text = soup.get_text(separator=' \n ')
        lines = (line.strip() for line in text.splitlines())
        clean_text = '\n'.join(line for line in lines if line)[:100000] 
        
        return {"text": clean_text, "images": found_images}, None
    except Exception as e: return None, f"ERROR: {str(e)}"

# --- PDF READER ---
def extract_text_from_pdf(uploaded_file):
    if not HAS_PYPDF:
        return "⚠️ Error: 'pypdf' library not installed. Please add 'pypdf' to requirements.txt."
    try:
        reader = PdfReader(uploaded_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text[:100000] # Limit char count
    except Exception as e:
        return f"Error reading PDF: {str(e)}"

# --- PDF GENERATOR (REPORTLAB) ---
def create_pdf(data):
    if not HAS_REPORTLAB:
        return None
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    # Custom Styles
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=16, spaceAfter=12, textColor=colors.darkorange)
    heading_style = ParagraphStyle('Heading', parent=styles['Heading2'], fontSize=12, spaceBefore=10, spaceAfter=6, textColor=colors.black)
    body_style = styles['BodyText']
    bullet_style = ParagraphStyle('Bullet', parent=styles['BodyText'], leftIndent=20)

    # 1. HEADER
    info = data.get('basic_info', {})
    story.append(Paragraph(f"{info.get('main_attractions', 'Tour Summary')}", title_style))
    story.append(Paragraph(f"<b>Location:</b> {info.get('city_country')} | <b>Duration:</b> {info.get('duration')}", body_style))
    story.append(Spacer(1, 12))

    # 2. HIGHLIGHTS
    story.append(Paragraph("✨ Highlights", heading_style))
    highlights = info.get('highlights', [])
    if highlights:
        bullets = [ListItem(Paragraph(h, body_style)) for h in highlights]
        story.append(ListFlowable(bullets, bulletType='bullet', start='•'))

    # 3. DESCRIPTION
    story.append(Paragraph("📝 What to Expect", heading_style))
    story.append(Paragraph(info.get('what_to_expect', ''), body_style))

    # 4. ITINERARY
    story.append(Paragraph("🗺️ Itinerary", heading_style))
    itin = data.get('klook_itinerary', {})
    segments = itin.get('segments', [])
    
    # Start
    start = itin.get('start', {})
    story.append(Paragraph(f"<b>{start.get('time', '')}</b> - Start at {start.get('location', '')}", body_style))
    
    # Segments
    for seg in segments:
        text = f"<b>{seg.get('time', '')}</b> - {seg.get('type')}: {seg.get('name')}"
        if seg.get('details'):
            text += f"<br/><i>{seg.get('details')}</i>"
        story.append(Paragraph(text, bullet_style))
    
    # End
    end = itin.get('end', {})
    story.append(Paragraph(f"<b>{end.get('time', '')}</b> - End at {end.get('location', '')}", body_style))

    # 5. INCLUSIONS / EXCLUSIONS
    inc = data.get('inclusions', {})
    
    story.append(Paragraph("✅ Included", heading_style))
    included = inc.get('included', [])
    if included:
        bullets = [ListItem(Paragraph(x, body_style)) for x in included]
        story.append(ListFlowable(bullets, bulletType='bullet', start='•'))
        
    story.append(Paragraph("❌ Excluded", heading_style))
    excluded = inc.get('excluded', [])
    if excluded:
        bullets = [ListItem(Paragraph(x, body_style)) for x in excluded]
        story.append(ListFlowable(bullets, bulletType='bullet', start='•'))

    doc.build(story)
    return buffer.getvalue()

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

# --- KLOOK SELLING POINTS LIST ---
SELLING_POINTS_LIST = """
Interactive, Romantic, Customizable, Guided, Private, Skip-the-line, Small Group, VIP, All Inclusive, 
Architecture, Canal, Cultural, Historical, Movie, Museum, Music, Religious Site, Pilgrimage, Spiritual, Temple, UNESCO site, Local Village, Old Town, 
TV, Movie and TV, Heritage, Downtown, City Highlights, Downtown Highlights, 
Alpine Route, Coral Reef, Desert, Glacier, Mangrove, Marine Life, Mountain, Rainforest, Safari, Sand Dune, Volcano, Waterfall, River, 
Cherry Blossom, Fireflies, Maple Leaf, Northern Lights, Stargazing, National Park, Nature, Wildlife, Sunrise, Sunset, 
Dolphin Watching, Whale Watching, Canyon, Flower Viewing, Tulip, Lavender, Spring, Summer, Autumn, Winter, Coastal, Beachfront, 
Bar Hopping, Dining, Wine Tasting, Cheese, Chocolate, Food, Gourmet, Street Food, Brewery, Distillery, Whiskey, Seafood, Local Food, Late Night Food, 
ATV, Bouldering, Diving, Fishing, Fruit Picking, Hiking, Island Hopping, Kayaking, Night Fishing, Ski, Snorkeling, Trekking, Caving, 
Sports, Stadium, Horse Riding, Parasailing, 
Transfers, Transfers With Tickets, Boat, Catamaran, Charter, Cruise, Ferry, Helicopter, Hop-On Hop-Off Bus, Limousine, Open-top Bus, Speedboat, Yacht, Walking, Bus, Bike, Electric Bike, River Cruise, Longtail Boat, Hot Air Balloon, 
Hot Spring, Beach, Yoga, Meditation, 
City, Countryside, Night, Shopping, Sightseeing, Photography, Self-guided, Shore Excursion, Adventure, Discovery, Backstreets, Hidden Gems
"""

# --- GEMINI CALLS ---
def call_gemini_json_summary(text, api_key):
    model_name = get_working_model_name(api_key)
    if not model_name: return "Error: No available Gemini models found."
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
    
    intro_prompt = f"""
    You are a content specialist for Klook.
    **TASK:** Convert tour text into strict JSON.
    
    **CRITICAL ACCURACY RULES:**
    1. **NO HALLUCINATION:** If pickup info or duration is not in the text, return "TBC" or null. Do not guess based on similar tours.
    2. **STRICT LENGTH:** 'what_to_expect' MUST be between **100-110 words**. 
    3. **NO FULL STOP:** The 'what_to_expect' paragraph MUST NOT end with a full stop (period).
    
    **FORMATTING RULES:**
    1. **Highlights:** Exactly 4-5 bullet points (10-12 words each). No full stops.
    2. **Phone:** Format as +X-XXX-XXX-XXXX.
    3. **Itinerary POIs:** Indicate if "Free Entry" or "Ticket Required" in the 'ticket_status' field. If unknown, use "Unknown".
    4. **Selling Points:** Choose only from the allowed list.
    
    **ALLOWED SELLING POINTS:**
    {SELLING_POINTS_LIST}
    
    **REQUIRED JSON STRUCTURE:**
    {{
        "basic_info": {{
            "city_country": "City, Country",
            "group_type": "Private/Join-in",
            "duration": "Extract EXACT text (e.g. 3 hours)",
            "main_attractions": "Tour Name",
            "highlights": ["Highlight 1", "Highlight 2", "Highlight 3", "Highlight 4"],
            "what_to_expect": "Strictly 100-110 words. No final full stop",
            "selling_points": ["Tag 1", "Tag 2"]
        }},
        "klook_itinerary": {{
            "start": {{ "time": "09:00", "location": "Meeting Point Name (Use TBC if missing)" }},
            "segments": [
                {{ "type": "Attraction", "time": "10:00", "name": "Name", "details": "Details", "location_search": "Search Term", "ticket_status": "Free Entry/Ticket Required/Unknown" }}
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

# --- EMAIL DRAFTER ---
def call_gemini_email_draft(json_data, api_key):
    model_name = get_working_model_name(api_key)
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""
    You are a Klook Onboarding Specialist. 
    **TASK:** Draft a concise GAP ANALYSIS email to the Merchant.
    **GOAL:** ONLY Request MISSING or VAGUE information. 
    **RULES:**
    1. Do NOT summarize the tour.
    2. Ask to confirm Duration and Price.
    3. Detect missing/null fields in this JSON: {json.dumps(json_data)}
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except: return "Error generating email."

# --- CAPTION GENERATOR ---
def call_gemini_caption(image_bytes, api_key, context_str=""):
    model_name = get_working_model_name(api_key)
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""
    Write a social media caption for this image.
    **CONTEXT:** This is a tour of: '{context_str}'. Make the caption specific to this activity/location if possible.
    **RULES:**
    1. Strictly 10-12 words.
    2. Start with an experiential verb.
    3. NO full stop at the end.
    4. No emojis.
    """
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
        # Update session context
        if "basic_info" in data and "main_attractions" in data["basic_info"]:
            st.session_state['product_context'] = data["basic_info"]["main_attractions"]
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
        
        # --- PDF BUTTON ---
        if HAS_REPORTLAB:
            pdf_data = create_pdf(data)
            if pdf_data:
                st.download_button(
                    label="📄 Download Summary PDF",
                    data=pdf_data,
                    file_name=f"Klook_Summary_{int(time.time())}.pdf",
                    mime="application/pdf"
                )
        else:
            st.warning("Install 'reportlab' to enable PDF downloads.")

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
        st.write("**🏷️ Selling Points:**")
        st.write(", ".join(info.get("selling_points", [])))
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
            sTicket = seg.get('ticket_status', 'Unknown')
            
            # --- MAP & OFFICIAL SITE LOGIC ---
            sLoc = seg.get('location_search', '')
            map_btn = ""
            if sLoc:
                query = urllib.parse.quote(sLoc)
                link = f"https://www.google.com/maps/search/?api=1&query={query}"
                site_query = urllib.parse.quote(f"{sLoc} official website")
                site_link = f"https://www.google.com/search?q={site_query}"
                
                map_btn = f' | <a href="{link}" target="_blank" style="text-decoration:none; color:#2196F3;">📍 Map</a> | <a href="{site_link}" target="_blank" style="text-decoration:none; color:#4CAF50;">🌐 Official Site</a>'
            
            icon = "🎡"
            color = "#ff5722"
            if "Transport" in sType: icon="🚌"; color="#2196F3"
            if "Meal" in sType: icon="🍽️"; color="#9C27B0"
            
            ticket_badge = ""
            if sTicket and "Free" in sTicket: ticket_badge = f" <span style='background:#E8F5E9; color:#2E7D32; padding:2px 6px; border-radius:4px; font-size:0.8rem'>🆓 {sTicket}</span>"
            elif sTicket and "Unknown" not in sTicket: ticket_badge = f" <span style='background:#FFF3E0; color:#EF6C00; padding:2px 6px; border-radius:4px; font-size:0.8rem'>🎫 {sTicket}</span>"

            st.markdown(f"""<div class="timeline-step" style="border-left-color: {color};"><span class="timeline-time">{sTime}</span> <br><span class="timeline-title">{icon} {sType}: {sName}</span> {ticket_badge} {map_btn}<br><span style="font-size:0.9rem; color:#666;">{sDet}</span></div>""", unsafe_allow_html=True)

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
t1, t2, t3, t4 = st.tabs(["🧠 Link Summary", "✍🏻 Text Summary", "📄 PDF Summary", "🖼️ Photo Resizer"])

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
            try:
                d = json.loads(result)
                if "basic_info" in d: st.session_state['product_context'] = d["basic_info"].get("main_attractions", "")
            except: pass

with t3:
    st.info("Upload a PDF brochure or document to summarize.")
    pdf_file = st.file_uploader("Upload PDF", type=['pdf'])
    if pdf_file and st.button("Generate from PDF"):
        keys = get_all_keys()
        if not keys: st.error("❌ No Keys"); st.stop()
        
        with st.status("🚀 Reading PDF...", expanded=True) as status:
            pdf_text = extract_text_from_pdf(pdf_file)
            if "Error" in pdf_text:
                status.update(label="❌ PDF Read Failed", state="error")
                st.error(pdf_text)
                st.stop()
            
            status.write(f"✅ Extracted {len(pdf_text)} chars. Calling AI...")
            result = smart_rotation_wrapper(pdf_text, keys)
            
            if "Busy" not in result and "Error" not in result:
                st.session_state['gen_result'] = result
                try:
                    d = json.loads(result)
                    if "basic_info" in d: st.session_state['product_context'] = d["basic_info"].get("main_attractions", "")
                except: pass
                status.update(label="✅ Complete!", state="complete")
            else:
                status.update(label="❌ AI Failed", state="error")
                st.error(result)

# --- PHOTO RESIZER TAB ---
with t4:
    st.info("Upload photos OR use photos scraped from the link.")
    
    context_val = st.session_state.get('product_context', '')
    manual_context = st.text_input("Product Name / Context (for better captions):", value=context_val)
    
    enable_captions = st.checkbox("☑️ Generate AI Captions", value=True)
    c_align = st.selectbox("Crop Focus", ["Center", "Top", "Bottom", "Left", "Right"])
    align_map = {"Center":(0.5,0.5), "Top":(0.5,0.0), "Bottom":(0.5,1.0), "Left":(0.0,0.5), "Right":(1.0,0.5)}
    
    files = st.file_uploader("Upload Files", accept_multiple_files=True, type=['jpg','png','jpeg'])
    
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
                    
                    if hasattr(item, 'read'): 
                        fname = item.name
                        b_img, err = resize_image_klook_standard(item, align_map[c_align])
                    else: 
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
                                # PASSING CONTEXT HERE
                                caption_text = call_gemini_caption(b_img, random.choice(keys), context_str=manual_context)
                            
                            st.text_area(f"Caption for {fname}", value=caption_text, height=100, key=f"cap_{idx}")
                            
                            st.download_button(
                                label=f"⬇️ Download {fname}",
                                data=b_img,
                                file_name=f"resized_{fname}",
                                mime="image/jpeg",
                                key=f"btn_{idx}"
                            )
                        st.divider()

            st.success("✅ All images processed!")
            st.download_button("⬇️ Download All (ZIP)", zip_buf.getvalue(), "klook_images.zip", "application/zip")

# --- ALWAYS RENDER IF DATA EXISTS ---
if st.session_state['gen_result']:
    render_output(st.session_state['gen_result'], st.session_state['url_input'])
