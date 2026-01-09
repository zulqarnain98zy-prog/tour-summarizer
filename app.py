import streamlit as st
import cloudscraper
import time
import random
import re
import urllib.parse
from bs4 import BeautifulSoup
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, NotFound

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Tour Summarizer Pro", page_icon="✈️", layout="wide")

# --- HIDE STREAMLIT BRANDING ---
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

st.title("✈️ Global Tour Summarizer (Deep FAQ Scan)")
st.markdown("Paste a link to generate a summary. **Aggressively scans for hidden FAQs.**")

# --- LOAD ALL KEYS ---
def get_all_keys():
    """Retrieves all available keys from secrets as a list."""
    if "GEMINI_KEYS" in st.secrets:
        return st.secrets["GEMINI_KEYS"]
    elif "GEMINI_API_KEY" in st.secrets:
        return [st.secrets["GEMINI_API_KEY"]]
    else:
        return []

# --- CACHING & SCRAPING (UPDATED) ---
@st.cache_data(ttl=86400, show_spinner=False)
def extract_text_from_url(url):
    try:
        scraper = cloudscraper.create_scraper(browser='chrome')
        response = scraper.get(url, timeout=15)
        if response.status_code == 403: return "403"
        if response.status_code != 200: return None
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 1. Remove Junk
        for script in soup(["script", "style", "nav", "footer", "iframe", "svg", "button", "noscript"]):
            script.extract()
            
        # 2. ENHANCED FAQ DETECTION
        # Standard <details> tags
        for details in soup.find_all('details'):
            details.append(soup.new_string('\n')) 
        
        # "Fake" Dropdowns (divs that act like accordions)
        # We look for any element with 'faq', 'answer', 'accordion', or 'panel' in its class/id
        for tag in soup.find_all(['div', 'section', 'li']):
            # Get class and id strings safely
            cls = " ".join(tag.get('class', [])) if tag.get('class') else ""
            ids = tag.get('id', "")
            
            # If it looks like a hidden FAQ container, force a newline after it
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
        
        if available_names:
            return available_names[0]
            
        return None
    except Exception:
        return None

# --- CORE GENERATION FUNCTION ---
def call_gemini_api(text, api_key):
    """Finds a valid model and calls it."""
    
    model_name = get_valid_model(api_key)
    
    if not model_name:
        raise ValueError("No available models found for this API Key.")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    prompt = """
    You are an expert travel product manager. Analyze the following tour description.
    **CRITICAL INSTRUCTION:** Translate all content to **ENGLISH**.
    
    **STRICT GROUNDING RULE:** For sections 3 through 14, you must ONLY use information explicitly found in the text.
    - Do not guess.
    - If a specific detail is missing in the text, write "Not specified" or "Not mentioned".
    
    **Output strictly in this format:**

    1. **Highlights**: Exactly 4 bullet points.
       * *Constraint:* Each bullet point must be **strictly between 10 and 15 words**.
       * *Constraint:* **DO NOT** put a full stop (.) at the end of the bullet points.
    2. **What to Expect**: A description of the experience.
       * *Constraint:* Length must be **between 100 and 150 words**.
       * *Constraint:* Absolute maximum length is **800 characters**.
    3. **Activity Duration**: The total time. (Write "Not mentioned" if missing).
    4. **Full Itinerary**: A step-by-step list (e.g., 8:00 AM - Pickup). Only include steps explicitly listed.
    5. **Start Time and End Time**: Specific times. (Write "Not mentioned" if missing).
    6. **Inclusions & Exclusions**: Two separate lists. Only list what is explicitly stated.
    7. **Additional Information**: Key logistics found in text.
    8. **Child Policy & Eligibility**: Specific age limits/rules found in text. (Do not guess).
    9. **Accessibility**: Info for persons with disabilities found in text.
    10. **Group Size**: Min/Max pax (if mentioned).
    11. **Unit Types & Prices**: List Adult, Child, Infant categories/prices if available.
    12. **Policies**: Cancellation policy and Confirmation type found in text.
    13. **SEO Keywords**: 3 high-traffic search keywords in English based on the content.
    14. **FAQ**: Extract any "Frequently Asked Questions" found on the page. If none, write "No FAQ found on page."
    15. **OTA Search Term**: Provide the single BEST search query (Product Name + City) to find this exact activity on Viator or GetYourGuide. Do not use symbols.

    ---
    **Social Media Content**
    Generate 10 photo captions.
    * *Constraint:* Each caption must be **exactly 1 sentence**.
    * *Constraint:* Each caption must be **strictly between 10 and 15 words**.
    * *Constraint:* **DO NOT** put a full stop (.) at the end of the captions.
    * Use emojis.
    
    Tour Text:
    """ + text
    
    response = model.generate_content(prompt)
    return response.text

