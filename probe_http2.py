"""Compare Instagram's answer to the same request over HTTP/1.1 and HTTP/2."""

import base64
import os
import pickle
import sys

import httpx
import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HEADERS = {
    "X-IG-App-ID": "936619743392459",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
}

TARGETS = [
    ("profile", "https://www.instagram.com/api/v1/users/web_profile_info/?username=wwe"),
    ("feed", "https://i.instagram.com/api/v1/feed/timeline/"),
]


def load_cookies():
    """instaloader pickles a plain name-to-value cookie dict."""
    data = pickle.loads(base64.b64decode(os.environ["IG_SESSION_B64"].strip()))
    return {k: str(v) for k, v in data.items()}


def report(name, status, body):
    text = " ".join(str(body).split())[:160]
    print(f"{name}: HTTP {status} · {text}")


def main():
    if not os.environ.get("IG_SESSION_B64", "").strip():
        sys.exit("IG_SESSION_B64 تنظیم نشده است.")
    cookies = load_cookies()
    print(f"کوکی‌ها: {', '.join(sorted(cookies))}")

    for name, url in TARGETS:
        try:
            r1 = requests.get(url, headers=HEADERS, cookies=cookies, timeout=30)
            report(f"{name} http/1.1", r1.status_code, r1.text)
        except Exception as exc:
            print(f"{name} http/1.1: خطا {type(exc).__name__}: {exc}")

        try:
            with httpx.Client(http2=True, headers=HEADERS, cookies=cookies, timeout=30) as client:
                r2 = client.get(url)
            report(f"{name} http/2 ", r2.status_code, r2.text)
        except Exception as exc:
            print(f"{name} http/2 : خطا {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
