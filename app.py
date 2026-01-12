import streamlit as st
import cloudscraper
import time
import random
import re
import urllib.parse
import json
from bs4 import BeautifulSoup
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, NotFound
from datetime import datetime
import sys
import io

# --- TRY IMPORTING FILE READERS ---
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from docx import Document
except ImportError:
    Document = None

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
st.markdown("Use Magic Tool to generate summaries or analysis in seconds!")

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

# --- MODEL FINDER ---
def get_valid_model(api_key):
    try:
        genai.configure(api_key=api_key)
        models = genai.list_models()
        available_names = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        priority = ['models/gemini-1.5-flash', 'models/gemini-1.5-flash-latest', 'models/gemini-1.5-pro']
        for m in priority:
            if m in available_names: return m
        return available_names[0] if available_names else None
    except Exception:
        return None

# --- GENERATION FUNCTIONS (JSON & QA) ---

def call_gemini_json_summary(text, api_key):
    """
    Forces the AI to return a strict JSON object to populate the tabs.
    """
    model_name = get_valid_model(api_key)
    if not model_name: raise ValueError("No model.")
    genai.configure(api_key=api_key)
    # Force JSON mode
    model = genai.GenerativeModel(model_name, generation_config={"response_mime_type": "application/json"})
    
    prompt = """
    You are an expert travel product manager. Analyze the tour text.
    **CRITICAL:** Output ONLY valid JSON. No Markdown. No code blocks.
    **Language:** English.

    Structure the JSON exactly like this:
    {
        "basic_info": {
            "city_country": "City, Country",
            "group_type": "1 Group (Private only) OR 1 Group (Join-in only) OR More than 1 (Both)",
            "group_size": "Min/Max pax",
            "duration": "Total time",
            "main_attractions": "Key spots visited",
            "what_to_expect": "100-150 words description (max 800 chars)",
            "selling_points": "Key selling points (history, food, nature, etc.)"
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
        "photos": {
            "captions": ["Caption 1 (10-15 words)", "Caption 2...", "Caption 10..."]
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

# --- SMART ROTATION WRAPPER ---
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

# --- DISPLAY HELPERS ---
def google_map_link(location):
    if not location or location == "Not mentioned": return location
    query = urllib.parse.quote(location)
    return f"[{location}](https://www.google.com/maps/search/?api=1&query={query})"

def render_json_results(json_text):
    """Parses JSON and creates the Tabs UI"""
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        st.error("⚠️ AI Generation Error: Output was not valid JSON. Please try again.")
        st.text(json_text)
        return

    # --- TAB DEFINITIONS ---
    tab_names = [
        "ℹ️ Basic Info", "⏰ Start & End", "🗺️ Itinerary", "📸 Photos", 
        "📜 Policies", "✅ Inclusions", "🚫 Restrictions", "🔍 SEO", 
        "💰 Price", "📊 Analysis"
    ]
    tabs = st.tabs(tab_names)

    # TAB A: Basic Info
    with tabs[0]:
        info = data.get("basic_info", {})
        c1, c2 = st.columns(2)
        c1.write(f"**📍 Departs From:** {info.get('city_country', '-')}")
        c2.write(f"**👥 Group Type:** {info.get('group_type', '-')}")
        c1.write(f"**🔢 Group Size:** {info.get('group_size', '-')}")
        c2.write(f"**⏳ Duration:** {info.get('duration', '-')}")
        st.divider()
        st.write(f"**🎡 Main Attractions:** {info.get('main_attractions', '-')}")
        st.write(f"**✨ Selling Points:** {info.get('selling_points', '-')}")
        st.info(f"**What to Expect:**\n\n{info.get('what_to_expect', '-')}")

    # TAB B: Start & End
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

    # TAB C: Itinerary
    with tabs[2]:
        itin = data.get("itinerary", {})
        st.caption(f"**Note:** {itin.get('note', '')}")
        steps = itin.get("steps", [])
        if isinstance(steps, list):
            for step in steps: st.write(step)
        else:
            st.write(steps)

    # TAB D: Photos
    with tabs[3]:
        st.warning("⚠️ Note: AI cannot crop/resize real photos. Please match these captions to your 4:3 images.")
        captions = data.get("photos", {}).get("captions", [])
        for i, cap in enumerate(captions, 1):
            st.write(f"**{i}.** {cap}")

    # TAB E: Policies
    with tabs[4]:
        pol = data.get("policies", {})
        st.error(f"**Cancellation Policy:** {pol.get('cancellation', '-')}")
        st.write(f"**📞 Merchant Contact:** {pol.get('merchant_contact', '-')}")

    # TAB F: Inclusions
    with tabs[5]:
        inc = data.get("inclusions", {})
        c1, c2 = st.columns(2)
        with c1:
            st.write("✅ **Included:**")
            for x in inc.get("included", []): st.write(f"- {x}")
        with c2:
            st.write("❌ **Not Included:**")
            for x in inc.get("excluded", []): st.write(f"- {x}")

    # TAB G: Restrictions
    with tabs[6]:
        res = data.get("restrictions", {})
        st.write(f"**👶 Child Policy:** {res.get('child_policy', '-')}")
        st.write(f"**♿ Accessibility:** {res.get('accessibility', '-')}")
        st.write(f"**📝 Additional Info:** {res.get('additional_info', '-')}")
        with st.expander("View FAQ"):
            st.write(res.get('faq', 'No FAQ found.'))

    # TAB H: SEO
    with tabs[7]:
        seo = data.get("seo", {}).get("keywords", [])
        st.write("**🔑 Keywords:**")
        st.code(", ".join(seo))

    # TAB I: Price
    with tabs[8]:
        st.write(data.get("pricing", {}).get("details", '-'))

    # TAB J: Analysis
    with tabs[9]:
        an = data.get("analysis", {})
        search_term = an.get("ota_search_term", "")
        st.write(f"**OTA Search Term:** `{search_term}`")
        
        if search_term:
            term = urllib.parse.quote(search_term)
            st.markdown("### 🔎 Find Similar Products")
            c1, c2, c3 = st.columns(3)
            with c1: st.link_button("🟢 Search Viator", f"https://www.viator.com/searchResults/all?text={term}")
            with c2: st.link_button("🔵 Search GYG", f"https://www.getyourguide.com/s?q={term}")
            with c3: st.link_button("🟠 Search Klook", f"https://www.google.com/search?q={urllib.parse.quote(f'site:klook.com {search_term}')}")
            
            st.markdown("### 🏢 Analyze Merchant")
            c4, c5 = st.columns(2)
            with c4: st.link_button("🔎 Competitors", f"https://www.google.com/search?q=related:{term}")
            with c5: st.link_button("⭐ Reliability", f"https://www.google.com/search?q={term} reviews scam legit")

# --- MAIN TABS ---
t1, t2, t3, t4 = st.tabs([
    "🧠 Generate Activity Summary (Link)", 
    "✍🏻 Generate Activity Summary (Fallback)", 
    "📂 Generate Activity Summary (File/PDF)",
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
                    else: render_json_results(res)
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

# 4. QA COMPARISON
with t4:
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
