"""Throwaway probe, second pass: how much can Instagram hand out with no cookie at all?

The first pass proved oEmbed answers 200 with a real scontent CDN URL while every other path either
needs the challenged session or is 429. That matters: it means GitHub's IP is not banned outright, it
just is not allowed to read feeds. Two questions are still open and they decide whether a
session-free route exists:

1. Does oEmbed carry enough to deliver a post (caption, every carousel slide, the video file), or only
   a thumbnail?
2. Is there any anonymous way to learn which shortcodes are new — robots.txt/sitemaps are built for
   crawlers and usually sit in the same loose protection class as oEmbed.

Delete this file with the mirrors workflow once a source is chosen.
"""

import re
import sys
import time

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html, application/xml, application/json, */*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
}

POST = "DdecWXJDhPS"
NATGEO = "DdcjXAeFyr8"

SOURCES = [
    ("oEmbed · کامل", f"https://www.instagram.com/api/v1/oembed/?url=https://www.instagram.com/p/{POST}/"),
    ("oEmbed · بی‌پارامتر اضافه", f"https://www.instagram.com/api/v1/oembed/?url=https://www.instagram.com/p/{NATGEO}/&omniture="),
    ("oEmbed · با maxwidth", f"https://www.instagram.com/api/v1/oembed/?url=https://www.instagram.com/p/{POST}/&max_width=1080&omit_script=true"),
    ("oEmbed · پروفایل", "https://www.instagram.com/api/v1/oembed/?url=https://www.instagram.com/wwe/"),
    ("dis · خودِ پست", f"https://www.instagram.com/p/{POST}/?__a=1&__d=dis"),
    ("dis · reel", f"https://www.instagram.com/reel/{POST}/?__a=1&__d=dis"),
    ("robots.txt", "https://www.instagram.com/robots.txt"),
    ("sitemap index", "https://www.instagram.com/sitemap.xml"),
    ("sitemap · accounts", "https://www.instagram.com/sitemaps/accounts/sitemap.xml"),
    ("sitemap · medias", "https://www.instagram.com/sitemaps/medias/sitemap.xml"),
    ("sitemap · پروفایل", "https://www.instagram.com/wwe/sitemap.xml"),
]


def dump_json(resp):
    try:
        data = resp.json()
    except ValueError:
        print(f"  JSON نیست · {' '.join(resp.text[:160].split())}")
        return
    print(f"  کلیدها: {sorted(data.keys())[:14]}")
    for key, value in data.items():
        if isinstance(value, str):
            print(f"  {key}: {' '.join(value.split())[:200]}")
        else:
            print(f"  {key}: {str(value)[:120]}")


def main():
    for label, url in SOURCES:
        print(f"\n{label}\n  {url}")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
            body = resp.text
            print(f"  {resp.status_code} · {len(body)} کاراکتر · type={resp.headers.get('content-type', '?')[:40]}")
            if resp.status_code != 200:
                print(f"  نمونه: {' '.join(body[:160].split())}")
            elif "json" in resp.headers.get("content-type", ""):
                dump_json(resp)
            elif "xml" in resp.headers.get("content-type", "") or body.lstrip().startswith("<?xml"):
                locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
                print(f"  <loc> ها: {len(locs)}")
                for loc in locs[:8]:
                    print(f"   {loc[:140]}")
            else:
                og = re.findall(r'<meta (?:property|name)="([^"]+)" content="([^"]{0,140})"', body)[:14]
                for name, content in og:
                    print(f"  {name}: {' '.join(content.split())}")
                if not og:
                    print(f"  نمونه: {' '.join(body[:400].split())}")
        except Exception as exc:
            print(f"  ERR {type(exc).__name__}: {str(exc)[:150]}")
        time.sleep(2)


if __name__ == "__main__":
    main()