# --- SMART ROTATION LOGIC ---
def generate_summary_with_smart_rotation(text, keys):
    if not keys:
        return "⚠️ No API keys found."

    random.shuffle(keys)
    max_cycles = 2
    
    for cycle in range(max_cycles):
        for index, key in enumerate(keys):
            try:
                result = call_gemini_api(text, key)
                return result
            
            except (ResourceExhausted, ServiceUnavailable):
                continue
            except (NotFound, ValueError):
                continue
            except Exception as e:
                return f"AI Error: {e}"
        
        if cycle < max_cycles - 1:
            time.sleep(5)
            
    return "⚠️ **All servers busy:** Please wait 1 minute."

# --- DISPLAY FUNCTIONS ---
def display_competitor_buttons(summary_text):
    match = re.search(r"15\.\s*\*\*OTA Search Term\*\*:\s*(.*)", summary_text)
    if match:
        search_term = match.group(1).strip()
        encoded_term = urllib.parse.quote(search_term)
        
        st.markdown("### 🔎 Find Similar Products")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.link_button("🟢 Search on Viator", f"https://www.viator.com/searchResults/all?text={encoded_term}")
        with col2:
            st.link_button("🔵 Search on GetYourGuide", f"https://www.getyourguide.com/s?q={encoded_term}")
        with col3:
            klook_query = f'site:klook.com "{search_term}"'
            st.link_button("🟠 Search on Klook", f"https://www.google.com/search?q={urllib.parse.quote(klook_query)}")
            
        st.write("") 
        col4, col5, col6 = st.columns(3)
        with col4:
            st.link_button("🦉 Search on TripAdvisor", f"https://www.tripadvisor.com/Search?q={encoded_term}")
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
        st.caption("Check if they sell on OTAs (via Google Search):")
        col3, col4 = st.columns(2)
        with col3:
            query_viator = f"{merchant_name} on Viator"
            st.link_button(f"🟢 Find {merchant_name} on Viator", f"https://www.google.com/search?q={urllib.parse.quote(query_viator)}")
        with col4:
            query_gyg = f"{merchant_name} on Get Your Guide"
            st.link_button(f"🔵 Find {merchant_name} on GetYourGuide", f"https://www.google.com/search?q={urllib.parse.quote(query_gyg)}")
    except Exception:
        pass

# --- MAIN INTERFACE ---
tab1, tab2 = st.tabs(["🔗 Paste Link", "📝 Paste Text (Fallback)"])

# METHOD 1: URL
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
                    st.info("👉 Use the 'Paste Text' tab above.")
                elif raw_text:
                    with st.spinner(f"Generating Summary..."):
                        summary = generate_summary_with_smart_rotation(raw_text, all_keys)
                        
                        if "All servers busy" in summary:
                            st.error(summary)
                        elif "AI Error" in summary:
                            st.error(summary)
                        else:
                            st.success("Done!")
                            st.markdown("---")
                            st.markdown(summary)
                            st.markdown("---")
                            display_competitor_buttons(summary)
                            display_merchant_buttons(url)
                else:
                    st.error("❌ Invalid URL.")

# METHOD 2: MANUAL TEXT
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
                summary = generate_summary_with_smart_rotation(manual_text, all_keys)
                if "All servers busy" in summary:
                    st.error(summary)
                elif "AI Error" in summary:
                    st.error(summary)
                else:
                    st.success("Success!")
                    st.markdown("---")
                    st.markdown(summary)
                    st.markdown("---")
                    display_competitor_buttons(summary)
