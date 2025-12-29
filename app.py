import streamlit as st
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai

# Page Config
st.set_page_config(page_title="Tour Summarizer", page_icon="✈️", layout="wide")

st.title("✈️ Tour Activity Summarizer (Smart Fix)")
st.markdown("Paste a tour link to generate a standard summary.")

# --- API Key Handling ---
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Enter Gemini API Key", type="password")

# --- Functions ---
def get_working_model():
    """
    Automatically finds a model that works for your API key
    so you don't get 404 errors.
    """
    try:
        # Get list of all models available to your key
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        # Priority list: Try to find these specific ones first
        preferred_order = [
            'models/gemini-1.5-flash',
            'models/gemini-1.5-flash-001',
            'models/gemini-1.5-pro',
            'models/gemini-1.5-pro-001',
            'models/gemini-pro'
        ]
        
        # Check if any preferred model is available
        for model in preferred_order:
            if model in available_models:
                return model
        
        # If none of the preferred ones exist, just grab the first valid one
        if available_models:
            return available_models[0]
            
        return None
    except Exception as e:
        return None

def extract_text_from_url(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 403:
            return "403"
        if response.status_code != 200:
            return None
            
        soup = BeautifulSoup(response.content, 'html.parser')
        
        for script in soup(["script", "style", "nav", "footer"]):
            script.extract()
            
        text = soup.get_text(separator=' ')
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        return text[:15000]
    except Exception as e:
        return None

def generate_summary(text, key, model_name):
    genai.configure(api_key=key)
    
    # Use the model name we found earlier
    model = genai.GenerativeModel(model_name)
    
    prompt = """
    Analyze the following tour description and summarize it strictly into this format:
    
    1. **Highlights**: Exactly 4 bullet points.
    2. **What to Expect**: A description under 800 characters.
    3. **Activity Duration**: The total time.
    4. **Full Itinerary**: A step-by-step list.
    5. **Inclusions & Exclusions**: Two separate lists.
    6. **Additional Information**: Key logistics (what to bring, restrictions).
    7. **Start Time and End Time**: Specific times if mentioned, otherwise general timing.
    
    Tour Text:
    """ + text
    
    response = model.generate_content(prompt)
    return response.text

# --- Main Interface ---
url = st.text_input("Paste Tour Link Here")

if st.button("Generate Summary"):
    if not api_key:
        st.warning("⚠️ Gemini API Key is missing.")
    elif not url:
        st.warning("⚠️ Please paste a URL.")
    else:
        # Configure the API first to check models
        genai.configure(api_key=api_key)
        
        # 1. FIND A WORKING MODEL
        with st.spinner("Finding the best AI model..."):
            model_name = get_working_model()
        
        if not model_name:
            st.error("❌ No available models found for this API key. Please check your key permissions in Google AI Studio.")
        else:
            # 2. EXTRACT AND SUMMARIZE
            with st.spinner(f"Reading website using {model_name}..."):
                raw_text = extract_text_from_url(url)
                
                if raw_text == "403":
                    st.error("🚫 Access Denied: This website blocks automated scrapers. Try copying the text manually.")
                elif raw_text:
                    try:
                        summary = generate_summary(raw_text, api_key, model_name)
                        st.success("Summary Generated!")
                        st.markdown("---")
                        st.markdown(summary)
                    except Exception as e:
                        st.error(f"AI Error: {e}")
                else:
                    st.error("❌ Could not read the website.")
