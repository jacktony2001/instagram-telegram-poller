"""Throwaway probe: do Instagram's own anonymous embed endpoints still answer from GitHub's IP?

Every third-party mirror sits behind Cloudflare and refuses the runner (403), and RSS-Bridge's public
instance returns 500 for them. Instagram's embed/oEmbed paths are different: they are built to render
inside other people's pages without a login, so they are not supposed to need a session, and they are
served by instagram.com itself rather than a mirror. If the post embed carries media URLs, the bot can
run on shortcodes alone with no cookie and no checkpoint to lose.

Delete this file together with the mirrors workflow once a source is chosen.
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
    "Accept": "text/html, application/json, */*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
}

# Real shortcodes taken from state.json, so the probes point at posts that exist.
POST = "DdecWXJDhPS"
STORY = "DdcVNQehPMP"

SOURCES = [
    ("پست · صفحه HTML", f"https://www.instagram.com/p/{POST}/"),
    ("پست · embed", f"https://www.instagram.com/p/{POST}/embed/"),
    ("پست · embed captioned", f"https://www.instagram.com/p/{POST}/embed/captioned/"),
    ("پست · oEmbed API", f"https://www.instagram.com/api/v1/oembed/?url=https://www.instagram.com/p/{POST}/&omniture="),
    ("پروفایل · embed", "https://www.instagram.com/wwe/embed/"),
    ("پروفایل · embed با scrolly", "https://www.instagram.com/wwe/embed/captioned/"),
    ("استوری · embed", f"https://www.instagram.com/p/{STORY}/embed/"),
    ("جست‌وجوی بدون لاگین", "https://www.instagram.com/web/search/topsearch/?query=wwe"),
]

# Something is only usable if the response names a real media host or a real post id.
NEEDLES = ["cdninstagram.com", "scontent", "og:image", "shortcode", "image_versions",
           "video_versions", "edge_media", "xdt_api", "thumbnail_src", "html"]


def judge(resp):
    body = resp.text
    found = [n for n in NEEDLES if n in body]
    print(f"  {resp.status_code} · {len(body)} کاراکتر · server={resp.headers.get('server', '?')} · "
          f"type={resp.headers.get('content-type', '?')[:40]}")
    print(f"  نشانه‌ها: {', '.join(found) or '—'}")
    urls = re.findall(r"https://[^\"'\\ ]+?(?:cdninstagram|scontent)[^\"'\\ ]+", body)[:3]
    for url in urls:
        print(f"  مدیا: {url[:150]}")
    metas = re.findall(r'<meta property="og:(?:image|title|description)" content="([^"]{0,120})', body)[:4]
    for meta in metas:
        print(f"  meta: {' '.join(meta.split())}")
    if not urls and not found:
        print(f"  نمونه: {' '.join(body[:160].split())}")


def main():
    for label, url in SOURCES:
        print(f"\n{label}\n  {url}")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
            judge(resp)
        except Exception as exc:
            print(f"  ERR {type(exc).__name__}: {str(exc)[:150]}")
        time.sleep(2)


if __name__ == "__main__":
    main()
