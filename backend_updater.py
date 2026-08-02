import os
import json
import time
import requests
import google.generativeai as genai
from datetime import datetime, timedelta

# ==========================================
# 1. SECURE CONFIGURATION (USING ENV VARIABLES)
# ==========================================
# GitHub Actions will pass the GEMINI_API_KEY from GitHub Secrets securely
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is missing! Please set it in GitHub Secrets.")

genai.configure(api_key=GEMINI_API_KEY)

# Use the latest fast model
generation_config = {
    "temperature": 0.3, # Low temp for factual/analytical consistency
    "response_mime_type": "application/json", # Force JSON output
}
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash", 
    generation_config=generation_config
)

# ==========================================
# 2. AI PROMPT DESIGN
# ==========================================
SYSTEM_PROMPT = """
You are an expert English language instructor preparing students for the CAT (Common Admission Test) exam in India.
I will provide you with a news editorial. You must analyze it and return a strict JSON object with the following structure:
{
    "centralIdea": "A 1-2 sentence summary of the main point.",
    "tone": "2-3 words describing the author's tone (e.g., Analytical, Critical, Optimistic).",
    "skimming": ["Point 1", "Point 2", "Point 3", "Point 4"],
    "grammar": "A brief explanation of one interesting grammatical structure found in the text.",
    "vocab": [
        {
            "word": "difficult_word",
            "english": "English meaning",
            "gujarati": "Meaning in Gujarati script",
            "pos": "Noun/Verb/Adjective",
            "synonyms": "syn1, syn2",
            "antonyms": "ant1, ant2"
        }
    ],
    "idioms": [
        {
            "idiom": "idiom used in text",
            "meaning": "english meaning",
            "gujarati": "Gujarati meaning"
        }
    ]
}
Extract 4-5 difficult vocabulary words. If there are no idioms, leave the list empty.
"""

# ==========================================
# 3. FETCHING & PROCESSING LOGIC
# ==========================================
def fetch_latest_editorials():
    """
    In a real scenario, you would scrape a website or use a News API (like NewsAPI.org).
    For this example, we simulate fetching 2 articles for today.
    """
    # Replace this with real scraping logic (e.g., BeautifulSoup for The Hindu/Indian Express)
    return [
        {
            "title": "The Economic Balancing Act of 2026",
            "content": "As inflation reaches an inflection point, fiscal policies require pragmatic recalibration. The central bank's hawkish stance, while contentious, attempts to mitigate systemic vulnerabilities. However, the collateral damage to nascent startups cannot be overlooked.",
            "theme": "Economics"
        },
        {
            "title": "AI's Existential Threshold",
            "content": "The relentless march of generative AI poses profound ethical conundrums. Regulatory frameworks remain anachronistic, failing to encompass the nebulous boundaries of machine consciousness. A proactive paradigm shift is indispensable.",
            "theme": "Technology"
        }
    ]

def process_article_with_ai(article):
    """Sends the article to Gemini AI to get CAT-level analysis in JSON format."""
    print(f"Processing: {article['title']}")
    
    prompt = f"Article Title: {article['title']}\n\nContent:\n{article['content']}"
    
    try:
        # Combine system instructions with the user prompt
        response = model.generate_content(SYSTEM_PROMPT + "\n\n" + prompt)
        
        # Parse the JSON response from Gemini
        ai_analysis = json.loads(response.text)
        
        # Merge the original article data with the AI analysis
        return {
            "id": f"art-{int(time.time())}-{hash(article['title']) % 10000}",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "title": article["title"],
            "content": article["content"],
            "theme": article["theme"],
            "readTime": f"{max(1, len(article['content'].split()) // 200)} min", # roughly 200 wpm
            **ai_analysis # Unpack centralIdea, tone, vocab, etc.
        }
    except Exception as e:
        print(f"Error processing article '{article['title']}': {e}")
        return None

# ==========================================
# 4. DATABASE MANAGEMENT (data.json)
# ==========================================
def update_database():
    db_file = "data.json"
    
    # Load existing data if it exists
    if os.path.exists(db_file):
        with open(db_file, "r", encoding="utf-8") as f:
            try:
                database = json.load(f)
            except json.JSONDecodeError:
                database = []
    else:
        database = []

    # Fetch and process new articles
    new_articles_raw = fetch_latest_editorials()
    new_articles_processed = []
    
    for raw_article in new_articles_raw:
        processed = process_article_with_ai(raw_article)
        if processed:
            new_articles_processed.append(processed)
            time.sleep(2) # Sleep slightly to avoid hitting API rate limits

    # Add new articles to the front of the database
    database = new_articles_processed + database

    # Filter out articles older than 30 days to keep the file lightweight
    thirty_days_ago = datetime.now() - timedelta(days=30)
    database = [
        art for art in database 
        if datetime.strptime(art["date"], "%Y-%m-%d") >= thirty_days_ago
    ]

    # Save the updated database
    with open(db_file, "w", encoding="utf-8") as f:
        json.dump(database, f, ensure_ascii=False, indent=4)
        
    print(f"Successfully added {len(new_articles_processed)} articles. Total articles in DB: {len(database)}")

if __name__ == "__main__":
    print(f"Starting daily editorial fetch for {datetime.now().strftime('%Y-%m-%d')}")
    update_database()