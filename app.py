import streamlit as st
import cloudscraper
import time
import random
import re
import urllib.parse
from bs4 import BeautifulSoup
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable

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

st.title("✈️ Global Tour Summarizer (Competitor & Merchant Analysis)")
st.markdown("Paste a link to generate a summary, **compare prices**, and **analyze the merchant**.")

# --- API KEY ROTATION ---
def get_random_key():
    if "GEMINI_KEYS" in st.secrets:
        keys = st.secrets["GEMINI_KEYS"]
        return random.choice(keys)
    elif "GEMINI_API_KEY" in st.secrets:
        return st.secrets["GEMINI_API_KEY"]
    else:
        return None

# --- CACHING ---
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
            
        text = soup.get_text(separator='\n')
        lines = (line.strip() for line in text.splitlines())
        clean_lines = [line for line in lines if line]
        final_text = '\n'.join(clean_lines)
        return final_text[:35000]
    except Exception:
        return "ERROR"

def get_working_model(api_key):
    try:
        genai.configure(api_key=api_key)
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        preferred_order = [
            'models/gemini-1.5-flash',
            'models/gemini-1.5-flash-latest',
            'models/gemini-1.5-flash-001',
            'models/gemini-1.5-pro',
            'models/gemini-pro'
        ]
        
        for model in preferred_order:
            if model in available_models:
                return model
        return available_models[0] if available_models else None
    except Exception:
        return None

@st.cache_data(ttl=86400, show_spinner=False)
def generate_summary_cached(text, _key, model_name):
    genai.configure(api_key=_key)
    model = genai.GenerativeModel(model_name)
    
    prompt = """
    You are an expert travel product manager. Analyze the following tour description.
    **CRITICAL INSTRUCTION:** Translate all content to **ENGLISH**.
    
    **Output strictly in this format:**

    1. **Highlights**: Exactly 4 bullet points.
       * *Constraint:* Each bullet point must be **strictly between 10 and 12 words**.
       * *Constraint:* **DO NOT** put a full stop (.) at the end of the bullet points.
    2. **What to Expect**: A description under 800 characters.
    3. **Activity Duration**: The total time.
    4. **Full Itinerary**: A step-by-step list (e.g., 8:00 AM - Pickup; 10:00 AM - Arrive).
    5. **Start Time and End Time**: Specific times if mentioned.
    6. **Inclusions & Exclusions**: Two separate lists.
    7. **Additional Information**: Key logistics (what to bring, restrictions).
    8. **Child Policy & Eligibility**: Age limits, ticket rules, or height restrictions.
    9. **Accessibility**: Info for persons with disabilities.
    10. **Group Size**: Min/Max pax (if mentioned).
    11. **Unit Types & Prices**: List Adult, Child, Infant prices if available.
    12. **Policies**: Cancellation policy and Confirmation type.
    13. **SEO Keywords**: 3 high-traffic search keywords in English.
    14. **FAQ**: Extract any "Frequently Asked Questions" found on the page. If none, write "No FAQ found on page."
    15. **OTA Search Term**: Provide the single BEST search query (Product Name + City) to find this exact activity on Viator or GetYourGuide. Do not use symbols.

    ---
    **Social Media Content**
    Generate 10 photo captions.
    * *Constraint:* Each caption must be **exactly 1 sentence**.
    * *Constraint:* Each caption must be **strictly between 10 and 12 words**.
    * *Constraint:* **DO NOT** put a full stop (.) at the end of the captions.
    * Use emojis.
    
    Tour Text:
    """ + text
    
    max_retries = 7
    wait_time = 5 
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            return response.text
        except (ResourceExhausted, ServiceUnavailable):
            if attempt < max_retries - 1:
                time.sleep(wait_time * (attempt + 1)) 
                continue
            else:
                return "⚠️ **Server Busy:** High traffic. Please wait 1 minute."
        except Exception as e:
            return f"AI Error: {e}"

