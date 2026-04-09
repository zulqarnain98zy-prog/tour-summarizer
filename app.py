import streamlit as st
import cloudscraper
import time
import random
import re
import urllib.parse
import json
import requests
import base64
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
                padding: 10px;
                margin-bottom: 10px;
                border-left: 3px solid #ff5722;
                background-color: #f8f9fa;
                border-radius: 0 5px 5px 0;
            }
            .timeline-icon { font-size: 1.2rem; margin-right: 8px; }
            .timeline-time { font-weight: bold; color: #555; font-size: 0.9rem; }
            .timeline-title { font-weight: bold; font-size: 1rem; color: #333; }
            
            /* Risk Colors */
            .risk-card {
                padding: 15px;
                border-radius: 10px;
                margin-bottom: 10px;
                border: 1px solid #ddd;
            }
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
if 'processed_images_data' not in st.session_state:
    st.session_state['processed_images_data'] = []

# --- LOAD KEYS ---
def get_all_keys():
    if "GEMINI_KEYS" in st.secrets:
        return st.secrets["GEMINI_KEYS"]
    elif "GEMINI_API_KEY" in st.secrets:
        return [st.secrets["GEMINI_API_KEY"]]
    else:
        return []

# --- HELPER: ROMANIZE TEXT ---
def romanize_text(text):
    if not text: return ""
    normalized = unicodedata.normalize('NFKD', text)
    return normalized.encode('ascii', 'ignore').decode('ascii')

# --- IMPROVED MERCHANT RISK LOGIC (V5 - AUTO-RETRY & MATH RULES) ---
def validate_merchant_risk(text, url, keys):
    if not keys: return {"error": "No API keys found."}
    
    scraped_content = text
    inferred_name = ""
    
    # 1. Automatic "About Us" and Merchant Name Hunting
    if url:
        try:
            scraper = cloudscraper.create_scraper()
            base_res = scraper.get(url, timeout=15)
            soup = BeautifulSoup(base_res.content, 'html.parser')
            
            title = soup.find('title')
            if title:
                inferred_name = title.get_text().split('|')[0].split('-')[0].strip()
            else:
                inferred_name = urllib.parse.urlparse(url).netloc.replace("www.", "").split('.')[0].capitalize()

            if not text:
                target_url = url
                for link in soup.find_all('a', href=True):
                    href = link['href'].lower()
                    if any(w in href for w in ['about', 'company', 'story', 'legal', 'who-we-are']):
                        target_url = urllib.parse.urljoin(url, link['href'])
                        break
                
                final_res = scraper.get(target_url, timeout=15)
                final_soup = BeautifulSoup(final_res.content, 'html.parser')
                for s in final_soup(["script", "style", "noscript"]): s.extract()
                scraped_content = final_soup.get_text(separator=' ')[:15000]
        except:
            pass

    # 2. Whois Check
    domain_years = "Unknown"
    if HAS_WHOIS and url:
        try:
            domain_name = urllib.parse.urlparse(url).netloc
            w = whois.whois(domain_name)
            c_date = w.creation_date[0] if isinstance(w.creation_date, list) else w.creation_date
            domain_years = (datetime.now() - c_date).days // 365
        except: pass

    # 3. Gemini Prompt with Advanced Vetting Logic
    prompt = f"""
    Analyze this merchant for Klook/GYG onboarding.
    URL: {url}
    CONTENT: {scraped_content[:10000]}
    
    TASK:
    1. Categories - Find ALL offerings and classify them STRICTLY into:
       - 'approve_categories_found': Only use "Attraction tickets", "Recurring shows", "Theme park", "Water park", "Transportation pass".
       - 'red_flag_categories_found': Only use "Food tours", "Dining experiences", "Private tours", "Walking tours", "Bus/Car/Boat tours", "Hiking & trekking", "ATV & All Wheel Drive", "Air tours", "ATV/All Wheel Drive tours", "Bicycle tours", "Food tours", "Food coupons", "Hop-on Hop-off bus", "Kayaking tours", "Multiday tours", "Outlet tours", "Private transfers", "Railway tours", "Shore excursions", "Ski tours", "Spa/Beauty", "Wifi & SIM".
       - 'other_categories_found': List ANY other activities they offer not listed above.
    2. Assess legitimacy (1-100) and provide a 'score_reason'.
    3. Make a final decision ('Approved' or 'Rejected').
    4. Provide a 'status_reason' explaining the Approved/Rejected decision.
    
    Return JSON:
    {{
        "merchant_name": "Extracted Name",
        "legitimacy_score": 1-100,
        "score_reason": "Explain why this score was given...",
        "preferred_categories_found": ["Category 1"],
        "red_flag_categories_found": ["Category 2"],
        "other_categories_found": ["Category 3"],
        "status": "Approved" or "Rejected",
        "status_reason": "Explain why approved or rejected based on categories...",
        "red_flags": ["General concern 1"],
        "strengths": ["Positive 1"],
        "summary": "Overview"
    }}
    """
    
    # 4. ROTATION LOOP (Tries keys until one works)
    shuffled_keys = list(keys)
    random.shuffle(shuffled_keys)
    last_error = ""

    for key in shuffled_keys:
        try:
            model_name = get_working_model_name(key)
            genai.configure(api_key=key)
            model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
            
            response = model.generate_content(prompt)
            
            # Bulletproof JSON Parsing
            clean_json = response.text.strip()
            if clean_json.startswith("```json"): clean_json = clean_json[7:]
            if clean_json.endswith("```"): clean_json = clean_json[:-3]
            
            res_data = json.loads(clean_json.strip())
            res_data["domain_age"] = domain_years
            
            if not res_data.get("merchant_name"): 
                res_data["merchant_name"] = inferred_name
                
            # --- STRICT RULE: MATH-BASED APPROVAL ---
            pref_list = res_data.get("preferred_categories_found", [])
            red_list = res_data.get("red_flag_categories_found", [])
            
            if not isinstance(pref_list, list): pref_list = []
            if not isinstance(red_list, list): red_list = []
            
            pref_count = len(pref_list)
            red_count = len(red_list)
            ai_reason = res_data.get("status_reason", "")
            
            if pref_count > red_count:
                res_data["status"] = "Approved"
                res_data["status_reason"] = f"Rule Auto-Approval: Found {pref_count} preferred vs {red_count} red-flag verticals. (AI notes: {ai_reason})"
            elif red_count > pref_count:
                res_data["status"] = "Rejected"
                res_data["status_reason"] = f"Rule Auto-Rejection: Found {red_count} red-flag vs {pref_count} preferred verticals. (AI notes: {ai_reason})"
            else:
                res_data["status_reason"] = f"Tie-Breaker (AI Decision): Equal categories found ({pref_count}). Reason: {ai_reason}"

            return res_data # Success! Break the loop.

        except Exception as e:
            last_error = str(e)
            time.sleep(0.5) # Wait half a second, then try the next key
            continue 
            
    return {"error": f"AI Audit Failed on all keys. Last Error: {last_error}", "merchant_name": inferred_name}

# --- IMAGE RESIZING LOGIC (ENHANCED FOR QUALITY DIAGNOSTICS & BASE64) ---
def resize_image_klook_standard(image_input, alignment=(0.5, 0.5)):
    if Image is None: return None, 0, 0, "⚠️ Error: 'Pillow' library missing.", None
    try:
        if isinstance(image_input, bytes):
            img = Image.open(io.BytesIO(image_input))
        else:
            img = Image.open(image_input)
            
        orig_w, orig_h = img.size
            
        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[3]) 
            img = background
        else:
            img = img.convert('RGB')

        target_width = 1280
        target_height = 800
        img_resized = ImageOps.fit(img, (target_width, target_height), method=Image.Resampling.LANCZOS, centering=alignment)
        
        buf = io.BytesIO()
        img_resized.save(
            buf, 
            format='JPEG', 
            quality=95,            
            subsampling=0,        
            optimize=True         
        )
        
        # 💥 NEW: Convert to Base64 for the Extension 💥
        image_bytes = buf.getvalue()
        b64_encoded = base64.b64encode(image_bytes).decode('utf-8')
        b64_string = f"data:image/jpeg;base64,{b64_encoded}"

        return image_bytes, orig_w, orig_h, None, b64_string
    except Exception as e:
        return None, 0, 0, f"Error processing image: {e}", None

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

# --- SCRAPER (ROBUST + HIGH RES IMAGES) ---
@st.cache_data(ttl=3600, show_spinner=False)
def extract_data_from_url(url):
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0'
    ]
    
    headers = {
        'User-Agent': random.choice(user_agents),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.google.com/'
    }

    try:
        try:
            scraper = cloudscraper.create_scraper(
                browser={'browser': 'chrome','platform': 'windows','desktop': True}
            )
            scraper.mount('https://', LegacySSLAdapter())
            response = scraper.get(url, headers=headers, timeout=30) 
        except Exception:
            response = requests.get(url, headers=headers, timeout=30, verify=False) 

        if response.status_code == 403:
            return None, "⛔ **Access Denied (403):** This website has a strong firewall. Please copy the text manually and use the **'✍🏻 Text Summary'** tab."
            
        if response.status_code != 200: 
            return None, f"ERROR: Status Code {response.status_code}"
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        found_images = []
        for img in soup.find_all('img'):
            src = img.get('data-src') or img.get('data-original') or img.get('src')
            if img.get('srcset'):
                try:
                    src = img.get('srcset').split(',')[-1].strip().split(' ')[0]
                except: pass
            
            if src:
                if src.startswith('//'): src = 'https:' + src
                elif src.startswith('/'): src = urllib.parse.urljoin(url, src)
                if not any(x in src.lower() for x in ['logo', 'icon', 'avatar', 'svg', 'blank', 'transparent']):
                    if src not in found_images:
                        found_images.append(src)
        found_images = found_images[:15]

        for script in soup(["script", "style", "noscript", "svg"]): 
            script.extract()
        text = soup.get_text(separator=' \n ')
        lines = (line.strip() for line in text.splitlines())
        clean_text = '\n'.join(line for line in lines if line)[:100000] 
        
        return {"text": clean_text, "images": found_images}, None

    except Exception as e: 
        return None, f"CONNECTION ERROR: {str(e)}\n\n💡 Tip: This site might be blocking bots. Try pasting the text manually in the 'Text Summary' tab."

