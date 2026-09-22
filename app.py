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
import streamlit.components.v1 as components 

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

# --- STATIC HTML PREVIEW GENERATOR (REPLACES REACT/JSX TO PREVENT CRASHES) ---
def generate_static_html_preview(data):
    b = data.get("basic_info", {})
    it = data.get("klook_itinerary", {})
    packages = data.get("packages", [])
    
    # Safely extract primitive values from basic_info
    title = b.get("activity_title", "Generated Activity")
    city = b.get("city_country", "Location")
    wte = b.get("what_to_expect", "")
    attractions = b.get("main_attractions", "")
    
    # Grab data from the first package as the default display for the UI preview
    pkg_default = packages[0] if packages else {}
    group_type = pkg_default.get("group_type", "Join-in")
    duration = pkg_default.get("duration", "TBC")
    pri = pkg_default.get("pricing", {})
    currency = pri.get("currency", "USD")
    adult_price = pri.get("adult_price", 0)
    inc = pkg_default.get("inclusions", {})
    
    # Generate Highlights HTML
    hl_list = b.get("highlights", [])
    if isinstance(hl_list, list):
        hl_html = "".join([f'<li class="flex gap-2"><span class="text-gray-400 mt-1">•</span><span>{h}</span></li>' for h in hl_list])
    else:
        hl_html = ""

    # Generate Selling Points HTML
    sp_list = b.get("selling_points", [])
    if isinstance(sp_list, list):
        sp_html = "".join([f'<span class="text-xs bg-gray-100 text-gray-600 px-2.5 py-1 rounded-full">{s}</span>' for s in sp_list])
    else:
        sp_html = ""

    # Generate Inclusions/Exclusions HTML (from first package)
    inc_list = inc.get("included", [])
    if isinstance(inc_list, list):
        inc_html = "".join([f'<li>{i}</li>' for i in inc_list])
    else:
        inc_html = ""
        
    exc_list = inc.get("excluded", [])
    if isinstance(exc_list, list):
        exc_html = "".join([f'<li>{i}</li>' for i in exc_list])
    else:
        exc_html = ""

    # Generate Itinerary HTML
    seg_list = it.get("segments", [])
    seg_html = ""
    if isinstance(seg_list, list):
        for seg in seg_list:
            seg_html += f"""
            <div class="border-l-2 border-orange-200 pl-3 mb-4">
                <p class="text-xs text-gray-400">{seg.get('time', 'TBC')} · {seg.get('type', 'Activity')}</p>
                <p class="text-sm font-medium text-gray-900">{seg.get('name', 'Location')}</p>
                <p class="text-xs text-gray-600 mt-1">{seg.get('details', '')}</p>
            </div>
            """

    start_loc = it.get("start", {}).get("location", "Meeting Point")
    start_time = it.get("start", {}).get("time", "TBC")
    end_loc = it.get("end", {}).get("location", "Drop-off Point")
    end_time = it.get("end", {}).get("time", "TBC")

    res = data.get("restrictions", {})
    pol = data.get("policies", {})

    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script src="https://cdn.tailwindcss.com"></script>
        <style>body {{ background-color: #ffffff; font-family: ui-sans-serif, system-ui, sans-serif; }}</style>
    </head>
    <body class="p-6">
        <div class="max-w-[1200px] mx-auto text-gray-900">
            <nav class="flex flex-wrap items-center gap-1 text-xs text-gray-500 mb-3">
                <span>Home</span> <span class="mx-1">›</span>
                <span>{city}</span> <span class="mx-1">›</span>
                <span>Things to do</span> <span class="mx-1">›</span>
                <span class="text-gray-400 truncate max-w-[220px]">{title}</span>
            </nav>
            
            <h1 class="text-[28px] font-bold text-gray-900 leading-tight">{title}</h1>
            
            <div class="flex flex-wrap items-center gap-2 mt-2 text-xs">
                <span class="flex items-center gap-1 bg-violet-50 text-violet-600 font-medium px-2 py-1 rounded">🛡️ Klook's choice</span>
                <span class="flex items-center gap-1 text-emerald-600 font-medium px-2 py-1">🌿 Certified Sustainable Partner</span>
                <span class="text-gray-500 px-2 py-1 border-l border-gray-200">English</span>
                <span class="text-gray-500 px-2 py-1 border-l border-gray-200">{group_type}</span>
            </div>
            
            <div class="flex flex-wrap gap-2 mt-3">
                <span class="bg-gray-100 text-gray-700 text-xs px-3 py-1.5 rounded-md">Meet with guide</span>
                <span class="bg-gray-100 text-gray-700 text-xs px-3 py-1.5 rounded-md">{duration} Duration</span>
            </div>

            <div class="grid grid-cols-3 grid-rows-2 gap-1 rounded-xl overflow-hidden mt-6 h-[260px] sm:h-[380px]">
                <div class="row-span-2 col-span-1"><img src="https://picsum.photos/seed/klook1/900/700" class="w-full h-full object-cover" /></div>
                <img src="https://picsum.photos/seed/klook2/500/340" class="w-full h-full object-cover" />
                <img src="https://picsum.photos/seed/klook3/500/340" class="w-full h-full object-cover" />
                <img src="https://picsum.photos/seed/klook4/500/340" class="w-full h-full object-cover" />
                <div class="relative">
                    <img src="https://picsum.photos/seed/klook5/500/340" class="w-full h-full object-cover" />
                </div>
            </div>

            <div class="flex flex-col lg:flex-row gap-6 mt-6">
                <div class="flex-1 min-w-0">
                    <div class="bg-orange-50 border border-orange-100 rounded-xl p-5 flex items-start justify-between gap-4">
                        <div>
                            <ul class="space-y-2 text-sm text-gray-800">
                                {hl_html}
                            </ul>
                        </div>
                        <div class="text-3xl hidden sm:block">👍</div>
                    </div>
                    
                    <div class="flex flex-wrap gap-2 mt-4">
                        {sp_html}
                    </div>

                    <section class="mt-10">
                        <div class="flex items-center gap-2 mb-4"><span class="w-1 h-5 bg-orange-500 rounded-sm"></span><h2 class="text-lg font-bold">What to expect</h2></div>
                        <p class="text-sm text-gray-700 leading-relaxed">{wte}</p>
                        <div class="mt-4 rounded-xl overflow-hidden"><img src="https://picsum.photos/seed/klook6/900/400" class="w-full h-[280px] object-cover" /><p class="text-xs text-gray-500 mt-2">▲ {attractions}</p></div>
                    </section>

                    <section class="mt-10">
                        <div class="flex items-center gap-2 mb-4"><span class="w-1 h-5 bg-orange-500 rounded-sm"></span><h2 class="text-lg font-bold">What's included / excluded</h2></div>
                        <div class="grid sm:grid-cols-2 gap-4 text-sm bg-gray-50 p-5 rounded-xl border border-gray-100">
                            <div>
                                <p class="font-medium text-gray-900 mb-2 flex items-center gap-1.5"><span class="text-emerald-500 font-bold">✓</span> Included</p>
                                <ul class="space-y-1 text-gray-700 list-disc list-inside">
                                    {inc_html}
                                </ul>
                            </div>
                            <div>
                                <p class="font-medium text-gray-900 mb-2 flex items-center gap-1.5"><span class="text-red-500 font-bold">✕</span> Excluded</p>
                                <ul class="space-y-1 text-gray-700 list-disc list-inside">
                                    {exc_html}
                                </ul>
                            </div>
                        </div>
                    </section>

                    <section class="mt-10 mb-8">
                        <div class="flex items-center gap-2 mb-4"><span class="w-1 h-5 bg-orange-500 rounded-sm"></span><h2 class="text-lg font-bold">Good to know</h2></div>
                        <div class="text-sm text-gray-700 space-y-2">
                            <p><span class="font-medium text-gray-900">Child policy: </span>{res.get('child_policy', 'TBC')}</p>
                            <p><span class="font-medium text-gray-900">Accessibility: </span>{res.get('accessibility', 'TBC')}</p>
                            <p><span class="font-medium text-gray-900">Cancellation: </span>{pol.get('cancellation', 'TBC')}</p>
                        </div>
                    </section>
                </div>

                <div class="w-full lg:w-[300px] shrink-0 space-y-4">
                    <div class="border border-gray-200 rounded-xl p-4 lg:sticky lg:top-4 bg-white shadow-sm">
                        <p class="text-xs text-gray-500">From</p>
                        <p class="text-2xl font-bold text-gray-900">{currency} {adult_price}</p>
                        <button class="w-full bg-orange-500 hover:bg-orange-600 text-white font-medium text-sm py-2.5 rounded-lg mt-3">Select options</button>
                    </div>

                    <div class="border border-gray-200 rounded-xl p-4 bg-white shadow-sm">
                        <h3 class="font-semibold text-gray-900">Package details</h3>
                        <div class="flex flex-wrap gap-2 mt-3">
                            <span class="text-xs border border-gray-200 rounded px-2 py-1 text-gray-600">Book now, pay later</span>
                            <span class="text-xs border border-gray-200 rounded px-2 py-1 text-gray-600">Free cancellation</span>
                        </div>
                        
                        <div class="mt-6">
                            <p class="font-semibold text-gray-900 mb-3">Itinerary</p>
                            <div class="flex gap-2 text-sm mb-4">
                                <p>📍 <span class="font-medium">{start_time}</span> · Departure from {start_loc}</p>
                            </div>
                            
                            {seg_html}
                            
                            <div class="flex gap-2 text-sm mt-4">
                                <p>🏁 <span class="font-medium">{end_time}</span> · End at {end_loc}</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return html_template

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
            response = scraper.get(url, headers=headers, timeout=15) 
        except Exception:
            response = requests.get(url, headers=headers, timeout=15, verify=False) 

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
            
        hidden_contacts = []
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if href.startswith('mailto:'): hidden_contacts.append(f"Email: {href.replace('mailto:', '')}")
            if href.startswith('tel:'): hidden_contacts.append(f"Phone: {href.replace('tel:', '')}")
            
        if hasattr(response, 'text'):
            raw_emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', response.text)
            for e in raw_emails:
                e = e.lower()
                if not any(ext in e for ext in ['.png', '.jpg', '.jpeg', '.webp', '.svg', 'sentry', 'w3.org', 'example']):
                    hidden_contacts.append(f"Email: {e}")
            
        text = soup.get_text(separator=' \n ')
        lines = (line.strip() for line in text.splitlines())
        clean_text = '\n'.join(line for line in lines if line)[:35000] 

        hidden_tooltips = []
        for el in soup.find_all(['span', 'i', 'a', 'div', 'button']):
            for attr in ['title', 'aria-label', 'data-tooltip', 'data-content', 'data-original-title']:
                if el.has_attr(attr) and len(el[attr].strip()) > 0:
                    val = el[attr].strip()
                    if len(val) > 3 and not any(x in val.lower() for x in ['close', 'menu', 'search', 'button']):
                        hidden_tooltips.append(f"Hidden Tooltip: {val}")
        
        text = soup.get_text(separator=' \n ')
        lines = (line.strip() for line in text.splitlines())
        clean_text = '\n'.join(line for line in lines if line)[:35000] 
        
        if hidden_contacts:
            clean_text += "\n\n--- MERCHANT CONTACTS FOUND IN CODE ---\n" + "\n".join(list(set(hidden_contacts)))
            
        if hidden_tooltips:
            clean_text += "\n\n--- HIDDEN TOOLTIPS FOUND IN CODE ---\n" + "\n".join(list(set(hidden_tooltips)))
        
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
            if len(text) > 10: return text[:35000]
        except Exception as e:
            error_log += f"Plumber failed: {str(e)}. "

    if HAS_PYPDF:
        try:
            uploaded_file.seek(0)
            reader = PdfReader(uploaded_file)
            for page in reader.pages:
                try: text += page.extract_text() + "\n"
                except: pass 
            if len(text) > 10: return text[:35000]
        except Exception as e:
            error_log += f"PyPDF failed: {str(e)}."
            
    if not text:
        return f"⚠️ Error reading PDF. Please install 'pdfplumber' for better support.\nDetails: {error_log}"
    
    return text[:35000]

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
    packages = data.get('packages', [])
    story.append(Paragraph(f"{info.get('main_attractions', 'Tour Summary')}", title_style))
    story.append(Paragraph(f"<b>Location:</b> {info.get('city_country')} | <b>Packages Found:</b> {len(packages)}", body_style))
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

    doc.build(story)
    return buffer.getvalue()


# --- SMART MODEL FINDER ---
@st.cache_data(ttl=86400, show_spinner=False)
def get_working_model_name(api_key):
    genai.configure(api_key=api_key)
    try:
        models = genai.list_models()
        available_models = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        
        priority_list = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-pro"]
        for pref in priority_list:
            for model in available_models:
                if pref in model: return model
                
        return available_models[0] if available_models else "gemini-2.5-flash"
    except: 
        return "gemini-2.5-flash"
        
def sanitize_text(text):
    if not text: return ""
    text = text.encode('utf-8', 'ignore').decode('utf-8')
    return text.replace("\\", "\\\\")[:35000]

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

# --- GEMINI CALLS (UPDATED PROMPT FOR PACKAGES ARRAY) ---
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
    1. **NO HALLUCINATION:** If pickup info or duration is not in the text, return "To be confirmed". Do NOT use "To be confirmed" for array lists like inclusions/exclusions (use an empty array [] or ["None mentioned"] instead).
    2. **STRICT LENGTH:** 'what_to_expect' MUST be between **100-120 words** AND strictly **UNDER 800 characters**. Count both.
    3. **NO FULL STOP:** The 'what_to_expect' paragraph MUST NOT end with a full stop (period).
    4. **POINT OF VIEW:** NEVER use first-person pronouns ("we", "us", "our"). Replace them with "The operator".
    
    **PACKAGE & TIER EXTRACTION (CRITICAL NEW RULE):**
    - Scan the text for distinct ticket tiers, pricing options, or tour variations (e.g., "Standard", "VIP", "Without Transfer").
    - For EVERY distinct option found, create a separate object inside the `packages` array.
    - If there is only one option, create an array with a single package object named "Standard Package".
    - You must assign specific `group_type`, `min_pax`, `max_pax`, `duration`, `pricing`, and `inclusions` inside EACH package object, as these vary by tier.
    - 'group_type' Logic: If the tour is private, return 'Private'. If shared, check max_pax. <=20 is 'Join-in (small group)', >20 is 'Join-in (big group)'.

    **ITINERARY & TIMING:**
    - Format: Use HH:MM format (24-hour clock).
    - NARRATIVE ITINERARIES: Extract every major location mentioned as its own separate segment. No lazy summaries like "City Tour".
    
    **CONTACT EXTRACTION:**
    - Extract contacts and return as: "Phone: +1 234 567 | Email: info@tour.com".
    
    **ACTIVITY TITLE GENERATION:**
    1. STRICT LIMIT: Maximum 68 characters (including spaces). If over 68, use "&" instead of "and".
    2. Format: <Official Attraction Name> Ticket or <Tour Name> Half-Day Tour or <Locations> One-Day Tour from <City>.

    **REQUIRED JSON STRUCTURE:**
    {{
        "basic_info": {{
            "activity_title": "The exact title generated using the strict rules above",
            "city_country": "City, Country",
            "main_attractions": "Tour Name",
            "highlights": ["Highlight 1 (10-12 words)", "Highlight 2 (10-12 words)", "Highlight 3", "Highlight 4"],
            "what_to_expect": "Strictly 100-120 words and max 800 chars. No final full stop",
            "selling_points": ["Tag 1", "Tag 2"]
        }},
        "packages": [
            {{
                "package_title": "Standard High Tea",
                "duration": "1 hour",
                "group_type": "Join-in (small group)",
                "min_pax": "Extract min pax from text (default '1')",
                "max_pax": "Extract max pax from text (default '20')",
                "pricing": {{ 
                    "details": "Original text string",
                    "currency": "USD",
                    "adult_price": 0.0,
                    "child_price": 0.0,
                    "infant_price": 0.0,
                    "child_age": "0-15"
                }},
                "inclusions": {{ 
                    "included": ["Item 1", "Item 2"], 
                    "excluded": ["Item 3"] 
                }}
            }}
        ],
        "klook_itinerary": {{
            "start": {{ "time": "09:00", "location": "Meeting Point" }},
            "segments": [
                {{ "type": "Attraction", "time": "10:00", "name": "Name", "details": "Details", "location_search": "Search Term", "ticket_status": "Free/Ticket" }}
            ],
            "end": {{ "time": "17:00", "location": "Drop off" }}
        }},
        "policies": {{ "cancellation": "Policy", "merchant_contact": "Email: info@tour.com | Phone: +1 234 567" }},
        "restrictions": {{ "child_policy": "Details", "accessibility": "Details", "what_to_bring": ["Item 1", "Item 2"], "faq": ["FAQ content"] }},
        "seo": {{ "keywords": ["Key 1"] }},
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
    1. STRICTLY 100-120 words AND strictly UNDER 800 characters. Count carefully.
    2. Do NOT end with a full stop/period.
    3. Language: {lang}
    4. Text only. No JSON.
    5. POINT OF VIEW: NEVER use "we", "us", or "our". Always replace them with "The operator".
    6. CONTENT COMPLETENESS: You MUST explicitly mention ALL key destinations, cities, and specific landmarks covered in the tour. Do not leave out secondary locations to save space.
    
    **INPUT TEXT:**
    {sanitize_text(text)}
    """
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except: return "Error regenerating description."

# --- GRAMMAR CHECKER FUNCTION ---
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
            model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
            
            response = model.generate_content(prompt)
            clean_json = response.text.strip()
            if clean_json.startswith("```json"): clean_json = clean_json[7:]
            if clean_json.endswith("```"): clean_json = clean_json[:-3]
            res_data = json.loads(clean_json.strip())
            
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
        img = Image.open(io.BytesIO(image_bytes))
        response = model.generate_content([prompt, img])
        return response.text
    except Exception as e: 
        return f"Caption Failed: {str(e)}"

# --- HELPER: RENDER COPY BOX ---
def copy_box(label, text, height=None):
    if not text: return
    safe_text = romanize_text(str(text)) if text else ""
    st.caption(f"**{label}**")
    st.code(safe_text, language="text") 

# --- POPUP DIALOG FUNCTION (UPDATED FOR PACKAGES) ---
@st.dialog("📋 Full Data for Copy-Paste")
def show_copy_dialog(data):
    info = data.get("basic_info", {})
    packages = data.get("packages", [])
    itin = data.get("klook_itinerary", {})
    pol = data.get("policies", {})
    res = data.get("restrictions", {})
    seo = data.get("seo", {})
    
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
    st.caption("**Selling Points**")
    sp_text = ", ".join([clean(s) for s in info.get('selling_points', [])])
    st.code(sp_text, language='text')

    st.divider()
    st.subheader("📦 Package Tiers")
    for i, p in enumerate(packages):
        st.write(f"**Tier {i+1}: {p.get('package_title')}**")
        pkg_details = f"Duration: {p.get('duration')}\nGroup Type: {p.get('group_type')}\nPax: Min {p.get('min_pax')} - Max {p.get('max_pax')}\n"
        
        inc = p.get("inclusions", {})
        pkg_details += f"\nInclusions:\n" + "\n".join([f"• {clean(x)}" for x in inc.get('included', [])])
        pkg_details += f"\n\nExclusions:\n" + "\n".join([f"• {clean(x)}" for x in inc.get('excluded', [])])
        
        st.code(pkg_details, language='text')

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
    st.caption("**Cancellation Policy**")
    st.code(clean(pol.get('cancellation')), language='text')
    st.caption("**Child Policy**")
    st.code(clean(res.get('child_policy')), language='text')
    st.caption("**What to Bring**")
    wtb_text = "\n".join([f"• {clean(x)}" for x in res.get('what_to_bring', [])])
    st.code(wtb_text, language='text')

    st.divider()
    st.subheader("4. SEO & Contact")
    kw_list = seo.get("keywords", [])
    kw_text = ", ".join(kw_list) if isinstance(kw_list, list) else str(kw_list)
    st.code(clean(kw_text), language='text')
    
    contact_clean = clean(pol.get('merchant_contact')).replace(' | ', '\n').replace('|', '\n')
    st.code(contact_clean, language='text')

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
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
            
        if not isinstance(data, dict):
            raise ValueError("The AI did not return a valid JSON dictionary.")
            
        if "basic_info" in data and "main_attractions" in data["basic_info"]:
            st.session_state['product_context'] = data["basic_info"]["main_attractions"]
    except Exception as e:
        st.warning(f"⚠️ Formatting Issue: {e} See 'Raw Response' below to see what the AI said.")
        st.code(json_text)
        return
        
    info = data.get("basic_info", {})
    packages = data.get("packages", [])
    pol = data.get("policies", {})
    seo = data.get("seo", {})

    st.success("✅ Analysis Complete!")
    if st.button("🚀 Open Full Data Popup", type="primary", use_container_width=True):
        show_copy_dialog(data)
    st.divider()

    with st.sidebar:
        st.header("📋 Copy Dashboard")
        copy_box("📍 Location", info.get('city_country'))
        copy_box("🏷️ Name", info.get('main_attractions'))
        contact_text = str(pol.get('merchant_contact', '')).replace(' | ', '\n').replace('|', '\n')
        copy_box("📞 Contact", contact_text)
        st.divider()
        if HAS_REPORTLAB:
            pdf_data = create_pdf(data)
            if pdf_data:
                st.download_button("📄 Download Summary PDF", pdf_data, f"Klook_Summary_{int(time.time())}.pdf", "application/pdf")

    tab_names = ["ℹ️ Basic Info", "⏰ Start & End", "🗺️ Klook Itinerary", "📜 Policies", "✅ Inclusions", "🚫 Restrictions", "🔍 SEO", "💰 Packages & Price", "📊 Analysis", "📧 Supplier Email", "🔧 Automation"]
    tabs = st.tabs(tab_names)

    with tabs[0]:
        st.subheader(f"🎟️ {info.get('activity_title', 'Activity Title (Not Generated)')}")
        st.write(f"**📍 Location:** {info.get('city_country')}")
        
        st.write(f"**📦 Packages Found ({len(packages)}):**")
        for p in packages:
            st.write(f"- {p.get('package_title')} *({p.get('duration')} | {p.get('group_type')})*")
        
        st.divider()
        st.write("**🌟 Highlights:**")
        for h in info.get("highlights", []): 
            st.write(f"- {h}")
        st.write("**🏷️ Selling Points:**")
        st.write(", ".join(info.get("selling_points", [])))
        
        st.divider()
        
        wte_text = info.get("what_to_expect", "")
        wte_count = len(wte_text.split())
        wte_chars = len(wte_text)
        
        c1, c2 = st.columns([3, 1])
        with c1:
            if wte_chars > 800:
                st.error(f"📝 **What to Expect** ({wte_count} words | ⚠️ {wte_chars}/800 chars):")
            else:
                st.info(f"📝 **What to Expect** ({wte_count} words | {wte_chars}/800 chars):")
        with c2:
            if st.button("🔄 Regenerate Description"):
                keys = get_all_keys()
                if keys and st.session_state.get('raw_text_content'):
                    with st.spinner("Rewriting..."):
                        new_desc = regenerate_description_only(st.session_state['raw_text_content'], random.choice(keys), "English")
                        if new_desc.endswith("."): new_desc = new_desc[:-1]
                        
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
        start = itin.get("start", {})
        end = itin.get("end", {})
        segments = itin.get("segments", [])
        st.markdown(f"""<div class="timeline-step" style="border-left-color: #4CAF50;"><span class="timeline-time">{start.get('time', 'TBC')}</span><br><span class="timeline-title">🏁 Departure Info</span><br><span style="font-size:0.9rem">{start.get('location', 'TBC')}</span></div>""", unsafe_allow_html=True)
        for seg in segments:
            sType = seg.get('type', 'Attraction')
            sName = seg.get('name', 'Activity')
            sTime = seg.get('time', 'TBC')
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
        st.markdown(f"""<div class="timeline-step" style="border-left-color: #F44336;"><span class="timeline-time">{end.get('time', 'TBC')}</span><br><span class="timeline-title">🏁 Return Info</span><br><span style="font-size:0.9rem">{end.get('location', 'TBC')}</span></div>""", unsafe_allow_html=True)

    with tabs[3]:
        st.error(f"**Cancellation Policy:** {pol.get('cancellation', '-')}")
        st.write("**📞 Merchant Contact:**")
        for line in str(pol.get('merchant_contact', '-')).split('|'):
            st.write(line.strip())

    with tabs[4]:
        st.write("📦 **Package Inclusions**")
        if packages:
            # Create sub-tabs for each package
            pkg_tabs = st.tabs([p.get("package_title", f"Package {i+1}") for i, p in enumerate(packages)])
            for i, p in enumerate(packages):
                with pkg_tabs[i]:
                    inc = p.get("inclusions", {})
                    c1, c2 = st.columns(2)
                    with c1: 
                        st.write("✅ **Included**")
                        for x in inc.get("included", []): st.write(f"- {x}")
                    with c2: 
                        st.write("❌ **Excluded**")
                        for x in inc.get("excluded", []): st.write(f"- {x}")
        else:
            st.write("No packages detected.")

    with tabs[5]:
        res = data.get("restrictions", {})
        st.write(f"**Child:** {res.get('child_policy')}")
        st.write(f"**Accessibility:** {res.get('accessibility')}")
        
        st.write("🎒 **What to Bring:**")
        for item in res.get("what_to_bring", []): st.write(f"- {item}")
        
        faq = res.get('faq')
        with st.expander("View FAQ", expanded=True):
            if isinstance(faq, list):
                for f in faq: st.write(f"- {f}")
            else:
                st.info(faq or 'No FAQ found.')

    with tabs[6]: 
        kw_list = seo.get("keywords", [])
        kw_text = ", ".join(kw_list) if isinstance(kw_list, list) else str(kw_list)
        st.code(kw_text, language="text")
    
    with tabs[7]:
        st.header("💰 Package Pricing & Calculator")
        
        def safe_float(val, default=0.0):
            try:
                clean_val = str(val).replace('$', '').replace('€', '').replace('£', '').replace(',', '').strip()
                return float(clean_val)
            except (ValueError, TypeError):
                return default

        if not packages:
            st.warning("No packages found to display pricing.")
            
        for i, p in enumerate(packages):
            with st.expander(f"🏷️ {p.get('package_title', f'Package {i+1}')}", expanded=True):
                price_data = p.get("pricing", {})
                cur = price_data.get('currency', 'USD')
                p_adult = safe_float(price_data.get('adult_price', 0.0), 100.0)
                p_child = safe_float(price_data.get('child_price', 0.0), 0.0)
                p_infant = safe_float(price_data.get('infant_price', 0.0), 0.0)
                c_age = price_data.get('child_age', 'N/A')
                
                st.write(f"**Duration:** {p.get('duration')} | **Group:** {p.get('group_type')} (Min {p.get('min_pax')} - Max {p.get('max_pax')})")
                
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Adult Price", f"{cur} {p_adult}")
                c2.metric("Child Price", f"{cur} {p_child}")
                c3.metric("👦 Child Age", str(c_age))
                c4.metric("Infant Price", f"{cur} {p_infant}")
                st.caption(f"Raw Details: {price_data.get('details', '')}")
                
                st.divider()
                st.write("🧮 **Net Rate Calculator**")
                
                col_calc, col_res1, col_res2, col_res3 = st.columns([1.5, 1, 1, 1])
                with col_calc:
                    calc_price = st.number_input(f"Public Price ({cur})", min_value=0.0, value=float(p_adult) if p_adult else 100.0, step=1.0, key=f"calc_price_{i}")
                    margin_pct = st.number_input(f"Target Margin (%)", min_value=0.0, max_value=100.0, value=20.0, step=0.5, key=f"calc_margin_{i}")
                
                net_rate = calc_price * (1 - (margin_pct / 100))
                profit = calc_price - net_rate
                
                with col_res1:
                    st.metric("🛒 Klook Sell Price", f"{calc_price:,.2f}")
                with col_res2:
                    st.metric("💵 Net Rate", f"{net_rate:,.2f}")
                with col_res3:
                    st.metric("📈 Profit", f"{profit:,.2f}")
    
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
        st.header("🔧 Automation Data & Frontend Preview")
        
        extension_payload = data.copy()
        
        if st.session_state.get('processed_images_data'):
            formatted_photos = []
            for item in st.session_state['processed_images_data']:
                formatted_photos.append({
                    "filename": item["fname"],
                    "caption": item["caption"],
                    "base64": item.get("b64_string", "") 
                })
            extension_payload["processed_photos"] = formatted_photos
            
        c1, c2 = st.columns([1, 1])
        with c1:
            st.subheader("Raw JSON Payload")
            st.code(json.dumps(extension_payload, indent=4), language="json")
            
        with c2:
            st.subheader("🖥️ Klook UI Preview")
            st.info("Render the extracted data perfectly, without React crashing.")
            if st.button("👁️ Generate Klook-Style Preview", use_container_width=True):
                html_code = generate_static_html_preview(extension_payload)
                components.html(html_code, height=850, scrolling=True)

# --- SMART ROTATION (FIXED ERROR EXPOSURE) ---
def smart_rotation_wrapper(text, keys, lang="English"):
    if not keys: return "⚠️ No API keys found."
    
    shuffled_keys = list(keys)
    random.shuffle(shuffled_keys)
    last_error = ""
    
    for attempt in range(2):
        for key in shuffled_keys:
            result = call_gemini_json_summary(text, key, lang)
            
            if result == "429_LIMIT" or "429" in str(result):
                last_error = "429 Quota Exceeded. API is cooling down..."
                time.sleep(4)
                continue
            
            if "Error" in str(result):
                last_error = result
                continue
                
            try:
                clean_result = result.replace("```json", "").replace("```", "").strip()
                d = json.loads(clean_result)
                
                if "basic_info" in d and "highlights" in d["basic_info"]:
                    d["basic_info"]["highlights"] = [h.rstrip('.') for h in d["basic_info"]["highlights"]]
                
                if "basic_info" in d and "what_to_expect" in d["basic_info"]:
                    wte = d["basic_info"]["what_to_expect"]
                    if wte.endswith("."): wte = wte[:-1]
                    d["basic_info"]["what_to_expect"] = wte
                
                processed_json = json.dumps(d)
                return processed_json
                
            except: 
                pass
            
            return result
            
    return f"⚠️ AI Failed. Last Error: {last_error}"

# --- MAIN APP LOGIC ---
with st.sidebar:
    st.header("⚙️ Settings")
    target_lang = st.selectbox("🌐 Target Language", ["English", "Chinese (Traditional)", "Chinese (Simplified)", "Korean", "Japanese", "Thai", "Vietnamese", "Indonesian"])
    st.divider()

t1, t2, t3, t4, t6, t7 = st.tabs(["🧠 Link Summary", "✍🏻 Text Summary", "📄 PDF Summary", "🖼️ Photo Resizer", "📝 Grammar Check", "🔎 Klook Search"])

with t1:
    url = st.text_input("Paste Tour Link", value="", key="main_url_input")
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
                    st.image(img_url, use_container_width=True)
                    if st.checkbox("Select", key=f"img_{i}"):
                        selected_scraped.append(img_url)
                except Exception:
                    st.warning(f"⚠️ Could not load image {i+1}")

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
                            b_img, orig_w, orig_h, err, b64_str = None, 0, 0, None, None
                    
                    if b_img:
                        zf.writestr(f"resized_{fname}", b_img)
                        
                        caption_text = ""
                        if enable_captions and keys:
                            caption_text = call_gemini_caption(b_img, random.choice(keys), context_str=manual_context)
                        
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
            st.success("✅ All images processed successfully!")

    if st.session_state.get('processed_images_data'):
        for item in st.session_state['processed_images_data']:
            c1, c2 = st.columns([1, 2])
            with c1:
                st.image(item["b_img"], caption=item["fname"], use_container_width=True)
            with c2:
                with st.container(border=True):
                    ow = item.get("orig_w", 0)
                    oh = item.get("orig_h", 0)
                    
                    qc_1, qc_2 = st.columns(2)
                    qc_1.write(f"📏 **Uploaded Size:** {ow} x {oh}")
                    
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
                
                wc_original = len(text_input.split())
                wc_fixed = len(fixed_text.split())
                char_count = len(fixed_text)
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Original Words", wc_original)
                c2.metric("Result Words", wc_fixed, delta=wc_fixed-wc_original)
                c3.metric("Character Count", char_count)
                
                st.divider()
                
                out_col1, out_col2 = st.columns([2, 1])
                
                with out_col1:
                    st.subheader("✅ Corrected Text")
                    st.text_area("Result (Copy from here):", value=fixed_text, height=250, label_visibility="collapsed")
                
                with out_col2:
                    st.subheader("🔍 Errors Fixed")
                    with st.container(height=250):
                        if errors_list:
                            for err in errors_list:
                                st.markdown(f"**❌ {err.get('original', '')}** \n**✅ {err.get('correction', '')}** \n*{err.get('reason', '')}*")
                                st.markdown("---")
                        else:
                            st.success("No grammatical errors found! Your text was perfect.")
                            
                st.success("Correction Complete!")

with t7:
    st.header("🔎 Activity Similarity Check")
    st.info("Paste a competitor's tour link or type the activity name to check if it already exists on Klook.")
    
    klook_search_input = st.text_input("Paste Tour Link or Name:", key="klook_search_tab")
    
    if klook_search_input:
        query_text = klook_search_input
        
        if klook_search_input.startswith("http"):
            try:
                parsed = urllib.parse.urlparse(klook_search_input)
                path_segments = [seg for seg in parsed.path.split('/') if seg]
                if path_segments:
                    slug = path_segments[-1]
                    slug = slug.split('.')[0]
                    query_text = slug.replace('-', ' ').replace('_', ' ').title()
                else:
                    query_text = parsed.netloc.replace('www.', '')
            except:
                pass 
        
        st.write(f"**Extracted Search Term:** `{query_text}`")
        
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
            st.empty() 

# --- ALWAYS RENDER IF DATA EXISTS ---
if st.session_state['gen_result']:
    render_output(st.session_state['gen_result'], st.session_state['url_input'])
