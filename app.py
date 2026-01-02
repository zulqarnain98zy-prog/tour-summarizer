import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import google.generativeai as genai

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

st.title("✈️ Global Tour Summarizer (Auto-Translate)")
st.markdown("Paste a link in **any language** (English, Chinese, Spanish, etc.) and get a standard **English summary**.")

# --- API KEY ---
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Enter Gemini API Key", type="password")

# --- HELPER FUNCTIONS ---
def get_working_model():
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
    try:
        # Browser emulation
        scraper = cloudscraper.create_scraper(browser='chrome')
        response = scraper.get(url, timeout=15)
        
        if response.status_code == 403:
            return "403"
        if response.status_code != 200:
            return None
            
        soup = BeautifulSoup(response.content, 'html.parser')
        
        for script in soup(["script", "style", "nav", "footer", "iframe"]):
            script.extract()
            
        text = soup.get_text(separator=' ')
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        return text[:25000] # Increased limit for foreign characters
    except Exception as e:
        return "ERROR"

def generate_summary(text, key, model_name):
    genai.configure(api_key=key)
    model = genai.GenerativeModel(model_name)
    
    # --- UPDATED PROMPT FOR TRANSLATION ---
    prompt = """
    You are an expert travel product manager.
    Analyze the following tour description.
    
    **CRITICAL INSTRUCTION:** The source text might be in a foreign language (Spanish, Chinese, French, etc.).
    You MUST translate all details and write the final response strictly in **ENGLISH**.
    
    Output format:
    
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
    13. **SEO Keywords**: 3 high-traffic search keywords in English.

    ---
    **Social Media Content**
    Generate 10 engaging Instagram/Social Media captions in English. 
    Mix short, punchy captions with longer, descriptive ones. Use emojis.
    
    Tour Text:
    """ + text
    
    response = model.generate_content(prompt)
    return response.text

# --- MAIN INTERFACE ---
tab1, tab2 = st.tabs(["🔗 Paste Link", "📝 Paste Text (Fallback)"])

# METHOD 1: URL
with tab1:
    url = st.text_input("Paste Tour Link Here (Any Language)")
    if st.button("Generate English Summary"):
        if not api_key:
            st.warning("⚠️ Gemini API Key is missing.")
        elif not url:
            st.warning("⚠️ Please paste a URL.")
        else:
            genai.configure(api_key=api_key)
            with st.spinner("Accessing website and translating..."):
                raw_text = extract_text_from_url(url)
                
                if raw_text == "403" or raw_text == "ERROR":
                    st.error("🚫 Website Blocked.")
                    st.info("👉 Use the 'Paste Text' tab. Copy the foreign text manually and paste it there. The AI will translate it.")
                elif raw_text:
                    model_name = get_working_model()
                    if model_name:
                        with st.spinner(f"Translating with {model_name}..."):
                            summary = generate_summary(raw_text, api_key, model_name)
                            st.success("Translation & Summary Complete!")
                            st.markdown("---")
                            st.markdown(summary)
                    else:
                        st.error("❌ No AI model found.")
                else:
                    st.error("❌ Invalid URL.")

# METHOD 2: MANUAL TEXT
with tab2:
    st.info("💡 Copy text from a Chinese/French/Spanish website and paste it here. We will translate it.")
    manual_text = st.text_area("Paste Foreign Text Here", height=300)
    
    if st.button("Translate & Generate"):
        if not api_key:
            st.warning("⚠️ Gemini API Key is missing.")
        elif len(manual_text) < 50:
            st.warning("⚠️ Please paste more text.")
        else:
            genai.configure(api_key=api_key)
            model_name = get_working_model()
            if model_name:
                with st.spinner(f"Translating..."):
                    summary = generate_summary(manual_text, api_key, model_name)
                    st.success("Success!")
                    st.markdown("---")
                    st.markdown(summary)
            else:
                st.error("❌ No AI model found.")
