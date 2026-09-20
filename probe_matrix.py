"""Throwaway probe: is the Instagram session dead, or only the feed endpoints challenged?

The identity matrix answered the first half: the private host returns checkpoint_required for the
web app-id and challenge_required for the app app-id, so the headers are not the problem. What is
still unknown is whether the sessionid works anywhere at all, and whether the web API's 429 survives
curl_cffi's TLS fingerprint. Each row prints the status and what Instagram said.
Delete this file with the probe workflow once the answer is known.
"""

import base64
import json
import os
import pickle
import re
import sys
import time
import uuid
from random import randint

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WEB_APP_ID = "936619743392459"
APP_APP_ID = "567067343352427"
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
INSTAGRAM_UA = "Instagram 448.0.0.0.20 Android (34/14; 420dpi; 1080x2221; Google; Pixel 8 Pro; shiba; samsung; en_US)"
IHOST = "https://i.instagram.com/api/v1"
WHOST = "https://www.instagram.com/api/v1"
WWE_PK = "45145019"


def session_cookies():
    blob = os.environ.get("IG_SESSION_B64", "").strip()
    if not blob:
        sys.exit("IG_SESSION_B64 تنظیم نشده است.")
    return {k: str(v) for k, v in pickle.loads(base64.b64decode(blob)).items()}


def make(transport, headers, jar):
    if transport == "cffi":
        from curl_cffi import requests as curl_cffi

        session = curl_cffi.Session(impersonate="chrome")
    else:
        session = requests.Session()
    session.headers.update(headers)
    session.cookies.update(jar)
    return session


def rows(jar):
    web = {"User-Agent": CHROME_UA, "X-IG-App-ID": WEB_APP_ID, "Accept-Language": "en-US,en;q=0.9"}
    app = {"User-Agent": INSTAGRAM_UA, "X-IG-App-ID": APP_APP_ID, "X-IG-Connection-Type": "WIFI",
           "Accept-Language": "en-US,en;q=0.9"}
    rank = f"{jar.get('ds_user_id', randint(10**9, 10**10))}_{uuid.uuid4()}"
    return [
        # does the sessionid open any door at all, or is the whole account behind a challenge?
        ("۱ current_user · نشست زنده است؟", "requests", app, IHOST, "/accounts/current_user/", {"edit": "true"}),
        ("۲ timeline · همان تنظیم ربات", "requests", dict(web, **{"X-IG-WWW-Claim": "0"}),
         IHOST, "/feed/timeline/", {"rank_token": rank, "media_id": ""}),
        ("۳ timeline · TLS جعلی", "cffi", dict(web, **{"X-IG-WWW-Claim": "0"}),
         IHOST, "/feed/timeline/", {"rank_token": rank, "media_id": ""}),
        ("۴ feed/user · روی میزبان www · TLS جعلی", "cffi", web, WHOST, f"/feed/user/{WWE_PK}/",
         {"ranked_content": "true", "count": "12"}),
        ("۵ web_profile_info · روی میزبان www · TLS جعلی", "cffi", dict(web, Referer="https://www.instagram.com/"),
         "https://www.instagram.com", "/api/v1/users/web_profile_info/", {"username": "wwe"}),
        ("۶ نمای HTML پروفایل · کوکی نشست · TLS جعلی", "cffi", dict(web, Referer="https://www.instagram.com/"),
         "https://www.instagram.com", "/wwe/", {}),
        ("۷ reels_media · روی میزبان www · TLS جعلی", "cffi", web, WHOST, "/feed/reels_media/",
         {"reel_ids": WWE_PK}),
    ]


def describe(body):
    """Instagram buries the useful part in a JSON blob; quote the message and the challenge link."""
    try:
        data = json.loads(body)
    except ValueError:
        return " ".join(body[:160].split())
    message = data.get("message") or data.get("error_type") or "?"
    found = re.search(r"https://www\.instagram\.com/(challenge|accounts/[a-z_]+)[^\"\\]*", body)
    link = f"\n      بازکردنی: {found.group(0)}" if found else ""
    return f"{message} · {json.dumps({k: v for k, v in data.items() if k != 'checkpoint_url'}, ensure_ascii=False)[:150]}{link}"


def main():
    jar = session_cookies()
    print(f"کوکی‌های موجود: {', '.join(sorted(jar))}\n")
    for label, transport, headers, base, path, params in rows(jar):
        try:
            resp = make(transport, headers, jar).get(base + path, params=params, timeout=30)
            print(f"{resp.status_code:>3} · {label}\n      {describe(resp.text)}\n")
        except Exception as exc:
            print(f"ERR · {label}\n      {type(exc).__name__}: {exc}\n")
        time.sleep(2)


if __name__ == "__main__":
    main()
