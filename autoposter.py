"""
autoposter.py
─────────────
Fetches trending news headlines, uses Claude (claude-sonnet-4-20250514) to write
full blog posts, and saves them to the database automatically.

Requires two API keys (set as environment variables):
  NEWS_API_KEY   — free at https://newsapi.org  (or uses GNews as fallback)
  ANTHROPIC_API_KEY — from https://console.anthropic.com

The scheduler runs every N hours (configurable via AUTO_POST_INTERVAL_HOURS env var,
default = 6). On startup it also runs immediately so you see results right away.
"""

import os
import re
import time
import logging
import requests
from groq import Groq
from datetime import datetime, timezone

log = logging.getLogger("autoposter")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [autoposter] %(message)s")

# ─── Config ───────────────────────────────────────────────────────────────────

NEWS_API_KEY         = os.environ.get("NEWS_API_KEY", "")
GROQ_API_KEY         = os.environ.get("GROQ_API_KEY", "")
INTERVAL_HOURS       = int(os.environ.get("AUTO_POST_INTERVAL_HOURS", "6"))
POSTS_PER_RUN        = int(os.environ.get("AUTO_POSTS_PER_RUN", "2"))   # how many per cycle
NEWS_COUNTRY         = os.environ.get("NEWS_COUNTRY", "us")             # newsapi country code
NEWS_CATEGORY        = os.environ.get("NEWS_CATEGORY", "")             # blank = top headlines
AI_AUTHOR            = "The Inkwell AI"

