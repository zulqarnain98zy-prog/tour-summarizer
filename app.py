import streamlit as st
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai

# Page Config
st.set_page_config(page_title="Tour Summarizer Pro", page_icon="✈️", layout="wide")

st.title("✈️ Tour Activity Summarizer (Custom Order)")
st.markdown("Paste a tour link to generate a summary with your specific criteria arrangement.")

# --- API Key Handling ---
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Enter Gemini API Key", type="password")

# --- Functions ---
def get_working_model():
    """
    Automatically finds a model that works for your API key.
    """
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
    model = genai.GenerativeModel(model_name)
    
    # --- UPDATED PROMPT WITH REARRANGED CRITERIA ---
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
    11. **Unit Types & Prices**: List Adult, Child, Infant, Senior prices if available in the text. (Note: if prices are dynamic/hidden, mention "Check availability for pricing").
    12. **Policies**: Cancellation policy and Confirmation type (instant/manual).
    13. **SEO Keywords**: 3 high-traffic search keywords relevant to this specific activity.

    ---
    **Social Media Content**
    Generate 10 engaging Instagram/Social Media captions relevant to this activity. 
    Mix short, punchy captions with longer, descriptive ones. Use emojis.
    
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
        genai.configure(api_key=api_key)
        
        with st.spinner("Finding the best AI model..."):
            model_name = get_working_model()
        
        if not model_name:
            st.error("❌ No available models found. Check API Key.")
        else:
            with st.spinner(f"Generating summary with custom order using {model_name}..."):
                raw_text = extract_text_from_url(url)
                
                if raw_text == "403":
                    st.error("🚫 Access Denied: This website blocks automated scrapers.")
                elif raw_text:
                    try:
                        summary = generate_summary(raw_text, api_key, model_name)
                        st.success("Success!")
                        st.markdown("---")
                        st.markdown(summary)
                    except Exception as e:
                        st.error(f"AI Error: {e}")
                else:
                    st.error("❌ Could not read the website.")