# --- ROBUST PDF READER ---
def extract_text_from_pdf(uploaded_file):
    text = ""
    error_log = ""
    
    if HAS_PDFPLUMBER:
        try:
            with pdfplumber.open(uploaded_file) as pdf:
                for page in pdf.pages:
                    extracted = page.extract_text()
                    if extracted: text += extracted + "\n"
            if len(text) > 10: return text[:100000]
        except Exception as e:
            error_log += f"Plumber failed: {str(e)}. "

    if HAS_PYPDF:
        try:
            uploaded_file.seek(0)
            reader = PdfReader(uploaded_file)
            for page in reader.pages:
                try: text += page.extract_text() + "\n"
                except: pass 
            if len(text) > 10: return text[:100000]
        except Exception as e:
            error_log += f"PyPDF failed: {str(e)}."
            
    if not text:
        return f"⚠️ Error reading PDF. Please install 'pdfplumber' for better support.\nDetails: {error_log}"
    
    return text[:100000]

# --- PDF GENERATOR ---
def create_pdf(data):
    if not HAS_REPORTLAB:
        return None
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=16, spaceAfter=12, textColor=colors.darkorange)
    heading_style = ParagraphStyle('Heading', parent=styles['Heading2'], fontSize=12, spaceBefore=10, spaceAfter=6, textColor=colors.black)
    body_style = styles['BodyText']
    bullet_style = ParagraphStyle('Bullet', parent=styles['BodyText'], leftIndent=20)

    info = data.get('basic_info', {})
    story.append(Paragraph(f"{info.get('main_attractions', 'Tour Summary')}", title_style))
    story.append(Paragraph(f"<b>Location:</b> {info.get('city_country')} | <b>Duration:</b> {info.get('duration')}", body_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph("✨ Highlights", heading_style))
    highlights = info.get('highlights', [])
    if highlights:
        bullets = [ListItem(Paragraph(h, body_style)) for h in highlights]
        story.append(ListFlowable(bullets, bulletType='bullet', start='•'))

    story.append(Paragraph("📝 What to Expect", heading_style))
    story.append(Paragraph(info.get('what_to_expect', ''), body_style))

    story.append(Paragraph("🗺️ Itinerary", heading_style))
    itin = data.get('klook_itinerary', {})
    segments = itin.get('segments', [])
    start = itin.get('start', {})
    story.append(Paragraph(f"<b>{start.get('time', '')}</b> - Start at {start.get('location', '')}", body_style))
    for seg in segments:
        text = f"<b>{seg.get('time', '')}</b> - {seg.get('type')}: {seg.get('name')}"
        if seg.get('details'): text += f"<br/><i>{seg.get('details')}</i>"
        story.append(Paragraph(text, bullet_style))
    end = itin.get('end', {})
    story.append(Paragraph(f"<b>{end.get('time', '')}</b> - End at {end.get('location', '')}", body_style))

    inc = data.get('inclusions', {})
    story.append(Paragraph("✅ Included", heading_style))
    if inc.get('included'):
        bullets = [ListItem(Paragraph(x, body_style)) for x in inc.get('included', [])]
        story.append(ListFlowable(bullets, bulletType='bullet', start='•'))
    story.append(Paragraph("❌ Excluded", heading_style))
    if inc.get('excluded'):
        bullets = [ListItem(Paragraph(x, body_style)) for x in inc.get('excluded', [])]
        story.append(ListFlowable(bullets, bulletType='bullet', start='•'))

    doc.build(story)
    return buffer.getvalue()


# --- SMART MODEL FINDER (FIXED WITH MEMORY CACHE) ---
# This stops the script from wasting API calls by caching the correct model!
@st.cache_data(ttl=86400, show_spinner=False)
def get_working_model_name(api_key):
    genai.configure(api_key=api_key)
    try:
        models = genai.list_models()
        available_models = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        
        # Will look for 1.5 or 2.5 flash automatically
        priority_list = ["gemini-1.5-flash", "gemini-2.5-flash", "gemini-1.5-pro"]
        for pref in priority_list:
            for model in available_models:
                if pref in model: return model
                
        return available_models[0] if available_models else "gemini-1.5-flash"
    except: 
        return "gemini-1.5-flash"
        
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

# --- GEMINI CALLS (UPDATED PROMPT) ---
def call_gemini_json_summary(text, api_key, target_lang="English"):
    model_name = get_working_model_name(api_key)
    if not model_name: return "Error: No available Gemini models found."
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
    
    intro_prompt = f"""
    You are a content specialist for Klook.
    **TASK:** Convert tour text into strict JSON.
    **OUTPUT LANGUAGE:** {target_lang}
    
    **CRITICAL RULE - ROMAN CHARACTERS ONLY:**
    If translating to English, you MUST use strict ASCII/Roman characters (A-Z).
    - Remove accents: 'ñ' -> 'n', 'é' -> 'e'.
    
    **CRITICAL ACCURACY RULES:**
    1. **NO HALLUCINATION:** If pickup info or duration is not in the text, return "To be confirmed".
    2. **STRICT LENGTH:** 'what_to_expect' MUST be between **100-120 words**. Count your words.
    3. **NO FULL STOP:** The 'what_to_expect' paragraph MUST NOT end with a full stop (period).
    
    **HIGHLIGHTS RULES (STRICT):**
    - **LENGTH:** Each bullet point must be **STRICTLY 10-12 words long**.
    - **QUANTITY:** Generate exactly 4 bullet points.
    - **NO FULL STOP:** Do NOT end highlights with a full stop/period.
    - Must be specific to the activity.
    
    **SELLING POINTS:**
    - Select EXACTLY 3-5 tags from the list below. Do NOT invent new ones.
    - List: {SELLING_POINTS_LIST}
    
**SETTINGS DATA (CRITICAL - READ CAREFULLY):**
    - 'group_type': Infer from text. Choose ONLY one: 'Private', 'Join-in (small group)', or 'Join-in (big group)'.
    - 'min_pax': Look for explicit minimum booking requirements. If not found, return "Check with Merchant".
    - 'max_pax': Look for explicit maximum capacity limits. If not found, return "Check with Merchant". DO NOT invent or default to any numbers.
    
    **ITINERARY & TIMING:**
    - **Start Time:** If a range is given (e.g., "Pickup 7:00am - 8:00am"), extract the **START** time (e.g., "07:00"). Do NOT average them.
    - **Format:** Use HH:MM format (24-hour clock).
    
    **PRICING EXTRACTION:**
    - Look for Adult, Child, and Infant prices. Extract as numbers.
    - Detect Currency Code.
    
    **REQUIRED JSON STRUCTURE:**
    {{
        "basic_info": {{
            "city_country": "City, Country",
            "group_type": "Private/Join-in (small group)/Join-in (big group)",
            "min_pax": "1",
            "max_pax": "15",
            "duration": "Duration",
            "main_attractions": "Tour Name",
            "highlights": ["Highlight 1 (10-12 words)", "Highlight 2 (10-12 words)", "Highlight 3", "Highlight 4"],
            "what_to_expect": "Strictly 100-120 words. No final full stop",
            "selling_points": ["Tag 1", "Tag 2"]
        }},
        "klook_itinerary": {{
            "start": {{ "time": "09:00", "location": "Meeting Point" }},
            "segments": [
                {{ "type": "Attraction", "time": "10:00", "name": "Name", "details": "Details", "location_search": "Search Term", "ticket_status": "Free/Ticket" }}
            ],
            "end": {{ "time": "17:00", "location": "Drop off" }}
        }},
        "policies": {{ "cancellation": "Policy", "merchant_contact": "+X-XXX-XXX-XXXX" }},
        "inclusions": {{ "included": ["Item 1"], "excluded": ["Item 2"] }},
        "restrictions": {{ "child_policy": "Details", "accessibility": "Details", "faq": ["FAQ content"] }},
        "seo": {{ "keywords": ["Key 1"] }},
        "pricing": {{ 
            "details": "Original text string",
            "currency": "USD",
            "adult_price": 0.0,
            "child_price": 0.0,
            "infant_price": 0.0
        }},
        "analysis": {{ "ota_search_term": "Product Name" }}
    }}
    **INPUT TEXT:**
    """
    try:
        response = model.generate_content(intro_prompt + sanitize_text(text))
        return response.text
    except ResourceExhausted: return "429_LIMIT"
    except Exception as e: return f"AI Error: {str(e)}"

# --- REGENERATE DESCRIPTION ONLY ---
def regenerate_description_only(text, api_key, lang="English"):
    model_name = get_working_model_name(api_key)
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""
    Write a 'What to Expect' summary for this tour.
    **CRITICAL RULES:**
    1. STRICTLY 100-120 words. Count carefully.
    2. Do NOT end with a full stop/period.
    3. Language: {lang}
    4. Text only. No JSON.
    
    **INPUT TEXT:**
    {sanitize_text(text)}
    """
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except: return "Error regenerating description."

# --- GRAMMAR CHECKER FUNCTION (UPDATED FOR ERROR LISTING) ---
def fix_grammar_american(text, keys):
    if not keys: return {"error": "AI Error: No API keys found."}
    
    prompt = f"""
    Act as a professional editor.
    Task: Correct the grammar, spelling, and punctuation of the following text.
    Standard: American English.
    Constraint: Keep the original tone and meaning.
    
    Return strict JSON in this format:
    {{
        "corrected_text": "The full corrected text here.",
        "errors_found": [
            {{"original": "wrong word or phrase", "correction": "right word", "reason": "Why it was changed"}}
        ]
    }}
    
    Input Text:
    {text}
    """
    
    shuffled_keys = list(keys)
    random.shuffle(shuffled_keys)
    last_error = ""
    
    for key in shuffled_keys:
        try:
            model_name = get_working_model_name(key)
            genai.configure(api_key=key)
            # Force JSON output so we can separate the text and the error list
            model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
            
            response = model.generate_content(prompt)
            
            clean_json = response.text.strip()
            if clean_json.startswith("```json"): clean_json = clean_json[7:]
            if clean_json.endswith("```"): clean_json = clean_json[:-3]
            
            res_data = json.loads(clean_json.strip())
            
            # Remove trailing period if present (matching your previous logic)
            if res_data.get("corrected_text", "").endswith("."):
                res_data["corrected_text"] = res_data["corrected_text"][:-1]
                
            return res_data 
            
        except Exception as e:
            last_error = str(e)
            time.sleep(0.5) 
            continue 
            
    return {"error": f"AI Error: All keys exhausted. Last error: {last_error}"}

# --- EMAIL DRAFTER ---
def call_gemini_email_draft(json_data, api_key):
    model_name = get_working_model_name(api_key)
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    prompt = f"Draft a concise GAP ANALYSIS email. Request MISSING info only. Data: {json.dumps(json_data)}"
    try:
        response = model.generate_content(prompt)
        return response.text
    except: return "Error generating email."

# --- CAPTION GENERATOR ---
def call_gemini_caption(image_bytes, api_key, context_str=""):
    model_name = get_working_model_name(api_key)
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    prompt = f"Social media caption (10-12 words, experiential verb start, NO full stop, no emojis). Context: '{context_str}'"
    try:
        response = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": image_bytes}])
        return response.text
    except: return "Caption Failed"

# --- HELPER: RENDER COPY BOX ---
def copy_box(label, text, height=None):
    if not text: return
    safe_text = romanize_text(str(text)) if text else ""
    st.caption(f"**{label}**")
    st.code(safe_text, language="text") 

# --- POPUP DIALOG FUNCTION ---
@st.dialog("📋 Full Data for Copy-Paste")
def show_copy_dialog(data):
    info = data.get("basic_info", {})
    itin = data.get("klook_itinerary", {})
    pol = data.get("policies", {})
    res = data.get("restrictions", {})
    seo = data.get("seo", {})
    inc = data.get("inclusions", {})
    
    st.info("💡 Scroll down to see all sections.")
    def clean(t): return romanize_text(str(t)) if t else ""

    st.subheader("1. Basic Information")
    st.caption("**Activity Name**")
    st.code(clean(info.get('main_attractions')), language='text')
    st.caption("**Highlights**")
    hl_text = "\n".join([f"• {clean(h)}" for h in info.get('highlights', [])])
    st.code(hl_text, language='text')
    st.caption("**Description**")
    st.code(clean(info.get('what_to_expect')), language='text')
    st.caption("**Duration**")
    st.code(clean(info.get('duration')), language='text')
    st.caption("**Selling Points**")
    sp_text = ", ".join([clean(s) for s in info.get('selling_points', [])])
    st.code(sp_text, language='text')

    st.divider()
    st.subheader("2. Itinerary Details")
    start = itin.get('start', {})
    end = itin.get('end', {})
    segments = itin.get('segments', [])
    itin_text = f"START: {clean(start.get('time'))} - {clean(start.get('location'))}\n\n"
    for seg in segments:
        itin_text += f"{clean(seg.get('time'))} - {clean(seg.get('type'))}: {clean(seg.get('name'))}\n"
        if seg.get('details'): itin_text += f"    ({clean(seg.get('details'))})\n"
    itin_text += f"\nEND: {clean(end.get('time'))} - {clean(end.get('location'))}"
    st.code(itin_text, language='text')

    st.divider()
    st.subheader("3. Policies & Restrictions")
    st.caption("**Inclusions**")
    inc_text = "\n".join([f"• {clean(x)}" for x in inc.get('included', [])])
    st.code(inc_text, language='text')
    st.caption("**Exclusions**")
    exc_text = "\n".join([f"• {clean(x)}" for x in inc.get('excluded', [])])
    st.code(exc_text, language='text')
    st.caption("**Cancellation Policy**")
    st.code(clean(pol.get('cancellation')), language='text')
    st.caption("**Child Policy**")
    st.code(clean(res.get('child_policy')), language='text')

    st.divider()
    st.subheader("4. SEO & Contact")
    st.code(clean(str(seo.get("keywords", []))), language='text')
    st.code(clean(pol.get('merchant_contact')), language='text')

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
        if "basic_info" in data and "main_attractions" in data["basic_info"]:
            st.session_state['product_context'] = data["basic_info"]["main_attractions"]
    except:
        st.warning("⚠️ Formatting Issue. See 'Raw Response' below.")
        st.code(json_text)
        return
        
    info = data.get("basic_info", {})
    inc = data.get("inclusions", {})
    pol = data.get("policies", {})
    seo = data.get("seo", {})
    price_data = data.get("pricing", {})

    st.success("✅ Analysis Complete!")
    if st.button("🚀 Open Full Data Popup", type="primary", use_container_width=True):
        show_copy_dialog(data)
    st.divider()

    with st.sidebar:
        st.header("📋 Copy Dashboard")
        copy_box("📍 Location", info.get('city_country'))
        copy_box("🏷️ Name", info.get('main_attractions'))
        copy_box("📞 Phone", pol.get('merchant_contact'))
        st.divider()
        if HAS_REPORTLAB:
            pdf_data = create_pdf(data)
            if pdf_data:
                st.download_button("📄 Download Summary PDF", pdf_data, f"Klook_Summary_{int(time.time())}.pdf", "application/pdf")

    tab_names = ["ℹ️ Basic Info", "⏰ Start & End", "🗺️ Klook Itinerary", "📜 Policies", "✅ Inclusions", "🚫 Restrictions", "🔍 SEO", "💰 Price", "📊 Analysis", "📧 Supplier Email", "🔧 Automation"]
    tabs = st.tabs(tab_names)

    with tabs[0]:
        st.write(f"**📍 Location:** {info.get('city_country')}")
        st.write(f"**⏳ Duration:** {info.get('duration')}")
        st.write(f"**👥 Group:** {info.get('group_type')}")
        
        # NEW MIN/MAX DISPLAY
        c_min, c_max = st.columns(2)
        c_min.metric("📉 Min Pax", info.get('min_pax', 'Check with Merchant'))
        c_max.metric("📈 Max Pax", info.get('max_pax', 'Check with Merchant'))
        
        st.divider()
        st.write("**🌟 Highlights:**")
        for h in info.get("highlights", []): st.write(f"- {h}")
        st.write("**🏷️ Selling Points:**")
        st.write(", ".join(info.get("selling_points", [])))
        
        st.divider()
        
        # WORD COUNT + REGENERATE BUTTON
        wte_text = info.get("what_to_expect", "")
        wte_count = len(wte_text.split())
        
        c1, c2 = st.columns([3, 1])
        with c1:
            st.info(f"📝 **What to Expect** ({wte_count} words):")
        with c2:
            if st.button("🔄 Regenerate Description"):
                keys = get_all_keys()
                if keys and st.session_state['raw_text_content']:
                    with st.spinner("Rewriting..."):
                        new_desc = regenerate_description_only(st.session_state['raw_text_content'], random.choice(keys), "English") # Uses current lang default
                        # Clean last period again just in case
                        if new_desc.endswith("."): new_desc = new_desc[:-1]
                        
                        # Update session state
                        data_obj = json.loads(st.session_state['gen_result'])
                        data_obj["basic_info"]["what_to_expect"] = new_desc
                        st.session_state['gen_result'] = json.dumps(data_obj)
                        st.rerun()
        
        st.write(wte_text)

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
        segments = itin.get("segments", [])
        st.markdown(f"""<div class="timeline-step" style="border-left-color: #4CAF50;"><span class="timeline-time">{start.get('time')}</span><br><span class="timeline-title">🏁 Departure Info</span><br><span style="font-size:0.9rem">{start.get('location')}</span></div>""", unsafe_allow_html=True)
        for seg in segments:
            sType = seg.get('type', 'Attraction')
            sName = seg.get('name', 'Activity')
            sTime = seg.get('time', '')
            sDet = seg.get('details', '')
            sTicket = seg.get('ticket_status', 'Unknown')
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
    
    with tabs[7]:
        st.header("💰 Price & Margin Calculator")
        st.subheader("🔎 Extracted from Website")
        cur = price_data.get('currency', 'USD')
        p_adult = price_data.get('adult_price', 0.0)
        p_child = price_data.get('child_price', 0.0)
        p_infant = price_data.get('infant_price', 0.0)
        c1, c2, c3 = st.columns(3)
        c1.metric("Adult Price", f"{cur} {p_adult}")
        c2.metric("Child Price", f"{cur} {p_child}")
        c3.metric("Infant Price", f"{cur} {p_infant}")
        st.caption(f"Raw Details: {price_data.get('details', '')}")
        st.divider()
        st.subheader("🧮 Net Rate Calculator")
        calc_price = st.number_input("🏷️ Merchant Public Price", min_value=0.0, value=float(p_adult) if p_adult else 100.0, step=1.0)
        margin_pct = st.number_input("📉 Target Margin (%)", min_value=0.0, max_value=100.0, value=20.0, step=0.5)
        net_rate = calc_price * (1 - (margin_pct / 100))
        profit = calc_price - net_rate
        k1, k2, k3 = st.columns(3)
        k1.metric("🛒 Klook Sell Price", f"{calc_price:,.2f}")
        k2.metric("💵 Net Rate (Cost)", f"{net_rate:,.2f}")
        k3.metric("📈 Profit / Booking", f"{profit:,.2f}")
    
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
        
        # Create a copy of the data specifically for the extension
        extension_payload = data.copy()
        
        # If there are processed images in the session memory, pack them in!
        if st.session_state.get('processed_images_data'):
            formatted_photos = []
            for item in st.session_state['processed_images_data']:
                formatted_photos.append({
                    "filename": item["fname"],
                    "caption": item["caption"],
                    "base64": item.get("b64_string", "") # Add the Base64 string
                })
            
            # Attach the array directly to the payload
            extension_payload["processed_photos"] = formatted_photos
            
        st.code(json.dumps(extension_payload, indent=4), language="json")

# --- SMART ROTATION (FIXED ERROR EXPOSURE) ---
def smart_rotation_wrapper(text, keys, lang="English"):
    if not keys: return "⚠️ No API keys found."
    
    shuffled_keys = list(keys)
    random.shuffle(shuffled_keys)
    last_error = ""
    
    for attempt in range(2): # Give the whole list of keys 2 full attempts
        for key in shuffled_keys:
            result = call_gemini_json_summary(text, key, lang)
            
            # If it's a quota error, log it and instantly try the next key
            if result == "429_LIMIT" or "429" in str(result):
                last_error = "429 Quota Exceeded on this key."
                time.sleep(0.5)
                continue
            
            # If it is another AI error (like 404), log it and try next key
            if "Error" in str(result):
                last_error = result
                continue
                
            # SUCCESS! Process the JSON
            try:
                # Clean up markdown formatting if the AI added it
                clean_result = result.replace("```json", "").replace("```", "").strip()
                d = json.loads(clean_result)
                
                if "basic_info" in d and "highlights" in d["basic_info"]:
                    d["basic_info"]["highlights"] = [h.rstrip('.') for h in d["basic_info"]["highlights"]]
                
                if "basic_info" in d and "what_to_expect" in d["basic_info"]:
                    wte = d["basic_info"]["what_to_expect"]
                    if wte.endswith("."): wte = wte[:-1]
                    d["basic_info"]["what_to_expect"] = wte
                
                return json.dumps(d)
            except: 
                pass
            
            return result
            
    # If all keys fail, it will now tell you EXACTLY why!
    return f"⚠️ AI Failed. Last Error: {last_error}"


# --- MAIN APP LOGIC ---
with st.sidebar:
    st.header("⚙️ Settings")
    target_lang = st.selectbox("🌐 Target Language", ["English", "Chinese (Traditional)", "Chinese (Simplified)", "Korean", "Japanese", "Thai", "Vietnamese", "Indonesian"])
    st.divider()

t1, t2, t3, t4, t5, t6, t7 = st.tabs(["🧠 Link Summary", "✍🏻 Text Summary", "📄 PDF Summary", "🖼️ Photo Resizer", "🛡️ Merchant Screening Tool", "📝 Grammar Check", "🔎 Klook Search"])

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
            st.session_state['raw_text_content'] = data_dict['text'] 
            
            status.write(f"✅ Found {len(data_dict['images'])} images & {len(data_dict['text'])} chars. Calling AI...")
            result = smart_rotation_wrapper(data_dict['text'], keys, target_lang)
            
            if "Busy" not in result and "Error" not in result:
                st.session_state['gen_result'] = result
                st.session_state['url_input'] = url
            
            if "Busy" in result or "Error" in result or "Failed" in result:
                status.update(label="❌ AI Failed", state="error")
                st.error(result)
            else:
                status.update(label="✅ Complete!", state="complete")

with t2:
    raw_text = st.text_area("Paste Tour Text")
    if st.button("Generate from Text"):
        keys = get_all_keys()
        if not keys: st.error("❌ No Keys"); st.stop()
        st.session_state['raw_text_content'] = raw_text 
        result = smart_rotation_wrapper(raw_text, keys, target_lang)
        if "Busy" not in result and "Error" not in result and "Failed" not in result:
            st.session_state['gen_result'] = result
            try:
                d = json.loads(result)
                if "basic_info" in d: st.session_state['product_context'] = d["basic_info"].get("main_attractions", "")
            except: pass
        else:
            st.error(result)

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
            
            st.session_state['raw_text_content'] = pdf_text 
            status.write(f"✅ Extracted {len(pdf_text)} chars. Calling AI...")
            result = smart_rotation_wrapper(pdf_text, keys, target_lang)
            
            if "Busy" not in result and "Error" not in result and "Failed" not in result:
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
                try:
                    st.image(img_url, use_column_width=True)
                    if st.checkbox("Select", key=f"img_{i}"):
                        selected_scraped.append(img_url)
                except Exception:
                    st.warning(f"⚠️ Could not load image {i+1}")

    # Use the persistent memory memory for processed images
    if 'processed_images_data' not in st.session_state:
        st.session_state['processed_images_data'] = []
        st.session_state['zip_buffer'] = None

    if st.button("Process Selected Images"):
        keys = get_all_keys()
        total_items = (files if files else []) + selected_scraped
        
        if not total_items:
            st.warning("⚠️ No images selected.")
        else:
            st.session_state['processed_images_data'] = []
            zip_buf = io.BytesIO()
            
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                prog_bar = st.progress(0)
                total_count = len(total_items)
                
                for idx, item in enumerate(total_items):
                    prog_bar.progress((idx + 1) / total_count)
                    
                    if hasattr(item, 'read'): 
                        fname = item.name
                        b_img, orig_w, orig_h, err, b64_str = resize_image_klook_standard(item, align_map[c_align])
                    else: 
                        fname = f"web_image_{idx}.jpg"
                        try:
                            headers = {'User-Agent': 'Mozilla/5.0'}
                            resp = requests.get(item, headers=headers, timeout=10)
                            b_img, orig_w, orig_h, err, b64_str = resize_image_klook_standard(resp.content, align_map[c_align])
                        except: 
                            b_img, b64_str = None, None
                    
                    if b_img:
                        zf.writestr(f"resized_{fname}", b_img)
                        
                        caption_text = ""
                        if enable_captions and keys:
                            caption_text = call_gemini_caption(b_img, random.choice(keys), context_str=manual_context)
                        
                        # 💥 NEW: SAVE BASE64 STRING INTO MEMORY 💥
                        st.session_state['processed_images_data'].append({
                            "fname": fname,
                            "b_img": b_img,
                            "orig_w": orig_w,
                            "orig_h": orig_h,
                            "caption": caption_text,
                            "b64_string": b64_str, 
                            "idx": idx
                        })
                        
            st.session_state['zip_buffer'] = zip_buf.getvalue()
            st.success("✅ All images processed!")

    # DISPLAY SECTION (Now includes quality check info)
    if st.session_state.get('processed_images_data'):
        for item in st.session_state['processed_images_data']:
            c1, c2 = st.columns([1, 2])
            with c1:
                st.image(item["b_img"], caption=item["fname"], use_column_width=True)
            with c2:
                # QUALITY CHECK DIAGNOSTIC BOX
                with st.container(border=True):
                    ow = item.get("orig_w", 0)
                    oh = item.get("orig_w", 0)
                    
                    qc_1, qc_2 = st.columns(2)
                    qc_1.write(f"📏 **Uploaded Size:** {ow} x {oh}")
                    
                    # Decide ifupscaling happened or just standard fit
                    if ow < 1280 or oh < 800:
                         qc_2.error("⚠️ 🔴 Source Low Resolution (Tool had to upscale/stretch the original)")
                    elif ow == 1280 and oh == 800:
                         qc_2.success("✅ Perfect Match (Original was exact standard size)")
                    else:
                         qc_2.info("✅ Standard Fit (Original was large enough, lost slight detail to downscale)")
                
                st.text_area(f"Caption for {item['fname']}", value=item["caption"], height=100, key=f"cap_{item['idx']}")
                
                st.download_button(
                    label=f"⬇️ Download {item['fname']}",
                    data=item["b_img"],
                    file_name=f"resized_{item['fname']}",
                    mime="image/jpeg",
                    key=f"btn_{item['idx']}"
                )
            st.divider()
            
        if st.session_state.get('zip_buffer'):
            st.download_button("⬇️ Download All (ZIP)", st.session_state['zip_buffer'], "klook_images.zip", "application/zip")

# --- TAB 5 UI (UPDATED ADVANCED MERCHANT VALIDATOR) ---
with t5:
    st.header("🛡️ Merchant Risk Assessment")
    m_url = st.text_input("Merchant Website URL", key="m_url")
    m_text = st.text_area("About Us / Business Text (Optional)", key="m_text")
    
    if st.button("🔍 Run Risk Audit"):
        keys = get_all_keys()
        if not keys: st.error("❌ No Keys"); st.stop()
        
        with st.status("🕵️ Auditing Merchant & Checking Categories...", expanded=True) as status:
            risk_res = validate_merchant_risk(m_text, m_url, keys)
            
            if "error" in risk_res and len(risk_res) == 2: 
                 status.update(label="❌ Audit Failed!", state="error")
                 st.error(risk_res["error"])
            else:
                 st.session_state['merchant_result'] = risk_res
                 status.update(label="✅ Audit Complete!", state="complete")

    if st.session_state['merchant_result'] and "legitimacy_score" in st.session_state['merchant_result']:
        res = st.session_state['merchant_result']
        m_name = res.get('merchant_name', 'Merchant')
        status_val = res.get('status', 'Unknown')
        
        # 1. BIG DECISION BANNER
        if status_val.lower() == 'approved':
            st.success(f"### ✅ STATUS: APPROVED \n **Reason:** {res.get('status_reason', '')}")
        else:
            st.error(f"### ❌ STATUS: REJECTED \n **Reason:** {res.get('status_reason', '')}")
            
        st.divider()
        
        # 2. SCORE & MERCHANT INFO
        col1, col2 = st.columns([1, 2])
        with col1:
            st.metric("Legitimacy Score", f"{res.get('legitimacy_score', 0)}/100")
            st.write(f"**Merchant:** {m_name}")
            st.write(f"**Domain Age:** {res.get('domain_age', 'Unknown')} years")
        with col2:
            st.info(f"**Score Breakdown:** \n {res.get('score_reason', 'N/A')}")
            
            st.write("🌐 **OTA Cross-Check (Google)**")
            search_query = urllib.parse.quote(f'"{m_name}"')
            st.link_button("🔵 Find on GetYourGuide", f"https://www.google.com/search?q={search_query}+GetYourGuide")
            st.link_button("🟢 Find on Viator", f"https://www.google.com/search?q={search_query}+Viator")

        st.divider()

        # 3. CATEGORY TRIANGULATION 
        st.subheader("📊 Category Extraction")
        c_pref, c_red, c_other = st.columns(3)
        
        with c_pref:
            st.write("🟢 **Approve Criterias**")
            items = res.get('preferred_categories_found', [])
            if items:
                for c in items: st.success(f"✅ {c}")
            else: st.caption("None found.")
                
        with c_red:
            st.write("🔴 **Reject Criterias**")
            items = res.get('red_flag_categories_found', [])
            if items:
                for c in items: st.error(f"🚩 {c}")
            else: st.caption("None found.")
                
        with c_other:
            st.write("⚪ **Other Criterias**")
            items = res.get('other_categories_found', [])
            if items:
                for c in items: st.info(f"🔹 {c}")
            else: st.caption("None found.")

# --- TAB 6 UI (NEW GRAMMAR CHECKER WITH ERROR LIST) ---
with t6:
    st.header("📝 Grammar Checker (American English)")
    st.info("Paste your text below to correct grammar and check word count.")
    
    text_input = st.text_area("Paste text here:", height=200, key="grammar_input")
    
    if st.button("Fix Grammar & Count Words"):
        keys = get_all_keys()
        if not keys: st.error("❌ No API Keys"); st.stop()
        if not text_input: st.warning("⚠️ Please enter text first."); st.stop()
        
        with st.spinner("Analyzing and Correcting Grammar..."):
            grammar_res = fix_grammar_american(text_input, keys)
            
            if "error" in grammar_res:
                st.error(grammar_res["error"])
            else:
                fixed_text = grammar_res.get("corrected_text", "")
                errors_list = grammar_res.get("errors_found", [])
                
                # Calculate counts
                wc_original = len(text_input.split())
                wc_fixed = len(fixed_text.split())
                char_count = len(fixed_text)
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Original Words", wc_original)
                c2.metric("Result Words", wc_fixed, delta=wc_fixed-wc_original)
                c3.metric("Character Count", char_count)
                
                st.divider()
                
                # Create two columns for the output (2/3 width for text, 1/3 width for errors)
                out_col1, out_col2 = st.columns([2, 1])
                
                with out_col1:
                    st.subheader("✅ Corrected Text")
                    st.text_area("Result (Copy from here):", value=fixed_text, height=250, label_visibility="collapsed")
                
                with out_col2:
                    st.subheader("🔍 Errors Fixed")
                    # Put it inside a scrollable container so it doesn't stretch the page too long
                    with st.container(height=250):
                        if errors_list:
                            for err in errors_list:
                                st.markdown(f"**❌ {err.get('original', '')}** \n**✅ {err.get('correction', '')}** \n*{err.get('reason', '')}*")
                                st.markdown("---")
                        else:
                            st.success("No grammatical errors found! Your text was perfect.")
                            
                st.success("Correction Complete!")

# --- TAB 7 UI (KLOOK SEARCH) ---
with t7:
    st.header("🔎 Activity Similarity Check")
    st.info("Paste a competitor's tour link or type the activity name to check if it already exists on Klook.")
    
    klook_search_input = st.text_input("Paste Tour Link or Name:", key="klook_search_tab")
    
    if klook_search_input:
        query_text = klook_search_input
        
        # SMART PARSER: If it's a URL, extract the slug to make a clean search term
        if klook_search_input.startswith("http"):
            try:
                parsed = urllib.parse.urlparse(klook_search_input)
                path_segments = [seg for seg in parsed.path.split('/') if seg]
                if path_segments:
                    # Grab the last part of the URL (e.g., 'huacachina-and-paracas-tour')
                    slug = path_segments[-1]
                    # Remove file extensions like .html if they exist
                    slug = slug.split('.')[0]
                    # Replace hyphens with spaces and capitalize
                    query_text = slug.replace('-', ' ').replace('_', ' ').title()
                else:
                    query_text = parsed.netloc.replace('www.', '')
            except:
                pass # Fallback to raw text if parsing fails
        
        st.write(f"**Extracted Search Term:** `{query_text}`")
        
        # Generate the Search Links
        encoded_google_term = urllib.parse.quote(f"site:klook.com {query_text}")
        google_klook_url = f"https://www.google.com/search?q={encoded_google_term}"
        
        encoded_direct_term = urllib.parse.quote(query_text)
        direct_klook_url = f"https://www.klook.com/search/result/?query={encoded_direct_term}"
        
        st.markdown("### 🚀 Search Options")
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1: 
            st.link_button("🟠 Google Search (site:klook.com)", google_klook_url, use_container_width=True)
        with c2: 
            st.link_button("🟠 Direct Search on Klook", direct_klook_url, use_container_width=True)
        with c3:
            st.empty() # Empty column just to keep buttons a nice size

# --- ALWAYS RENDER IF DATA EXISTS ---
if st.session_state['gen_result']:
    render_output(st.session_state['gen_result'], st.session_state['url_input'])









