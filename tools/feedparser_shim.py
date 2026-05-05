"""
Minimal RSS/Atom feed parser using stdlib xml.etree.ElementTree.
Implements just enough of the feedparser API used by scrape_rss_feeds.py.
"""
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "rss": "",
    "media": "http://search.yahoo.com/mrss/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}


def _strip_ns(tag):
    return re.sub(r"\{[^}]+\}", "", tag)


def _text(el, tag, default=""):
    if el is None:
        return default
    child = el.find(tag)
    if child is None:
        # Try without namespace
        for c in el:
            if _strip_ns(c.tag) == _strip_ns(tag.split("}")[-1] if "}" in tag else tag):
                return (c.text or "").strip()
        return default
    return (child.text or "").strip()


def _parse_date(s):
    """Parse RFC 822 or ISO 8601 date string → time.struct_time-like tuple."""
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
        return dt.timetuple()
    except Exception:
        pass
    # ISO 8601
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S+00:00",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s[:19], fmt[:len(s[:19])])
            return dt.timetuple()
        except Exception:
            pass
    return None


class _Entry:
    def __init__(self):
        self.title = ""
        self.link = ""
        self.summary = ""
        self.published_parsed = None
        self.updated_parsed = None
        self.created_parsed = None


class _Feed:
    def __init__(self):
        self.entries = []


def _find_text(el, *tags):
    for tag in tags:
        child = el.find(tag)
        if child is not None and child.text:
            return child.text.strip()
    # try stripping namespace
    for tag in tags:
        bare = _strip_ns(tag)
        for c in el:
            if _strip_ns(c.tag) == bare and c.text:
                return c.text.strip()
    return ""


def _get_link(el):
    # Atom: <link href="..."/>
    for child in el:
        if _strip_ns(child.tag) == "link":
            href = child.get("href")
            if href:
                return href
            if child.text and child.text.strip():
                return child.text.strip()
    return ""


def _parse_atom_entry(el):
    entry = _Entry()
    for child in el:
        tag = _strip_ns(child.tag)
        if tag == "title":
            entry.title = (child.text or "").strip()
        elif tag == "link":
            href = child.get("href")
            if href:
                entry.link = href
            elif child.text:
                entry.link = child.text.strip()
        elif tag in ("summary", "content"):
            if not entry.summary:
                entry.summary = (child.text or "").strip()
        elif tag == "published":
            entry.published_parsed = _parse_date((child.text or "").strip())
        elif tag == "updated":
            entry.updated_parsed = _parse_date((child.text or "").strip())
    return entry


def _parse_rss_item(el):
    entry = _Entry()
    for child in el:
        tag = _strip_ns(child.tag)
        if tag == "title":
            entry.title = (child.text or "").strip()
        elif tag == "link":
            entry.link = (child.text or "").strip()
        elif tag in ("description", "summary"):
            if not entry.summary:
                entry.summary = (child.text or "").strip()
        elif tag in ("encoded",):  # content:encoded
            entry.summary = (child.text or "").strip()
        elif tag == "pubDate":
            entry.published_parsed = _parse_date((child.text or "").strip())
        elif tag == "date":  # dc:date
            entry.published_parsed = _parse_date((child.text or "").strip())
        # <guid> sometimes is the link
        elif tag == "guid" and not entry.link:
            text = (child.text or "").strip()
            if text.startswith("http"):
                entry.link = text
    return entry


def parse(content):
    """Parse RSS or Atom feed from bytes/str content."""
    feed = _Feed()
    if not content:
        return feed
    try:
        if isinstance(content, str):
            content = content.encode("utf-8", errors="replace")
        # Strip BOM / bad chars
        content = content.lstrip(b"\xef\xbb\xbf")
        root = ET.fromstring(content)
    except ET.ParseError:
        # Try lxml if available
        try:
            from lxml import etree
            root = etree.fromstring(content)
            content_str = etree.tostring(root, encoding="unicode")
            root = ET.fromstring(content_str)
        except Exception:
            return feed

    root_tag = _strip_ns(root.tag)

    if root_tag == "feed":
        # Atom
        for child in root:
            if _strip_ns(child.tag) == "entry":
                feed.entries.append(_parse_atom_entry(child))
    else:
        # RSS 2.0 / RDF
        channel = root.find("channel")
        items_parent = channel if channel is not None else root
        for child in items_parent:
            if _strip_ns(child.tag) == "item":
                feed.entries.append(_parse_rss_item(child))
        # RDF-style: items at root level too
        if not feed.entries:
            for child in root:
                if _strip_ns(child.tag) == "item":
                    feed.entries.append(_parse_rss_item(child))

    return feed
