import datetime
import os
import pathlib
import re

import feedparser
import requests

root = pathlib.Path(__file__).parent.resolve()

BLOG_FEED_URL = os.environ.get("BLOG_FEED_URL", "https://www.7fl.org/feed.xml").strip()
BLOG_POST_LIMIT = int(os.environ.get("BLOG_POST_LIMIT", "6"))
BLOG_LANGUAGE = os.environ.get("BLOG_LANGUAGE", "zh").strip().lower()
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "20"))
REQUEST_HEADERS = {"User-Agent": "readme-feed-updater/1.0"}


def replace_chunk(content, marker, chunk):
    pattern = re.compile(
        r"<!\-\- {} starts \-\->.*?<!\-\- {} ends \-\->".format(
            re.escape(marker), re.escape(marker)
        ),
        re.DOTALL,
    )
    replacement = "<!-- {} starts -->\n{}\n<!-- {} ends -->".format(marker, chunk, marker)
    return pattern.sub(replacement, content)


def parse_feed_with_fallback(feed_url):
    if not feed_url:
        return feedparser.parse("")

    direct_feed = feedparser.parse(feed_url)
    if getattr(direct_feed, "entries", None):
        return direct_feed

    direct_error = getattr(direct_feed, "bozo_exception", None)
    if direct_error:
        print(f"Direct feed parse failed for {feed_url}: {direct_error}")

    try:
        response = requests.get(
            feed_url,
            timeout=REQUEST_TIMEOUT,
            headers=REQUEST_HEADERS,
        )
        response.raise_for_status()
        fallback_feed = feedparser.parse(response.content)
        if getattr(fallback_feed, "entries", None):
            return fallback_feed
        print(f"Fallback feed parse returned no entries for {feed_url}")
        return fallback_feed
    except Exception as error:
        print(f"Fallback feed request failed for {feed_url}: {error}")
        return direct_feed


def format_entry_date(entry):
    raw = (entry.get("published") or entry.get("updated") or "").strip()
    if raw:
        if re.match(r"\d{4}-\d{2}-\d{2}", raw):
            return raw[:10]

        formats = [
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
        ]
        for fmt in formats:
            try:
                return datetime.datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue

    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime.datetime(
            parsed.tm_year,
            parsed.tm_mon,
            parsed.tm_mday,
        ).strftime("%Y-%m-%d")

    return raw or "Unknown date"


def contains_cjk(text):
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def is_allowed_entry(entry):
    if BLOG_LANGUAGE != "zh":
        return True

    link = (entry.get("link") or "").split("#")[0]
    title = entry.get("title", "")

    if "/en/" in link:
        return False

    return contains_cjk(title)


def fetch_blog_entries(feed_url, limit):
    feed = parse_feed_with_fallback(feed_url)
    entries = [
        {
            "title": entry.get("title", "Untitled"),
            "url": entry.get("link", "").split("#")[0],
            "published": format_entry_date(entry),
        }
        for entry in getattr(feed, "entries", [])
        if entry.get("link") and is_allowed_entry(entry)
    ]
    return entries[:limit]


if __name__ == "__main__":
    readme = root / "README.md"
    readme_contents = readme.read_text(encoding="utf-8")

    entries = fetch_blog_entries(BLOG_FEED_URL, BLOG_POST_LIMIT)
    if not entries:
        print("No blog content fetched, keeping existing blog block.")
        raise SystemExit(0)

    blog_md = "<br>".join(
        [
            "• [{title}]({url}) - {published}".format(**entry)
            for entry in entries
        ]
    )
    rewritten = replace_chunk(readme_contents, "blog", blog_md)
    readme.write_text(rewritten, encoding="utf-8")
