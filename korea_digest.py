"""Daily Korea News Digest: fetches Korean news, summarizes with Claude, emails the digest."""

import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import feedparser
import requests

# Korean news RSS feeds
RSS_FEEDS = [
    ("Yonhap News", "https://en.yna.co.kr/RSS/news.xml"),
    ("Korea Herald", "http://www.koreaherald.com/rss/020100000000.xml"),
    ("Korea JoongAng Daily", "https://koreajoongangdaily.joins.com/section/rss/all-articles"),
    ("Arirang News", "https://www.arirang.com/rss/news_total.xml"),
    ("KBS World", "https://world.kbs.co.kr/rss/rss_news.htm?lang=e"),
]

BACKUP_FEEDS = [
    ("Yonhap English", "https://en.yna.co.kr/RSS/news.xml"),
    ("NK News", "https://www.nknews.org/feed/"),
]


def fetch_rss_articles(feeds: list[tuple[str, str]], max_per_feed: int = 15) -> list[dict]:
    """Fetch recent articles from RSS feeds."""
    articles = []
    for source_name, url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                title = entry.get("title", "").strip()
                summary = entry.get("summary", entry.get("description", "")).strip()
                link = entry.get("link", "")
                published = entry.get("published", entry.get("updated", ""))
                if title:
                    articles.append({
                        "source": source_name,
                        "title": title,
                        "summary": summary[:500],
                        "link": link,
                        "published": published,
                    })
        except Exception as e:
            print(f"Warning: Failed to fetch from {source_name}: {e}")
    return articles


def build_news_context(articles: list[dict]) -> str:
    """Format articles into a text block for Claude."""
    if not articles:
        return "No articles were fetched today."
    lines = []
    for i, a in enumerate(articles, 1):
        lines.append(f"[{i}] {a['source']} — {a['title']}")
        if a["summary"]:
            lines.append(f"    {a['summary']}")
        if a["link"]:
            lines.append(f"    Link: {a['link']}")
        lines.append("")
    return "\n".join(lines)


def generate_digest(articles: list[dict]) -> str:
    """Use Claude to create an email-ready news digest."""
    client = anthropic.Anthropic()
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    news_context = build_news_context(articles)

    prompt = f"""You are a professional news editor creating a daily Korea news digest email for {today}.

Below are today's raw news articles from Korean media sources. Create a well-organized, engaging email digest.

FORMAT REQUIREMENTS:
- Write in clean HTML suitable for email
- Start with a brief 1-2 sentence overview of the day's top themes
- Group stories into logical sections (e.g., Politics, Economy, Society, Tech, Culture, North Korea)
- For each section, summarize the key stories in 2-3 sentences each
- Include source attribution and links where available
- End with a "Quick Hits" section for minor but interesting stories
- Keep the tone professional but accessible
- Only include sections that have relevant stories (skip empty categories)
- Do NOT include a subject line or email headers — just the body content

RAW ARTICLES:
{news_context}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def send_email(subject: str, html_body: str, text_body: str) -> None:
    """Send the digest email via Gmail SMTP."""
    gmail_address = os.environ["GMAIL_ADDRESS"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    recipients = [e.strip() for e in os.environ["RECIPIENT_EMAILS"].split(",") if e.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Korea News Digest <{gmail_address}>"
    msg["To"] = ", ".join(recipients)

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(gmail_address, gmail_password)
        server.sendmail(gmail_address, recipients, msg.as_string())

    print(f"Digest sent to {len(recipients)} recipient(s).")


def main() -> None:
    # Validate environment
    for var in ("ANTHROPIC_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "RECIPIENT_EMAILS"):
        if not os.environ.get(var):
            raise SystemExit(f"Error: {var} environment variable is not set.")

    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    print(f"Generating Korea News Digest for {today}...")

    # Fetch news
    articles = fetch_rss_articles(RSS_FEEDS)
    if len(articles) < 5:
        print("Few articles from primary feeds, trying backup feeds...")
        articles.extend(fetch_rss_articles(BACKUP_FEEDS))
    print(f"Fetched {len(articles)} articles from RSS feeds.")

    if not articles:
        print("No articles fetched. Skipping digest.")
        return

    # Generate digest with Claude
    print("Generating digest with Claude...")
    html_digest = generate_digest(articles)

    # Wrap in a styled email template
    html_email = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Georgia, serif; max-width: 680px; margin: 0 auto; padding: 20px; color: #1a1a1a;">
  <div style="border-bottom: 3px solid #003478; padding-bottom: 12px; margin-bottom: 24px;">
    <h1 style="margin: 0; color: #003478;">Korea Daily Digest</h1>
    <p style="margin: 4px 0 0; color: #666; font-size: 14px;">{today}</p>
  </div>
  {html_digest}
  <div style="border-top: 1px solid #ddd; margin-top: 32px; padding-top: 12px; font-size: 12px; color: #999;">
    <p>Generated by Korea Daily Digest &bull; Powered by Claude</p>
  </div>
</body>
</html>"""

    # Plain text fallback
    text_email = f"Korea Daily Digest — {today}\n\nView this email in HTML for the best experience.\n"

    subject = f"Korea Daily Digest — {today}"
    send_email(subject, html_email, text_email)
    print("Done!")


if __name__ == "__main__":
    main()
