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

# --- TRY IMPORTING FILE READERS (Handle missing libraries gracefully) ---
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
    """Extracts text from PDF, DOCX, or TXT files."""
    try:
        file_type = uploaded_file.type
        
        # 1. PDF Handling
        if "pdf" in file_type:
            if PdfReader is None:
                return "⚠️ Error: 'pypdf' library not installed. Please add it to requirements.txt."
            reader = PdfReader(uploaded_file)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            return text

        # 2. DOCX Handling
        elif "wordprocessingml" in file_type or "docx" in uploaded_file.name:
            if Document is None:
                return "⚠️ Error: 'python-docx' library not installed. Please add it to requirements.txt."
            doc = Document(uploaded_file)
            text = "\n".join([para.text for para in doc.paragraphs])
            return text

        # 3. Plain Text Handling
        else:
            return uploaded_file.getvalue().decode("utf-8")
            
    except Exception as e:
        return f"⚠️ Error reading file: {e}"

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
        
        priority_list = [
            'models/gemini-1.5-flash',
            'models/gemini-1.5-flash-latest',
            'models/gemini-1.5-flash-001',
            'models/gemini-1.5-pro',
            'models/gemini-pro'
        ]
        
        for model in priority_list:
            if model in available_names:
                return model
        return available_names[0] if available_names else None
    except Exception:
        return None

# --- CORE GENERATION FUNCTION (SUMMARY) ---
def call_gemini_api(text, api_key):
    model_name = get_valid_model(api_key)
    if not model_name: raise ValueError("No available models found.")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    prompt = """
    You are an expert travel product manager. Analyze the following tour description.
    **CRITICAL INSTRUCTION:** Translate all content to **ENGLISH**.
    
    **STRICT GROUNDING RULE:** Sections 3-14 must be strictly based on the text. Write "Not specified" if missing.
    
    **Output strictly in this format:**

    1. **Highlights**: Exactly 4 bullet points.
       * *Constraint:* 10-15 words each. No full stops.
    2. **What to Expect**: 100-150 words. Max 800 chars.
    3. **Activity Duration**: Total time.
    4. **Full Itinerary**: Step-by-step list.
    5. **Start Time**: Specific times.
    6. **Inclusions**: List.
    7. **Exclusions**: List.
    8. **Child Policy**: Age rules.
    9. **Accessibility**: Disability info.
    10. **Group Size**: Min/Max pax.
    11. **Prices**: Adult/Child prices.
    12. **Cancellation Policy**: Specific rules.
    13. **SEO Keywords**: 3 keywords.
    14. **FAQ**: Hidden FAQs.
    15. **OTA Search Term**: Product Name + City.

    ---
    **Social Media Content**
    Generate 10 photo captions (1 sentence, 10-15 words each).
    
    Tour Text:
    """ + text
    
    response = model.generate_content(prompt)
    return response.text

