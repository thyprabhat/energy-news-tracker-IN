#!/usr/bin/env python3
"""
Energy News Tracker for India's large power consumers.

What it does, every run:
  1. Reads config.json (your topics, keywords, weights, exclude terms).
  2. Pulls recent articles per keyword via Google News RSS.
  3. Drops anything already seen in the last 14 days, and anything matching
     an exclude term.
  4. Groups + scores what's left by topic, sorts by recency.
  5. Writes a dated Markdown digest to digests/YYYY-MM-DD.md.
  6. Emails the same digest (as HTML) if SMTP secrets are configured.

HOW TO "POLISH" THIS OVER TIME
  Everything you'll want to tune lives in config.json, not this file:
    - Add/remove search terms under a topic to widen or narrow coverage.
    - Raise a topic's "weight" to push it higher in the digest ordering.
    - Add noisy terms to "exclude_terms" as you notice irrelevant hits.
    - Add a brand-new topic block to start tracking a new angle.
  You should rarely need to edit this script itself.
"""

import hashlib
import html
import json
import os
import re
import smtplib
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import feedparser

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
SEEN_PATH = BASE_DIR / "seen.json"
DIGESTS_DIR = BASE_DIR / "digests"
SEEN_RETENTION_DAYS = 14

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"


# --------------------------------------------------------------------------
# Config / state
# --------------------------------------------------------------------------

def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_seen(path: Path = SEEN_PATH) -> dict:
    if not path.exists():
        return {"seen": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_seen(seen_hashes: list, path: Path = SEEN_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"seen": seen_hashes}, f, indent=2)


def prune_seen(seen_entries: list) -> list:
    """Keep only hashes recorded within the retention window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=SEEN_RETENTION_DAYS)
    kept = []
    for entry in seen_entries:
        try:
            recorded = datetime.fromisoformat(entry["date"])
        except (KeyError, ValueError):
            continue
        if recorded >= cutoff:
            kept.append(entry)
    return kept


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

def build_query_url(term: str) -> str:
    query = urllib.parse.quote(f'{term} when:2d')
    return GOOGLE_NEWS_RSS.format(query=query)


def normalize_title(title: str) -> str:
    """Collapse whitespace/punctuation so near-duplicate headlines dedupe."""
    t = title.lower()
    t = re.sub(r"[^a-z0-9\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def title_hash(title: str) -> str:
    return hashlib.sha256(normalize_title(title).encode("utf-8")).hexdigest()


def fetch_articles_for_term(term: str, lookback_hours: int) -> list:
    """Fetch and lightly parse one keyword's RSS feed. Never raises;
    returns an empty list on any fetch/parse problem so one bad feed
    doesn't take down the whole run."""
    url = build_query_url(term)
    articles = []
    try:
        feed = feedparser.parse(url)
    except Exception as e:  # pragma: no cover - defensive
        print(f"  [warn] failed to fetch '{term}': {e}", file=sys.stderr)
        return articles

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    for entry in getattr(feed, "entries", []):
        title = getattr(entry, "title", "").strip()
        link = getattr(entry, "link", "").strip()
        if not title or not link:
            continue

        published_dt = None
        if getattr(entry, "published_parsed", None):
            published_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        if published_dt and published_dt < cutoff:
            continue

        source = ""
        if getattr(entry, "source", None) is not None:
            source = getattr(entry.source, "title", "") or ""

        articles.append({
            "title": title,
            "link": link,
            "source": source,
            "published": published_dt.isoformat() if published_dt else None,
        })

    return articles


# --------------------------------------------------------------------------
# Scoring / filtering
# --------------------------------------------------------------------------

def matches_exclude(title: str, exclude_terms: list) -> bool:
    lowered = title.lower()
    return any(term.lower() in lowered for term in exclude_terms)


