"""Map which private-API routes answer from the runner, using the working feed/timeline."""

import base64
import os
import pickle
import random
import sys

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

API = "https://i.instagram.com/api/v1"
HEADERS = {
    "X-IG-App-ID": "936619743392459",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "X-IG-WWW-Claim": "0",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
}


def load_cookies():
    data = pickle.loads(base64.b64decode(os.environ["IG_SESSION_B64"].strip()))
    return {k: str(v) for k, v in data.items()}


def main():
    if not os.environ.get("IG_SESSION_B64", "").strip():
        sys.exit("IG_SESSION_B64 تنظیم نشده است.")
    session = requests.Session()
    session.headers.update(HEADERS)
    session.cookies.update(load_cookies())

    def get(name, url, params=None, bare=False):
        try:
            resp = session.get(url, params=params, timeout=30) if not bare else requests.get(url, timeout=30)
        except Exception as exc:
            print(f"{name}: خطا {type(exc).__name__}: {exc}")
            return None
        print(f"{name}: HTTP {resp.status_code} · {' '.join(resp.text.split())[:120]}")
        return resp

    rank_token = f"{random.randint(10**9, 10**10 - 1)},{random.randint(10**9, 10**10 - 1)}"
    first = get("feed/timeline", f"{API}/feed/timeline/", {"rank_token": rank_token, "media_id": ""})
    try:
        data = first.json()
    except Exception:
        print("پاسخ فید JSON نبود؛ همین‌جا می‌بندیم.")
        return

    media = [entry["media_or_ad"] for entry in data.get("feed_items", []) if "media_or_ad" in entry]
    owners = sorted({m["user"]["username"] for m in media if m.get("user")})
    print(f"آیتم‌های فید: {len(media)} · کاربران: {', '.join(owners) or 'هیچ'}")
    print(f"next_max_id: {data.get('next_max_id')} · أكثر آیتم: {data.get('more_available')}")
    if not media:
        return

    sample = media[0]
    user = sample["user"]
    pk = user["pk"]
    username = user["username"]
    print(f"نمونه: {username} · pk={pk} · نوع={sample.get('media_type')} · code={sample.get('code')}")

    page = data.get("next_max_id")
    if page:
        get("feed/timeline page2", f"{API}/feed/timeline/", {"rank_token": rank_token, "max_id": page})

    get(f"feed/user/{username}", f"{API}/feed/user/{pk}/", {"count": 12})
    get(f"clips/{username}", f"{API}/feed/user/{pk}/reel_media/")
    get(f"reels_media/{username}", f"{API}/feed/reels_media/", {"reel_ids": pk})
    get("reels_tray", f"{API}/feed/reels_tray/", {"reason": "pull_to_refresh"})
    get(f"info/{username}", f"{API}/users/{pk}/info/")

    candidates = (sample.get("image_versions2") or {}).get("candidates") or []
    if candidates:
        get("cdn image (بدون کوکی)", candidates[0]["url"], bare=True)
    videos = sample.get("video_versions") or []
    if videos:
        get("cdn video (بدون کوکی)", videos[0]["url"], bare=True)


if __name__ == "__main__":
    main()
