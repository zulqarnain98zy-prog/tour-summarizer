import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import google.generativeai as genai

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Tour Summarizer Pro", page_icon="✈️", layout="wide")

# --- HIDE STREAMLIT BRANDING (OPTIONAL) ---
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

st.title("✈️ Tour Activity Summarizer")
st.markdown("Generate standard summaries, SEO keywords, and policies instantly.")

# --- API KEY ---
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Enter Gemini API Key", type="password")

# --- HELPER FUNCTIONS ---
def get_working_model():
    """Finds a working Google Gemini model."""
    try:
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        preferred_order = [
            'models/gemini-1.5-flash',
            'models/gemini-1.5-flash-latest',
            'models/gemini-1.5-pro',
            'models/gemini-pro'
        ]
        
        for model in preferred_order:
            if model in available_models:
                return model
        return available_models[0] if available_models else None
    except Exception:
        return None

def extract_text_from_url(url):
    """
    Uses Cloudscraper to bypass basic anti-bot protections.
    """
    try:
        scraper = cloudscraper.create_scraper(browser='chrome')
        response = scraper.get(url, timeout=15)
        
        if response.status_code == 403:
            return "403"
        if response.status_code != 200:
            return None
            
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove junk
        for script in soup(["script", "style", "nav", "footer", "iframe"]):
            script.extract()
            
        text = soup.get_text(separator=' ')
        # Clean whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        return text[:20000] # Increased limit
    except Exception as e:
        return "ERROR"

def generate_summary(text, key, model_name):
    genai.configure(api_key=key)
    model = genai.GenerativeModel(model_name)
    
    prompt = """
    Analyze the following tour description and summarize it strictly into this format:
    
    1. **Highlights**: Exactly 4 bullet points.
    2. **What to Expect**: A description under 800 characters.
    3. **Activity Duration**: The total time.
    4. **Full Itinerary**: A step-by-step list.
    5. **Start Time and End Time**: Specific times if mentioned, otherwise general timing (e.g., Morning/Afternoon).
    6. **Inclusions & Exclusions**: Two separate lists.
    7. **Additional Information**: Key logistics (what to bring, restrictions).
    8. **Child Policy & Eligibility**: Age limits, ticket rules, or height restrictions.
    9. **Accessibility**: Info for persons with disabilities (wheelchair access, mobility issues).
    10. **Group Size**: Min/Max pax (if mentioned).
    11. **Unit Types & Prices**: List Adult, Child, Infant, Senior prices if available.
    12. **Policies**: Cancellation policy and Confirmation type (instant/manual).
    13. **SEO Keywords**: 3 high-traffic search keywords.

    ---
    **Social Media Content**
    Generate 10 engaging Instagram/Social Media captions (mix of short & long). Use emojis.
    
    Tour Text:
    """ + text
    
    response = model.generate_content(prompt)
    return response.text

# --- MAIN INTERFACE ---
# Tabs allow user to choose method
tab1, tab2 = st.tabs(["🔗 Paste Link", "📝 Paste Text (Fallback)"])

# METHOD 1: URL
with tab1:
    url = st.text_input("Paste Tour Link Here")
    if st.button("Generate from Link"):
        if not api_key:
            st.warning("⚠️ Gemini API Key is missing.")
        elif not url:
            st.warning("⚠️ Please paste a URL.")
        else:
            genai.configure(api_key=api_key)
            with st.spinner("Accessing website..."):
                raw_text = extract_text_from_url(url)
                
                # If blocked (403) or Error, advise user to use Tab 2
                if raw_text == "403" or raw_text == "ERROR":
                    st.error("🚫 Website Blocked: This site has strong security.")
                    st.info("👉 **Solution:** Click the 'Paste Text (Fallback)' tab above. Copy all the text from the website manually (Ctrl+A, Ctrl+C) and paste it there. It works 100% of the time!")
                elif raw_text:
                    model_name = get_working_model()
                    if model_name:
                        with st.spinner(f"Summarizing with {model_name}..."):
                            summary = generate_summary(raw_text, api_key, model_name)
                            st.success("Success!")
                            st.markdown("---")
                            st.markdown(summary)
                    else:
                        st.error("❌ No AI model found. Check API key.")
                else:
                    st.error("❌ Invalid URL or Connection Error.")

# METHOD 2: MANUAL TEXT
with tab2:
    st.info("💡 Use this if the link above fails. Go to the website, press **Ctrl+A** (Select All) then **Ctrl+C** (Copy), and paste here.")
    manual_text = st.text_area("Paste Website Text Here", height=300)
    
    if st.button("Generate from Text"):
        if not api_key:
            st.warning("⚠️ Gemini API Key is missing.")
        elif len(manual_text) < 50:
            st.warning("⚠️ Please paste more text.")
        else:
            genai.configure(api_key=api_key)
            model_name = get_working_model()
            if model_name:
                with st.spinner(f"Reading your text..."):
                    summary = generate_summary(manual_text, api_key, model_name)
                    st.success("Success!")
                    st.markdown("---")
                    st.markdown(summary)
            else:
                st.error("❌ No AI model found.")