def collect_topic_articles(topic: dict, lookback_hours: int, exclude_terms: list,
                            already_seen: set) -> list:
    seen_in_this_topic = set()
    collected = []

    for term in topic["terms"]:
        for art in fetch_articles_for_term(term, lookback_hours):
            h = title_hash(art["title"])
            if h in already_seen or h in seen_in_this_topic:
                continue
            if matches_exclude(art["title"], exclude_terms):
                continue
            seen_in_this_topic.add(h)
            art["hash"] = h
            collected.append(art)

    # Most recent first; undated articles sort last.
    collected.sort(key=lambda a: a["published"] or "", reverse=True)
    return collected


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def render_markdown(date_str: str, topic_results: list) -> str:
    lines = [f"# Energy News Digest — India Large Consumers ({date_str})", ""]
    any_articles = any(items for _, items in topic_results)

    if not any_articles:
        lines.append("_No new articles matched your topics in this window._")
        return "\n".join(lines)

    for topic_name, articles in topic_results:
        if not articles:
            continue
        lines.append(f"## {topic_name}")
        lines.append("")
        for art in articles:
            src = f" — *{art['source']}*" if art["source"] else ""
            lines.append(f"- [{art['title']}]({art['link']}){src}")
        lines.append("")

    return "\n".join(lines)


def render_html(date_str: str, topic_results: list) -> str:
    parts = [f"<h1>Energy News Digest — India Large Consumers ({date_str})</h1>"]
    any_articles = any(items for _, items in topic_results)

    if not any_articles:
        parts.append("<p><em>No new articles matched your topics in this window.</em></p>")
        return "\n".join(parts)

    for topic_name, articles in topic_results:
        if not articles:
            continue
        parts.append(f"<h2>{html.escape(topic_name)}</h2><ul>")
        for art in articles:
            src = f" &mdash; <em>{html.escape(art['source'])}</em>" if art["source"] else ""
            parts.append(
                f'<li><a href="{html.escape(art["link"])}">{html.escape(art["title"])}</a>{src}</li>'
            )
        parts.append("</ul>")

    return "\n".join(parts)


# --------------------------------------------------------------------------
# Email (optional — skipped gracefully if secrets aren't set)
# --------------------------------------------------------------------------

def send_email(subject: str, html_body: str) -> None:
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    email_to = os.environ.get("EMAIL_TO")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))

    if not (smtp_user and smtp_pass and email_to):
        print("[info] SMTP secrets not set — skipping email, digest file still saved.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = email_to
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [email_to], msg.as_string())
        print("[info] Email sent.")
    except Exception as e:
        print(f"[warn] Email send failed: {e}", file=sys.stderr)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    config = load_config()
    lookback_hours = config.get("lookback_hours", 30)
    max_per_topic = config.get("max_articles_per_topic", 10)
    exclude_terms = config.get("exclude_terms", [])

    seen_state = prune_seen(load_seen().get("seen", []))
    already_seen_hashes = {entry["hash"] for entry in seen_state}

    topic_results = []
    new_hashes_this_run = []

    for topic in config["topics"]:
        print(f"[info] Fetching topic: {topic['name']}")
        articles = collect_topic_articles(
            topic, lookback_hours, exclude_terms, already_seen_hashes
        )[:max_per_topic]
        topic_results.append((topic["name"], articles))
        for art in articles:
            new_hashes_this_run.append(art["hash"])
            already_seen_hashes.add(art["hash"])  # avoid cross-topic dupes too

    today = datetime.now(timezone.utc)
    date_str = today.strftime("%Y-%m-%d")

    md = render_markdown(date_str, topic_results)
    html_body = render_html(date_str, topic_results)

    DIGESTS_DIR.mkdir(exist_ok=True)
    out_path = DIGESTS_DIR / f"{date_str}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[info] Digest written to {out_path}")

    now_iso = today.isoformat()
    updated_seen = seen_state + [
        {"hash": h, "date": now_iso} for h in new_hashes_this_run
    ]
    save_seen(updated_seen)

    send_email(f"Energy News Digest — India Large Consumers ({date_str})", html_body)


if __name__ == "__main__":
    main()