# --- CORE QA FUNCTION (REASON INCLUDED) ---
def call_qa_comparison(klook_data, merchant_data, api_key):
    model_name = get_valid_model(api_key)
    if not model_name: raise ValueError("No available models found.")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""
    You are a Strict Quality Assurance (QA) Auditor.
    Your job is to compare the "Klook Backend Data" (Draft) against the "Merchant Website Data" (Source of Truth).

    **OBJECTIVE:** Determine if the Klook Data is accurate. If there are contradictions, we must REJECT.

    **INPUT DATA:**
    ---
    **SOURCE A (Klook Draft):**
    {klook_data}
    
    ---
    **SOURCE B (Merchant Official Site):**
    {merchant_data}
    ---

    **OUTPUT FORMAT:**
    
    ### 🛡️ QA VERDICT
    **Status:** [✅ APPROVED / ❌ REJECT / ⚠️ WARNING]
    **Reason:** [One short sentence explaining WHY it was rejected. Example: "Rejected because Klook price is higher than official site." OR "Rejected because Start Time is missing on Klook."]

    ### 🔍 Discrepancy Analysis
    | Feature | Klook Says | Merchant Website Says | Impact |
    | :--- | :--- | :--- | :--- |
    | **Price** | [Extract] | [Extract] | [High/Low] |
    | **Start Time** | [Extract] | [Extract] | [High/Low] |
    | **Inclusions** | [Extract] | [Extract] | [High/Low] |
    | **Cancellation**| [Extract] | [Extract] | [High/Low] |

    ### 📝 Missing Information
    List any critical details found on the Merchant Site that are COMPLETELY MISSING from Klook.

    ### 💡 Recommendation
    One sentence advice to the agent (e.g., "Update the start time to 9:00 AM to match the website").
    """
    
    response = model.generate_content(prompt)
    return response.text

# --- SMART ROTATION LOGIC ---
def smart_rotation_wrapper(task_type, keys, *args):
    if not keys: return "⚠️ No API keys found."
    random.shuffle(keys)
    max_cycles = 2
    
    for cycle in range(max_cycles):
        for index, key in enumerate(keys):
            try:
                if task_type == 'summary':
                    return call_gemini_api(args[0], key)
                elif task_type == 'qa':
                    return call_qa_comparison(args[0], args[1], key)
            except (ResourceExhausted, ServiceUnavailable, NotFound, ValueError):
                continue
            except Exception as e:
                return f"AI Error: {e}"
        if cycle < max_cycles - 1: time.sleep(5)
    return "⚠️ **All servers busy:** Please wait 1 minute."

# --- DISPLAY FUNCTIONS ---
def display_competitor_buttons(summary_text):
    match = re.search(r"15\.\s*\*\*OTA Search Term\*\*:\s*(.*)", summary_text)
    if match:
        search_term = match.group(1).strip()
        encoded_term = urllib.parse.quote(search_term)
        st.markdown("### 🔎 Find Similar Products")
        col1, col2, col3 = st.columns(3)
        with col1: st.link_button("🟢 Search on Viator", f"https://www.viator.com/searchResults/all?text={encoded_term}")
        with col2: st.link_button("🔵 Search on GetYourGuide", f"https://www.getyourguide.com/s?q={encoded_term}")
        with col3: 
            klook_query = f'site:klook.com "{search_term}"'
            st.link_button("🟠 Search on Klook", f"https://www.google.com/search?q={urllib.parse.quote(klook_query)}")
        st.write("") 
        col4, col5, col6 = st.columns(3)
        with col4: st.link_button("🦉 Search on TripAdvisor", f"https://www.tripadvisor.com/Search?q={encoded_term}")
        with col5: 
            fh_query = f'"{search_term}" FareHarbor'
            st.link_button("⚓ Find on FareHarbor", f"https://www.google.com/search?q={urllib.parse.quote(fh_query)}")
        with col6: 
            rezdy_query = f'"{search_term}" Rezdy'
            st.link_button("📅 Find on Rezdy", f"https://www.google.com/search?q={urllib.parse.quote(rezdy_query)}")

def display_merchant_buttons(url_input):
    if not url_input: return
    try:
        parsed_url = urllib.parse.urlparse(url_input)
        domain = parsed_url.netloc
        clean_domain = domain.replace("www.", "")
        merchant_name = clean_domain.split('.')[0].capitalize()
        
        st.markdown("---")
        st.markdown(f"### 🏢 Analyze Merchant: **{merchant_name}**")
        col1, col2 = st.columns(2)
        with col1:
            query = f"sites like {clean_domain}"
            st.link_button(f"🔎 Find Competitors to {merchant_name}", f"https://www.google.com/search?q={urllib.parse.quote(query)}")
        with col2:
            query_reviews = f"{merchant_name} website reviews scam legit"
            st.link_button(f"⭐ Check {merchant_name} Reliability", f"https://www.google.com/search?q={urllib.parse.quote(query_reviews)}")
        st.write("")
        col3, col4 = st.columns(2)
        with col3:
            query_viator = f"{merchant_name} on Viator"
            st.link_button(f"🟢 Find {merchant_name} on Viator", f"https://www.google.com/search?q={urllib.parse.quote(query_viator)}")
        with col4:
            query_gyg = f"{merchant_name} on Get Your Guide"
            st.link_button(f"🔵 Find {merchant_name} on GetYourGuide", f"https://www.google.com/search?q={urllib.parse.quote(query_gyg)}")
    except Exception:
        pass

# --- MAIN INTERFACE (4 TABS) ---
tab1, tab2, tab3, tab4 = st.tabs([
    "🧠 Generate Activity Summary (Link)", 
    "✍🏻 Generate Activity Summary (Fallback)", 
    "📂 Generate Activity Summary (File/PDF)",
    "⚖️ QA Comparison (Testing)"
])

# METHOD 1: URL SUMMARY
with tab1:
    url = st.text_input("Paste Tour Link Here")
    if st.button("Generate Summary"):
        all_keys = get_all_keys()
        if not all_keys:
            st.error("⚠️ API Key missing in Secrets.")
        elif not url:
            st.warning("⚠️ Please paste a URL.")
        else:
            with st.spinner("Analyzing..."):
                raw_text = extract_text_from_url(url)
                if raw_text == "403" or raw_text == "ERROR":
                    st.error("🚫 Website Blocked.")
                elif raw_text:
                    with st.spinner(f"Generating Summary..."):
                        summary = smart_rotation_wrapper('summary', all_keys, raw_text)
                        
                        if "All servers busy" in summary or "AI Error" in summary:
                            st.error(summary)
                        else:
                            print(f"✅ SUMMARY SUCCESS | {datetime.now()} | URL: {url}")
                            st.success("Done!")
                            st.markdown("---")
                            st.markdown(summary)
                            st.markdown("---")
                            display_competitor_buttons(summary)
                            display_merchant_buttons(url)
                else:
                    st.error("❌ Invalid URL.")

# METHOD 2: MANUAL TEXT SUMMARY
with tab2:
    st.info("💡 Copy text from the website manually and paste it here if the link fails.")
    manual_text = st.text_area("Paste Full Text Here", height=300)
    if st.button("Generate from Text"):
        all_keys = get_all_keys()
        if not all_keys:
            st.error("⚠️ API Key missing.")
        elif len(manual_text) < 50:
            st.warning("⚠️ Please paste more text.")
        else:
            with st.spinner(f"Processing..."):
                summary = smart_rotation_wrapper('summary', all_keys, manual_text)
                if "All servers busy" in summary or "AI Error" in summary:
                    st.error(summary)
                else:
                    print(f"✅ SUMMARY SUCCESS | {datetime.now()} | Manual Text")
                    st.success("Success!")
                    st.markdown("---")
                    st.markdown(summary)
                    st.markdown("---")
                    display_competitor_buttons(summary)

# METHOD 3: FILE UPLOAD
with tab3:
    st.info("📂 Upload a PDF, Docx, or Text file containing the activity details.")
    uploaded_file = st.file_uploader("Upload File", type=["pdf", "docx", "txt"])
    
    if st.button("Generate from File"):
        all_keys = get_all_keys()
        if not all_keys:
            st.error("⚠️ API Key missing.")
        elif not uploaded_file:
            st.warning("⚠️ Please upload a file.")
        else:
            with st.spinner("Reading File..."):
                file_text = extract_text_from_file(uploaded_file)
                
                if "Error" in file_text and "⚠️" in file_text:
                    st.error(file_text)
                elif len(file_text) < 50:
                    st.warning("⚠️ File content is too short or empty.")
                else:
                    with st.spinner(f"Processing File..."):
                        summary = smart_rotation_wrapper('summary', all_keys, file_text)
                        
                        if "All servers busy" in summary or "AI Error" in summary:
                            st.error(summary)
                        else:
                            print(f"✅ FILE SUCCESS | {datetime.now()} | File: {uploaded_file.name}")
                            st.success("Success!")
                            st.markdown("---")
                            st.markdown(summary)
                            st.markdown("---")
                            display_competitor_buttons(summary)

# METHOD 4: QA COMPARISON
with tab4:
    st.markdown("### 🛡️ Quality Assurance Check")
    st.info("Paste the draft text from Klook Backend and the link to the Merchant's real website. The AI will find discrepancies.")
    
    col_qa_1, col_qa_2 = st.columns(2)
    
    with col_qa_1:
        qa_klook_text = st.text_area("1️⃣ Paste from Klook", height=200, placeholder="Paste the content from the Klook Admin Panel here...")
        
    with col_qa_2:
        qa_merchant_url = st.text_input("2️⃣ Paste Merchant Website Link", placeholder="https://example-tour-operator.com/tour-details")
        
    if st.button("⚔️ Compare & Validate"):
        all_keys = get_all_keys()
        if not all_keys:
            st.error("⚠️ API Key missing.")
        elif not qa_klook_text or not qa_merchant_url:
            st.warning("⚠️ Please fill in both fields.")
        else:
            with st.spinner("Scraping Merchant Website..."):
                qa_merchant_text = extract_text_from_url(qa_merchant_url)
                
                if qa_merchant_text == "403" or qa_merchant_text == "ERROR":
                    st.error("🚫 Merchant Website Blocked. Please copy text manually.")
                elif qa_merchant_text:
                    with st.spinner("Comparing Data (Finding Discrepancies)..."):
                        qa_result = smart_rotation_wrapper('qa', all_keys, qa_klook_text, qa_merchant_text)
                        
                        if "All servers busy" in qa_result or "AI Error" in qa_result:
                            st.error(qa_result)
                        else:
                            print(f"✅ QA SUCCESS | {datetime.now()} | Compared Klook Data vs {qa_merchant_url}")
                            st.success("Comparison Complete!")
                            st.markdown("---")
                            st.markdown(qa_result)
