"""Throwaway probe: can a public Instagram mirror give us post lists from a datacenter IP?

The idea is to stop depending on a logged-in session entirely. These sites scrape Instagram for
their own viewers and answer plain HTTP GETs; if one of them survives Cloudflare from GitHub Actions
and hands back CDN urls, the bot reads new posts there and only touches Instagram's CDN, which needs
no cookie at all. Delete this file and mirrors.yml once a source is chosen.
"""

import sys
import time

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

USER = "wwe"
BROKEN = "no-such-user-zzz-42"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
}

# Each source is tried for both a real profile and a nonsense one: a source that returns 200 and a
# non-empty payload for a user who does not exist is not actually giving us data.
SOURCES = [
    ("imginn · info", f"https://imginn.com/api/v3/user/{USER}/info/"),
    ("imginn · پست", f"https://imginn.com/api/v3/user/{USER}/posts/"),
    ("imginn · استوری", f"https://imginn.com/api/v3/user/{USER}/stories/"),
    ("picuki · api", "https://www.picuki.com/api/public.php?request_type=account&data=" + USER + "&page=1"),
    ("picuki · پروفایل", f"https://www.picuki.com/profile/{USER}"),
    ("picnob · پروفایل", f"https://www.picnob.com/profile/{USER}/"),
    ("pixwox · پروفایل", f"https://www.pixwox.com/profile/{USER}/"),
    ("dumpor · پروفایل", f"https://dumpor.app/profile/{USER}"),
    ("instanavigation", f"https://www.instanavigation.com/@{USER}"),
    ("storiesig · api", f"https://storiesig.info/api/ig/api.php?username={USER}"),
]

NEEDLES = ["cdninstagram.com", "instagram.com/p/", "shortcode", "image_url", "story", "taken_at"]


def judge(resp):
    body = resp.text
    found = [n for n in NEEDLES if n in body]
    server = resp.headers.get("server", "?")
    verdict = "داده دارد" if any(n in found for n in ("cdninstagram.com", "shortcode", "image_url")) else "داده ندارد"
    print(f"  {resp.status_code} · {len(body)} کاراکتر · server={server} · {verdict}")
    print(f"  نشانه‌ها: {', '.join(found) or '—'}")
    if not found:
        print(f"  نمونه: {' '.join(body[:180].split())}")
    return bool(found)


def main():
    for label, url in SOURCES:
        print(f"\n{label}\n  {url}")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=25, allow_redirects=True)
            ok = judge(resp)
        except Exception as exc:
            print(f"  ERR {type(exc).__name__}: {str(exc)[:160]}")
            continue
        if ok:
            time.sleep(1)
            try:
                ghost = requests.get(url.replace(USER, BROKEN), headers=HEADERS, timeout=25)
                print(f"  کاربر جعلی: {ghost.status_code} · {len(ghost.text)} کاراکتر")
            except Exception as exc:
                print(f"  کاربر جعلی: ERR {type(exc).__name__}")
        time.sleep(1)


if __name__ == "__main__":
    main()
