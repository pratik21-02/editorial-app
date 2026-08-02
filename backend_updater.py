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
# 3. ROBUST WEB SCRAPING (THE HINDU)
# ==========================================
def fetch_latest_editorials():
    print("Fetching live editorials from The Hindu...")
    articles = []
    
    # 1. RSS feed URL for The Hindu Editorials
    rss_url = "https://www.thehindu.com/opinion/editorial/feeder/default.rss"
    
    # Adding more browser-like headers to avoid being blocked
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5'
    }
    
    try:
        response = requests.get(rss_url, headers=headers, timeout=15)
        response.raise_for_status() # Raise an exception for bad status codes
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
            
            # 2. Visit the actual article link to scrape paragraphs
            time.sleep(2) # Be polite to the server
            art_resp = requests.get(link, headers=headers, timeout=15)
            art_resp.raise_for_status()
            art_soup = BeautifulSoup(art_resp.content, 'html.parser')
            
            # The Hindu usually puts article content inside divs with class 'articlebodycontent' or similar
            # If that fails, we fallback to scraping all paragraphs.
            content_div = art_soup.find('div', class_=re.compile(r'articlebodycontent', re.IGNORECASE))
            
            if content_div:
                 paragraphs = content_div.find_all('p')
            else:
                 paragraphs = art_soup.find_all('p')
            
            # 3. Clean up the text
            content_pieces = []
            for p in paragraphs:
                text = p.text.strip()
                # Filter out standard ad/promo texts and very short lines
                if len(text) > 40 and "Click here" not in text and "Also Read" not in text and "Subscribe" not in text:
                    content_pieces.append(text)
            
            full_content = " ".join(content_pieces)
            
            # Ensure we actually scraped something before adding it
            if len(full_content) < 200:
                 print(f"Warning: Scraped content for '{title}' is too short. Might be a paywall or structure change.")
                 continue

            # Limit to ~800 words to save AI processing tokens & ensure CAT length
            words = full_content.split()
            if len(words) > 800:
                full_content = " ".join(words[:800]) + "..."
                
            if full_content:
                    articles.append({
                        "title": title,
                        "content": full_content,
                        "theme": "Current Affairs / Editorial"
                    })
                
    except requests.exceptions.RequestException as e:
        print(f"Network error fetching news: {e}")
    except Exception as e:
        print(f"Unexpected error fetching live news: {e}")
        
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
        print(f"Raw AI Response (if available): {getattr(response, 'text', 'No response text')}")
        return None

# ==========================================
# 4. DATABASE MANAGEMENT
# ==========================================
def update_database():
    db_file = "data.json"
    
    # IMPORTANT: Initialize database FIRST, before checking if file exists
    database = []
    
    if os.path.exists(db_file):
        with open(db_file, "r", encoding="utf-8") as f:
            try:
                content = f.read().strip()
                if content: # Only load if file is not empty
                     database = json.loads(content)
            except json.JSONDecodeError:
                print(f"Warning: {db_file} is corrupted or empty. Starting fresh.")
                database = []

    # Fetch Real News
    new_articles_raw = fetch_latest_editorials()
    
    if not new_articles_raw:
        print("No articles fetched. Exiting update process.")
        
        # If database is entirely empty and we fetched nothing, create an empty list file
        # so git doesn't crash on 'git add data.json'
        if not os.path.exists(db_file) or os.path.getsize(db_file) == 0:
            with open(db_file, "w", encoding="utf-8") as f:
                json.dump([], f)
            print("Created empty data.json to prevent git errors.")
        return

    new_articles_processed = []
    for raw_article in new_articles_raw:
        # Check if we already have this article based on title to avoid duplicates
        is_duplicate = any(db_art.get("title") == raw_article["title"] for db_art in database)
        if not is_duplicate:
            processed = process_article_with_ai(raw_article)
            if processed:
                new_articles_processed.append(processed)
                time.sleep(3) # Avoid rate limits
        else:
            print(f"Skipping duplicate: {raw_article['title']}")

    # Merge and save
    database = new_articles_processed + database

    thirty_days_ago = datetime.now() - timedelta(days=30)
    
    # Safely filter dates
    filtered_db = []
    for art in database:
        try:
             art_date = datetime.strptime(art["date"], "%Y-%m-%d")
             if art_date >= thirty_days_ago:
                 filtered_db.append(art)
        except (ValueError, KeyError):
             # If a date is malformed or missing, just keep it for now
             filtered_db.append(art)

    with open(db_file, "w", encoding="utf-8") as f:
        json.dump(filtered_db, f, ensure_ascii=False, indent=4)
        
    print(f"Successfully added {len(new_articles_processed)} articles. Total articles in DB: {len(filtered_db)}")

if __name__ == "__main__":
    print(f"Starting live daily editorial fetch for {datetime.now().strftime('%Y-%m-%d')}")
    update_database()
```

### Isme kya naya aur behtar hai?
1. **The Hindu RSS:** Maine URLs change kar diye hain aur scraper ko unki website ke hisaab se adapt kar diya hai.
2. **Error Handling & Empty File Fix:** Pehle code empty list save nahi karta tha agar news fail ho jaye, jisse git fail ho raha tha. Ab agar kuch scrape nahi hua, toh bhi ek valid khali `[]` json banegi taki workflow error 128 na de.
3. **Paywall check:** *The Hindu* mein kai baar chota article dikhta hai (paywall). Code ab length check karke chote articles reject kar dega.
4. **Headers:** Thode modern headers lagaye hain taki website usko bot na samjhe.

Isko commit karke dobara Action run kijiye! Action tab ke logs check zarur karna.
