"""Throwaway probe round 3: does anything on the web host still carry post data?

Round 2 settled the identity question — the private feed endpoints return checkpoint_required no
matter which app-id, user agent or TLS fingerprint is used, while the profile HTML page answers 200
and says logged-in. So the only route left to check is the web pages themselves: the JSON switch,
the embedded payload of the profile page, and the old anonymous query hash.
Delete this file with the probe workflow once the route is chosen.
"""

import base64
import json
import os
import pickle
import re
import sys
import time
from random import randint

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WEB_APP_ID = "936619743392459"
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
TOKEN = "1962238593"
USER = "wwe"
WEB = {"User-Agent": CHROME_UA, "X-IG-App-ID": WEB_APP_ID, "Accept-Language": "en-US,en;q=0.9",
       "Referer": f"https://www.instagram.com/{USER}/", "X-Asbd-Id": "129477"}


def session_cookies():
    blob = os.environ.get("IG_SESSION_B64", "").strip()
    if not blob:
        sys.exit("IG_SESSION_B64 تنظیم نشده است.")
    return {k: str(v) for k, v in pickle.loads(base64.b64decode(blob)).items()}


def make(transport, jar):
    if transport == "cffi":
        from curl_cffi import requests as curl_cffi

        session = curl_cffi.Session(impersonate="chrome")
    else:
        session = requests.Session()
    session.headers.update(WEB)
    session.cookies.update(jar)
    return session


def report(kind, body):
    """A page is only useful if the post array is actually inside it."""
    print(f"      طول پاسخ: {len(body)} کاراکتر")
    for marker in ("edge_owner_to_timeline_media", "shortcode_media", '"items"', "xdt_api__v1__feed", "checkpoint",
                   "LoginToContinue", "Page Not Found"):
        if marker in body:
            print(f"      ✓ {marker}")
    ids = sorted(set(re.findall(r'"(?:doc_id|query_hash)":"?([0-9a-f]{16,32})"', body)))
    if ids:
        print(f"      شناسه‌های کوئری: {', '.join(ids[:8])}")
    scripts = [s for s in re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', body, re.S)]
    for n, payload in enumerate(scripts, 1):
        if len(payload) > 2000:
            print(f"      اسکریپت {n}: {len(payload)} کاراکتر · {payload[:160]}")
    if kind == "json":
        try:
            data = json.loads(body)
            print(f"      کلیدهای بالا: {', '.join(list(data)[:8])}")
        except ValueError:
            print("      JSON نیست.")


def main():
    jar = session_cookies()
    targets = [
        ("۱ ?__a=1&__d=dis · سوئیچ JSON پروفایل", "json", f"https://www.instagram.com/{USER}/",
         {"__a": "1", "__d": "dis"}),
        ("۲ نمای HTML پروفایل", "html", f"https://www.instagram.com/{USER}/", {}),
        ("۳ کوئری قدیمی ناشناس با query_hash", "json", "https://www.instagram.com/graphql/query/",
         {"query_hash": "e769aa130647d2354c40ea6a439bfc08",
          "variables": json.dumps({"id": TOKEN, "first": 12}, separators=(",", ":"))}),
        ("۴ بی‌کوکی روی نمای HTML (نشست لازم است؟)", "html", f"https://www.instagram.com/{USER}/", {}),
    ]
    for n, (label, kind, url, params) in enumerate(targets):
        jar_used = {} if n == 3 else jar
        try:
            resp = make("cffi", jar_used).get(url, params=params, timeout=30)
            print(f"{resp.status_code:>3} · {label}")
            report(kind, resp.text)
        except Exception as exc:
            print(f"ERR · {label}\n      {type(exc).__name__}: {exc}")
        print()
        time.sleep(3)


if __name__ == "__main__":
    main()
