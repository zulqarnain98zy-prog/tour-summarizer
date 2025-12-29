import streamlit as st
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai

# Page Config
st.set_page_config(page_title="Tour Summarizer", page_icon="✈️", layout="wide")

st.title("✈️ Tour Activity Summarizer (Free Version)")
st.markdown("Paste a tour link (GetYourGuide, Viator, Klook, etc.) to generate a standard summary.")

# --- API Key Handling ---
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Enter Gemini API Key", type="password")

# --- Functions ---
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

def generate_summary(text, key):
    # Configure Gemini
    genai.configure(api_key=key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
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
        with st.spinner("Analyzing tour content..."):
            raw_text = extract_text_from_url(url)
            
            if raw_text == "403":
                st.error("🚫 Access Denied: This website blocks automated scrapers. Try copying the text manually.")
            elif raw_text:
                try:
                    summary = generate_summary(raw_text, api_key)
                    st.success("Summary Generated!")
                    st.markdown("---")
                    st.markdown(summary)
                except Exception as e:
                    st.error(f"AI Error: {e}")
            else:
                st.error("❌ Could not read the website.")
