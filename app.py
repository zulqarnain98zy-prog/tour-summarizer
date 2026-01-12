import streamlit as st
import cloudscraper
import time
import random
import re
import urllib.parse
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

# --- SPECIAL AUDIT SCRAPER (COUNTS IMAGES) ---
def extract_audit_data(url):
    """
    Special scraper for the Audit tab.
    Returns: (text_content, image_count)
    """
    try:
        scraper = cloudscraper.create_scraper(browser='chrome')
        response = scraper.get(url, timeout=15)
        if response.status_code != 200: return None, 0
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 1. Count Images (Heuristic: Count jpg/png inside main content divs)
        # We look for img tags. This is an estimate as lazy loading might hide some.
        images = soup.find_all('img')
        valid_images = [img for img in images if img.get('src') and ('jpg' in img.get('src') or 'jpeg' in img.get('src'))]
        image_count = len(valid_images)
        
        # 2. Extract Text
        for script in soup(["script", "style", "nav", "footer", "iframe", "svg", "button", "noscript"]):
            script.extract()
        for details in soup.find_all('details'):
            details.append(soup.new_string('\n')) 
        
        text = soup.get_text(separator='\n')
        lines = (line.strip() for line in text.splitlines())
        clean_lines = [line for line in lines if line]
        final_text = '\n'.join(clean_lines)
        
        return final_text[:35000], image_count
        
    except Exception:
        return "ERROR", 0

# --- STANDARD TEXT EXTRACTION ---
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

# --- GENERATION FUNCTIONS ---