# --- BUTTON FUNCTION 1: FIND SIMILAR PRODUCTS ---
def display_competitor_buttons(summary_text):
    match = re.search(r"15\.\s*\*\*OTA Search Term\*\*:\s*(.*)", summary_text)
    if match:
        search_term = match.group(1).strip()
        encoded_term = urllib.parse.quote(search_term)
        
        st.markdown("### 🔎 Find Similar Products")
        st.caption("Click to find this exact activity on other platforms:")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.link_button("🟢 Search on Viator", f"https://www.viator.com/searchResults/all?text={encoded_term}")
        with col2:
            st.link_button("🔵 Search on GetYourGuide", f"https://www.getyourguide.com/s?q={encoded_term}")
        with col3:
            st.link_button("🟠 Search on Klook", f"https://www.klook.com/search?text={encoded_term}")

# --- BUTTON FUNCTION 2: FIND SIMILAR MERCHANTS ---
def display_merchant_buttons(url_input):
    if not url_input:
        return

    try:
        # Extract the domain (e.g., www.headout.com -> headout.com)
        parsed_url = urllib.parse.urlparse(url_input)
        domain = parsed_url.netloc
        
        # Remove 'www.' to get clean name
        clean_domain = domain.replace("www.", "")
        
        # Extract name (e.g., headout.com -> Headout)
        merchant_name = clean_domain.split('.')[0].capitalize()
        
        st.markdown("---")
        st.markdown(f"### 🏢 Analyze Merchant: **{merchant_name}**")
        st.caption(f"Researching the website source: {clean_domain}")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Google Search: "sites like headout.com"
            query = f"sites like {clean_domain}"
            encoded_query = urllib.parse.quote(query)
            st.link_button(f"🔎 Find Similar Merchants to {merchant_name}", f"https://www.google.com/search?q={encoded_query}")
            
        with col2:
            # Google Search: "Headout reviews"
            query_reviews = f"{merchant_name} website reviews scam legit"
            encoded_reviews = urllib.parse.quote(query_reviews)
            st.link_button(f"⭐ Check {merchant_name} Reliability", f"https://www.google.com/search?q={encoded_reviews}")
            
    except Exception:
        pass

# --- MAIN INTERFACE ---
tab1, tab2 = st.tabs(["🔗 Paste Link", "📝 Paste Text (Fallback)"])

# METHOD 1: URL
with tab1:
    url = st.text_input("Paste Tour Link Here")
    if st.button("Generate Summary"):
        current_key = get_random_key()
        if not current_key:
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
                    model_name = get_working_model(current_key)
                    if model_name:
                        with st.spinner(f"Processing (Model: {model_name})..."):
                            summary = generate_summary_cached(raw_text, current_key, model_name)
                            if "Server Busy" in summary:
                                st.error(summary)
                            else:
                                st.success("Done!")
                                st.markdown("---")
                                st.markdown(summary)
                                st.markdown("---")
                                # 1. PRODUCT SEARCH
                                display_competitor_buttons(summary)
                                # 2. MERCHANT SEARCH
                                display_merchant_buttons(url)
                    else:
                        st.error("❌ No AI model found.")
                else:
                    st.error("❌ Invalid URL.")

# METHOD 2: MANUAL TEXT
with tab2:
    st.info("💡 Copy text from the website manually and paste it here if the link fails.")
    manual_text = st.text_area("Paste Full Text Here", height=300)
    if st.button("Generate from Text"):
        current_key = get_random_key()
        if not current_key:
            st.error("⚠️ API Key missing.")
        elif len(manual_text) < 50:
            st.warning("⚠️ Please paste more text.")
        else:
            with st.spinner(f"Processing..."):
                model_name = get_working_model(current_key)
                if model_name:
                    summary = generate_summary_cached(manual_text, current_key, model_name)
                    if "Server Busy" in summary:
                        st.error(summary)
                    else:
                        st.success("Success!")
                        st.markdown("---")
                        st.markdown(summary)
                        st.markdown("---")
                        display_competitor_buttons(summary)
                else:
                    st.error("❌ No AI model found.")
