"""Throwaway probe: can a public RSS-Bridge instance hand us new posts and stories?

The mirrors themselves (imginn, pixnoy, imgsed) sit behind Cloudflare and answer 403 to GitHub's IP
ranges, but a bridge instance fetches them with its own address and hands back a feed. That would
remove the Instagram session from the picture entirely. What matters here is not just HTTP 200: the
feed has to carry per-post ids (shortcodes), media URLs, and something we can order by.
Delete this file with the mirrors workflow once a source is chosen.
"""

import re
import sys
import time
from xml.etree import ElementTree

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/json, text/html;q=0.9, */*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
}

IMGS = "bridge=Imgsed&context=Username&u={user}&post=on&story=on&format={fmt}"
BRIDGES = "https://rss-bridge.org/bridge01/?action=display&"

SOURCES = [
    ("rss-bridge.org · Imgsed · RSS", BRIDGES + IMGS.format(user="wwe", fmt="RSS")),
    ("rss-bridge.org · Imgsed · JSON", BRIDGES + IMGS.format(user="wwe", fmt="Json")),
    ("rss-bridge.org · Imgsed · natgeo", BRIDGES + IMGS.format(user="natgeo", fmt="RSS")),
    ("imgsed · استوری مستقیم", "https://imgsed.com/api/media/?name=wwe"),
    ("pixnoy · پروفایل مستقیم", "https://www.pixnoy.com/profile/wwe/"),
]


def describe(xml):
    """A feed we can poll has items, links with shortcodes, and dates we can compare."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        print(f"  XML نیست: {str(exc)[:80]} · نمونه: {' '.join(xml[:160].split())}")
        return
    items = root.iter("item")
    entries = list(items)
    print(f"  آیتم: {len(entries)}")
    codes, dates, cdn = [], [], 0
    for entry in entries[:6]:
        link = (entry.findtext("link") or "") + (entry.findtext("guid") or "")
        found = re.findall(r"/p/([A-Za-z0-9_-]{6,})/", link) or re.findall(r"/p/([A-Za-z0-9_-]{6,})", link)
        codes += found
        date = entry.findtext("pubDate") or entry.findtext("updated") or "?"
        dates.append(date)
        if "cdninstagram.com" in (link or "") or "scontent" in (entry.findtext("description") or ""):
            cdn += 1
        title = " ".join((entry.findtext("title") or "").split())[:60]
        print(f"   {date} · {title} · {link[:80]}")
    print(f"  shortcode: {len(codes)} از {len(entries)} · لینک CDN: {cdn} · تاریخ قابل‌مقایسه: {dates[:2]}")


def main():
    for label, url in SOURCES:
        print(f"\n{label}\n  {url}")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=45, allow_redirects=True)
            body = " ".join(resp.text[:150].split())
            print(f"  {resp.status_code} · {len(resp.text)} کاراکتر · server={resp.headers.get('server','?')} · "
                  f"type={resp.headers.get('content-type','?')[:40]}")
            if resp.status_code != 200:
                print(f"  نمونه: {body}")
            else:
                describe(resp.text)
        except Exception as exc:
            print(f"  ERR {type(exc).__name__}: {str(exc)[:150]}")
        time.sleep(2)


if __name__ == "__main__":
    main()