def call_gemini_api(text, api_key):
    """Standard Summary Generator"""
    model_name = get_valid_model(api_key)
    if not model_name: raise ValueError("No model.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    prompt = """
    You are an expert travel product manager. Analyze the tour.
    **Translate to ENGLISH.**
    **Output strict format:**
    1. **Highlights**: 4 bullets (10-15 words, no full stop).
    2. **What to Expect**: 100-150 words (Max 800 chars).
    3. **Activity Duration**: Total time.
    4. **Full Itinerary**: Step-by-step.
    5. **Start Time**: Specific times.
    6. **Inclusions**: List.
    7. **Exclusions**: List.
    8. **Child Policy**: Age rules.
    9. **Accessibility**: Info.
    10. **Group Size**: Min/Max.
    11. **Prices**: Categories.
    12. **Cancellation Policy**: Rules.
    13. **SEO Keywords**: 3 keywords.
    14. **FAQ**: Hidden FAQs.
    15. **OTA Search Term**: Product Name + City.
    ---
    **Social Media**: 10 captions (1 sentence, 10-15 words).
    Tour Text:
    """ + text
    return model.generate_content(prompt).text

def call_qa_comparison(klook, merchant, api_key):
    """QA Comparison"""
    model_name = get_valid_model(api_key)
    if not model_name: raise ValueError("No model.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    prompt = f"""
    Compare Klook Data (Draft) vs Merchant Data (Source).
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

def call_klook_audit(text, image_count, api_key):
    """New Audit Function"""
    model_name = get_valid_model(api_key)
    if not model_name: raise ValueError("No model.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""
    You are a strictly logical Klook Product Auditor. 
    Audit the product page text below based on the following Strict Criteria.

    **METADATA PROVIDED:**
    - **Detected Image Count (Approx):** {image_count} images found in code.

    **CRITERIA TO CHECK:**
    1. **Photos:** Must have Minimum 6 photos. (Check the Image Count provided above). *Note: Ratio must be 4:3, verify visually.*
    2. **Cancellation Policy:**
       - If Day Tour: Must be "Instant Confirmation" AND "24 hours free cancellation".
       - If Multi-day Tour: Must be "24 hours cancellation" OR "48 hours".
    3. **Inventory:** Must appear to have 3 months of inventory (Look for "Bookable", "Year round", or specific date ranges in text).
    4. **Itinerary:** Must be filled in (Look for a detailed timeline).

    **OUTPUT FORMAT:**
    
    ### 📋 Klook Product Audit
    
    | Criteria | Status | Observation |
    | :--- | :--- | :--- |
    | **1. Banner & Photos** | [✅ Pass / ❌ Fail] | Found {image_count} images. (Rule: Min 6). Ratio check required manually. |
    | **2. Cancellation** | [✅ Pass / ❌ Fail] | [Quote the policy found in text]. Matches rule? |
    | **3. Inventory** | [✅ Pass / ⚠️ Unsure] | [Quote availability clues]. (Note: Calendar is dynamic). |
    | **4. Itinerary** | [✅ Pass / ❌ Fail] | [Is there a detailed timeline?] |

    **OVERALL VERDICT:** [✅ READY TO PUBLISH / ❌ NEEDS REVISION]
    **Action Items:** [List what needs fixing, if any]

    **Tour Text:**
    {text}
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
                if task_type == 'summary': return call_gemini_api(args[0], key)
                elif task_type == 'qa': return call_qa_comparison(args[0], args[1], key)
                elif task_type == 'audit': return call_klook_audit(args[0], args[1], key)
            except (ResourceExhausted, ServiceUnavailable, NotFound, ValueError): continue
            except Exception as e: return f"AI Error: {e}"
        if cycle < max_cycles - 1: time.sleep(5)
    return "⚠️ **All servers busy:** Please wait 1 minute."

# --- DISPLAY FUNCTIONS ---
def display_buttons(summary):
    match = re.search(r"15\.\s*\*\*OTA Search Term\*\*:\s*(.*)", summary)
    if match:
        term = urllib.parse.quote(match.group(1).strip())
        st.markdown("### 🔎 Find Similar Products")
        c1, c2, c3 = st.columns(3)
        with c1: st.link_button("🟢 Viator", f"https://www.viator.com/searchResults/all?text={term}")
        with c2: st.link_button("🔵 GetYourGuide", f"https://www.getyourguide.com/s?q={term}")
        with c3: st.link_button("🟠 Klook", f"https://www.google.com/search?q={urllib.parse.quote(f'site:klook.com {match.group(1).strip()}')}")

# --- MAIN TABS ---
t1, t2, t3, t4, t5 = st.tabs([
    "🧠 Summary (Link)", 
    "✍🏻 Summary (Fallback)", 
    "📂 Summary (File)",
    "⚖️ QA Comparison",
    "✅ Klook Standard Audit"
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
                    st.success("Done!")
                    st.markdown("---"); st.markdown(res); st.markdown("---")
                    display_buttons(res)
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
                st.success("Done!")
                st.markdown("---"); st.markdown(res)

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
                    st.success("Done!")
                    st.markdown("---"); st.markdown(res)
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

# 5. KLOOK AUDIT (NEW!)
with t5:
    st.markdown("### ✅ Klook Product Auditor")
    st.info("Paste a Klook Product Link. We will check: **6+ Photos, Cancellation Policy, Inventory, & Itinerary.**")
    audit_url = st.text_input("Paste Klook Product URL")
    
    if st.button("Run Audit", key="btn5"):
        keys = get_all_keys()
        if not keys:
            st.error("⚠️ API Key missing.")
        elif not audit_url:
            st.warning("⚠️ Please paste a URL.")
        else:
            with st.spinner("Auditing Product..."):
                # Use special Audit Scraper (returns text + image count)
                audit_text, img_count = extract_audit_data(audit_url)
                
                if audit_text == "ERROR" or audit_text == "403":
                    st.error("🚫 Website Blocked.")
                else:
                    audit_res = smart_rotation_wrapper('audit', keys, audit_text, img_count)
                    
                    if "AI Error" in audit_res:
                        st.error(audit_res)
                    else:
                        print(f"✅ AUDIT SUCCESS | {datetime.now()} | {audit_url}")
                        st.success("Audit Complete!")
                        st.markdown("---")
                        st.markdown(audit_res)
