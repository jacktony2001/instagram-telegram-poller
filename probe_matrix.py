"""Throwaway probe: which identity actually makes i.instagram.com answer 200 from the runner.

Yesterday's 400 came back as checkpoint_required with lock:true. instagrapi's issues show the
same body for a mismatched app identity (web app-id on the private host, an old app version in
the user agent) rather than for a dead session, and the web API is known to fingerprint TLS.
Each row below is one combination; delete this file with the test-delivery workflow once the
winner is known.
"""

import base64
import os
import pickle
import random
import sys
import time
import uuid

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
PRIVATE = "https://i.instagram.com/api/v1"
PUBLIC = "https://www.instagram.com/api/v1"
WWE_PK = "45145019"


def session_cookies():
    blob = os.environ.get("IG_SESSION_B64", "").strip()
    if not blob:
        sys.exit("IG_SESSION_B64 تنظیم نشده است.")
    return {k: str(v) for k, v in pickle.loads(base64.b64decode(blob)).items()}


def build_session(transport, headers, jar):
    if transport == "cffi":
        from curl_cffi import requests as curl_cffi

        try:
            session = curl_cffi.Session(impersonate="chrome_126")
        except Exception:  # the alias depends on the curl_cffi version that got installed
            session = curl_cffi.Session(impersonate="chrome")
    else:
        session = requests.Session()
    session.headers.update(headers)
    session.cookies.update(jar)
    return session


def rows(jar):
    """rank_token of the app API is "<user_id>_<uuid>"; the web one is "<rand>,<rand>"."""
    if jar.get("ds_user_id"):
        rank_token = f"{jar['ds_user_id']}_{uuid.uuid4()}"
    else:
        rank_token = f"{random.randint(10**9, 10**10 - 1)},{random.randint(10**9, 10**10 - 1)}"
    web = {"User-Agent": CHROME_UA, "X-IG-App-ID": WEB_APP_ID, "Accept-Language": "en-US,en;q=0.9"}
    app = {"User-Agent": INSTAGRAM_UA, "X-IG-App-ID": APP_APP_ID, "X-IG-Connection-Type": "WIFI",
           "Accept-Language": "en-US,en;q=0.9"}
    timeline = {"rank_token": rank_token, "media_id": ""}
    user_feed = {"rank_token": rank_token, "ranked_content": "true", "count": "12", "max_id": ""}
    return [
        ("۱ timeline · app-id وب · WWW-Claim 0 · تنظیم فعلی", "requests",
         dict(web, **{"X-IG-WWW-Claim": "0", "X-Requested-With": "XMLHttpRequest"}), PRIVATE, "/feed/timeline/", timeline),
        ("۲ timeline · app-id وب · بی WWW-Claim", "requests", web, PRIVATE, "/feed/timeline/", timeline),
        ("۳ timeline · app-id اپ · UA اینستا", "requests", app, PRIVATE, "/feed/timeline/", timeline),
        ("۴ timeline · app-id اپ · TLS جعلی", "cffi", app, PRIVATE, "/feed/timeline/", timeline),
        ("۵ feed/user/<pk> · app-id اپ", "requests", app, PRIVATE, f"/feed/user/{WWE_PK}/", user_feed),
        ("۶ feed/user/<pk> · app-id اپ · TLS جعلی", "cffi", app, PRIVATE, f"/feed/user/{WWE_PK}/", user_feed),
        ("۷ reels_media · app-id اپ", "requests", app, PRIVATE, "/feed/reels_media/", {"reel_ids": WWE_PK}),
        ("۸ web_profile_info · TLS جعلی (کنترل ۴۲۹)", "cffi", dict(web, Referer="https://www.instagram.com/"),
         PUBLIC, "/users/web_profile_info/", {"username": "wwe"}),
    ]


def main():
    jar = session_cookies()
    print(f"کوکی‌های موجود: {', '.join(sorted(jar))}\n")
    for label, transport, headers, base, path, params in rows(jar):
        try:
            resp = build_session(transport, headers, jar).get(base + path, params=params, timeout=30)
            body = " ".join(resp.text[:180].split())
            print(f"{resp.status_code:>3} · {label}\n      {path} → {body}\n")
        except Exception as exc:
            print(f"ERR · {label}\n      {type(exc).__name__}: {exc}\n")
        time.sleep(1)


if __name__ == "__main__":
    main()