# Map news categories → blog category names
CATEGORY_MAP = {
    "technology": "Technology",
    "science":    "Technology",
    "business":   "Technology",
    "health":     "Culture",
    "entertainment": "Culture",
    "sports":     "Culture",
    "general":    "Culture",
    "":           "Culture",
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")[:120]

def calc_read_time(content: str) -> int:
    return max(1, len(content.split()) // 200)

# ─── News Fetching ────────────────────────────────────────────────────────────

def fetch_trending_headlines(n: int = 10) -> list[dict]:
    """
    Try NewsAPI first. Falls back to GNews (no key needed) if NewsAPI key is missing.
    Returns list of {"title": str, "description": str, "url": str, "category": str}
    """
    if NEWS_API_KEY:
        return _fetch_newsapi(n)
    else:
        log.warning("NEWS_API_KEY not set — falling back to GNews (limited results)")
        return _fetch_gnews(n)

def _fetch_newsapi(n: int) -> list[dict]:
    params = {
        "apiKey":   NEWS_API_KEY,
        "country":  NEWS_COUNTRY,
        "pageSize": n,
    }
    if NEWS_CATEGORY:
        params["category"] = NEWS_CATEGORY

    try:
        r = requests.get("https://newsapi.org/v2/top-headlines", params=params, timeout=10)
        r.raise_for_status()
        articles = r.json().get("articles", [])
        results = []
        for a in articles:
            title = a.get("title", "").split(" - ")[0].strip()  # remove source suffix
            if not title or title == "[Removed]":
                continue
            results.append({
                "title":       title,
                "description": a.get("description") or a.get("content") or "",
                "url":         a.get("url", ""),
                "category":    NEWS_CATEGORY or "general",
            })
        return results
    except Exception as e:
        log.error(f"NewsAPI error: {e}")
        return []

def _fetch_gnews(n: int) -> list[dict]:
    """GNews public endpoint — no key required, limited to 10/day."""
    try:
        r = requests.get(
            "https://gnews.io/api/v4/top-headlines",
            params={"lang": "en", "max": n, "apikey": "free"},
            timeout=10
        )
        # GNews free tier may 401 — just return empty and we skip the run
        if r.status_code != 200:
            log.warning(f"GNews returned {r.status_code}. Set NEWS_API_KEY for reliable news fetching.")
            return _mock_headlines()
        articles = r.json().get("articles", [])
        return [
            {
                "title":       a.get("title", ""),
                "description": a.get("description", ""),
                "url":         a.get("url", ""),
                "category":    "general",
            }
            for a in articles if a.get("title")
        ]
    except Exception as e:
        log.error(f"GNews error: {e}")
        return _mock_headlines()

def _mock_headlines() -> list[dict]:
    """
    Fallback demo headlines when no API key is configured.
    Claude will still write real articles from these.
    """
    from datetime import date
    today = date.today().strftime("%B %d, %Y")
    return [
        {
            "title": f"AI Breakthroughs Are Reshaping the Tech Industry in {date.today().year}",
            "description": "From language models to robotics, artificial intelligence is transforming how companies operate and how people work.",
            "url": "", "category": "technology",
        },
        {
            "title": "Global Leaders Meet to Discuss Climate Policy Ahead of Major Summit",
            "description": "Heads of state from over 50 countries gathered to align on emissions targets and green energy investment commitments.",
            "url": "", "category": "general",
        },
        {
            "title": "The Return of Long-Form Reading: Why People Are Buying Books Again",
            "description": "After years of declining sales, physical book purchases are surging — especially among younger readers.",
            "url": "", "category": "entertainment",
        },
        {
            "title": "New Study Reveals Surprising Benefits of Urban Green Spaces",
            "description": "Researchers found that access to parks and green infrastructure significantly improves mental health outcomes in city dwellers.",
            "url": "", "category": "health",
        },
    ]

# ─── AI Article Writer ────────────────────────────────────────────────────────

def generate_article(headline: dict) -> dict | None:
    """
    Call Groq to write a full blog post based on the headline.
    Returns {"title", "content", "excerpt"} or None on failure.
    """
    if not GROQ_API_KEY:
        log.error("GROQ_API_KEY not set — cannot generate articles.")
        return None

    client = Groq(api_key=GROQ_API_KEY)

    title       = headline["title"]
    description = headline["description"]
    source_url  = headline["url"]

    source_note = f"\nThe original news item is from: {source_url}" if source_url else ""

    prompt = f"""You are a skilled writer for "The Inkwell," an independent publication known for thoughtful, long-form essays.

A trending news story has been spotted:
HEADLINE: {title}
SUMMARY: {description}{source_note}

Write a complete, original blog article inspired by this news story. The article should:
- Be 400-600 words
- Open with a compelling first paragraph that draws the reader in
- Go beyond the surface news - offer context, analysis, historical parallels, or broader cultural significance
- Have a clear perspective and voice, not just neutral reporting
- End memorably
- NOT be a simple news summary - treat it as a jumping-off point for genuine writing
- Use only plain ASCII characters - no smart quotes, em dashes, or special characters
- Use paragraph breaks (blank lines between paragraphs) only - no markdown headers, bullets, or formatting

Structure your response EXACTLY like this with these exact markers:
TITLE: Your article title here
EXCERPT: One sentence summary under 150 characters
CONTENT:
Your full article text here, paragraphs separated by blank lines."""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.choices[0].message.content.strip()

        # Parse plain text response
        article_title = title
        excerpt = ""
        article_content = ""

        lines = raw.split("\n")
        content_started = False
        content_lines = []

        for line in lines:
            if line.startswith("TITLE:"):
                article_title = line.replace("TITLE:", "").strip()
            elif line.startswith("EXCERPT:"):
                excerpt = line.replace("EXCERPT:", "").strip()
            elif line.startswith("CONTENT:"):
                content_started = True
            elif content_started:
                content_lines.append(line)

        article_content = "\n".join(content_lines).strip()

        # Fallback if parsing fails
        if not article_content:
            article_content = raw

        return {
            "title":   article_title,
            "excerpt": excerpt or article_content[:200],
            "content": article_content,
        }
    except Exception as e:
        log.error(f"Groq generation error for '{title}': {e}")
        return None

# ─── Database Writer ──────────────────────────────────────────────────────────

def save_article(app, article: dict, news_category: str) -> bool:
    """Save a generated article to the database. Returns True if saved."""
    from app import db, Post, Category

    with app.app_context():
        # Check for duplicate title
        existing = Post.query.filter_by(title=article["title"]).first()
        if existing:
            log.info(f"  Skipping duplicate: {article['title']}")
            return False

        # Find or create category
        cat_name = CATEGORY_MAP.get(news_category.lower(), "Culture")
        cat = Category.query.filter_by(name=cat_name).first()
        if not cat:
            cat = Category(name=cat_name, slug=slugify(cat_name))
            db.session.add(cat)
            db.session.flush()

        # Build unique slug
        base_slug = slugify(article["title"])
        slug = base_slug
        count = 1
        while Post.query.filter_by(slug=slug).first():
            slug = f"{base_slug}-{count}"
            count += 1

        # Unfeature all previous posts, then feature this new one
        Post.query.update({"featured": False})

        post = Post(
            title=article["title"],
            slug=slug,
            content=article["content"],
            excerpt=article["excerpt"] or article["content"][:280] + "...",
            author=AI_AUTHOR,
            category_id=cat.id,
            published=True,
            featured=True,
            read_time=calc_read_time(article["content"]),
        )
        db.session.add(post)
        db.session.commit()
        log.info(f"  ✓ Posted: '{post.title}' [{cat_name}]")
        return True

# ─── Main Runner ──────────────────────────────────────────────────────────────

def run_autoposter(app):
    """Fetch trending news and post AI-written articles. Called by the scheduler."""
    log.info("─── Auto-poster running ───")
    headlines = fetch_trending_headlines(n=POSTS_PER_RUN * 3)  # fetch extra, some may be skipped

    if not headlines:
        log.warning("No headlines fetched. Check your NEWS_API_KEY.")
        return

    posted = 0
    for h in headlines:
        if posted >= POSTS_PER_RUN:
            break
        log.info(f"Generating article for: {h['title']}")
        article = generate_article(h)
        if not article:
            continue
        saved = save_article(app, article, h.get("category", ""))
        if saved:
            posted += 1
        time.sleep(1)  # be polite to the API

    log.info(f"─── Done. {posted} article(s) posted. ───")


def start_scheduler(app):
    """Start the APScheduler background scheduler."""
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(daemon=True)

    # Run immediately on startup
    scheduler.add_job(
        func=lambda: run_autoposter(app),
        id="autoposter_startup",
        next_run_time=datetime.now(timezone.utc),
    )

    # Then run every N hours
    scheduler.add_job(
        func=lambda: run_autoposter(app),
        trigger="interval",
        hours=INTERVAL_HOURS,
        id="autoposter_interval",
        replace_existing=True,
    )

    scheduler.start()
    log.info(f"Scheduler started — auto-posting every {INTERVAL_HOURS}h ({POSTS_PER_RUN} post(s)/run)")
    return scheduler
