import os
import json
import time
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from datetime import datetime, timedelta
import re

# ==========================================
# 1. SECURE CONFIGURATION (USING ENV VARIABLES)
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is missing! Please set it in GitHub Secrets.")

genai.configure(api_key=GEMINI_API_KEY)

# Use the fast and cheap flash model
generation_config = {
    "temperature": 0.3, 
    "response_mime_type": "application/json", 
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
# 3. ROBUST WEB SCRAPING (THE GUARDIAN)
# ==========================================
def fetch_latest_editorials():
    print("Fetching live CAT-level editorials from The Guardian...")
    articles = []
    
    # Using The Guardian Editorials: Best for CAT, High Vocabulary, No Paywall Blocking
    rss_url = "https://www.theguardian.com/profile/editorial/rss"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    try:
        response = requests.get(rss_url, headers=headers, timeout=15)
        response.raise_for_status() 
        soup = BeautifulSoup(response.content, 'xml')
        
        # Get the top 2 latest articles
        items = soup.find_all('item')[:2]
        
        if not items:
            print("Warning: No items found in the RSS feed.")
            return articles

        for item in items:
            title = item.title.text
            link = item.link.text
            print(f"Scraping link: {link}")
            
            # Visit the actual article link
            time.sleep(2) 
            art_resp = requests.get(link, headers=headers, timeout=15)
            art_soup = BeautifulSoup(art_resp.content, 'html.parser')
            
            # The Guardian uses <p> tags natively. We scrape all of them.
            paragraphs = art_soup.find_all('p')
            
            content_pieces = []
            for p in paragraphs:
                text = p.text.strip()
                # Filter out standard ad/promo/newsletter texts
                if len(text) > 50 and "Sign up" not in text and "Subscribe" not in text and "newsletter" not in text:
                    content_pieces.append(text)
            
            full_content = " ".join(content_pieces)
            
            if len(full_content) < 300:
                 print(f"Warning: Scraped content for '{title}' is too short. Skipping.")
                 continue

            # Limit to ~800 words to save AI processing tokens & ensure CAT RC length
            words = full_content.split()
            if len(words) > 800:
                full_content = " ".join(words[:800]) + "..."
                
            if full_content:
                    articles.append({
                        "title": title,
                        "content": full_content,
                        "theme": "Global Affairs / CAT Standard Read"
                    })
                
    except Exception as e:
        print(f"Error fetching live news: {e}")
        
    return articles

def process_article_with_ai(article):
    """Sends the article to Gemini AI to get CAT-level analysis in JSON format."""
    print(f"Sending to AI: {article['title']}")
    
    prompt = f"Article Title: {article['title']}\n\nContent:\n{article['content']}"
    
    try:
        response = model.generate_content(SYSTEM_PROMPT + "\n\n" + prompt)
        ai_analysis = json.loads(response.text)
        
        return {
            "id": f"art-{int(time.time())}-{hash(article['title']) % 10000}",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "title": article["title"],
            "content": article["content"],
            "theme": article["theme"],
            "readTime": f"{max(1, len(article['content'].split()) // 200)} min", 
            **ai_analysis 
        }
    except Exception as e:
        print(f"Error AI processing '{article['title']}': {e}")
        return None

# ==========================================
# 4. DATABASE MANAGEMENT
# ==========================================
def update_database():
    db_file = "data.json"
    
    database = []
    
    if os.path.exists(db_file):
        with open(db_file, "r", encoding="utf-8") as f:
            try:
                content = f.read().strip()
                if content: 
                     database = json.loads(content)
            except json.JSONDecodeError:
                print(f"Warning: {db_file} is corrupted or empty. Starting fresh.")
                database = []

    # Fetch Real News
    new_articles_raw = fetch_latest_editorials()
    
    if not new_articles_raw:
        print("No articles fetched. Exiting update process.")
        # Ensure we at least save an empty array so git doesn't throw pathspec error
        if not os.path.exists(db_file) or os.path.getsize(db_file) == 0:
            with open(db_file, "w", encoding="utf-8") as f:
                json.dump([], f)
        return

    new_articles_processed = []
    for raw_article in new_articles_raw:
        is_duplicate = any(db_art.get("title") == raw_article["title"] for db_art in database)
        if not is_duplicate:
            processed = process_article_with_ai(raw_article)
            if processed:
                new_articles_processed.append(processed)
                time.sleep(3) 
        else:
            print(f"Skipping duplicate: {raw_article['title']}")

    # Merge and save
    database = new_articles_processed + database

    thirty_days_ago = datetime.now() - timedelta(days=30)
    
    filtered_db = []
    for art in database:
        try:
             art_date = datetime.strptime(art["date"], "%Y-%m-%d")
             if art_date >= thirty_days_ago:
                 filtered_db.append(art)
        except (ValueError, KeyError):
             filtered_db.append(art)

    with open(db_file, "w", encoding="utf-8") as f:
        json.dump(filtered_db, f, ensure_ascii=False, indent=4)
        
    print(f"Successfully added {len(new_articles_processed)} articles. Total articles in DB: {len(filtered_db)}")

if __name__ == "__main__":
    print(f"Starting live daily editorial fetch for {datetime.now().strftime('%Y-%m-%d')}")
    update_database()
