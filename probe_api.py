"""Find which private-API endpoints still answer from the GitHub runner."""

import base64
import os
import pickle
import sys

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

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
API = "https://i.instagram.com/api/v1"


def load_cookies():
    """instaloader pickles a plain name-to-value cookie dict."""
    data = pickle.loads(base64.b64decode(os.environ["IG_SESSION_B64"].strip()))
    return {k: str(v) for k, v in data.items()}


def show(name, resp):
    body = " ".join(resp.text.split())[:180]
    print(f"{name}: HTTP {resp.status_code} · {body}")


def main():
    if not os.environ.get("IG_SESSION_B64", "").strip():
        sys.exit("IG_SESSION_B64 تنظیم نشده است.")
    session = requests.Session()
    session.headers.update(HEADERS)
    session.cookies.update(load_cookies())

    def get(name, url, params=None):
        try:
            resp = session.get(url, params=params, timeout=30)
        except Exception as exc:
            print(f"{name}: خطا {type(exc).__name__}: {exc}")
            return None
        show(name, resp)
        return resp

    me = get("own account", f"{API}/users/{session.cookies.get('ds_user_id')}/info/")
    if me is None or not me.ok:
        print("نشست به API خصوصی دسترسی ندارد؛ همین‌جا می‌بندیم.")
        return

    for name in os.environ.get("TARGETS", "wwe,natgeo").split(","):
        username = name.strip()
        if not username:
            continue
        info = get(f"usernameinfo {username}", f"{API}/users/usernameinfo/", {"username": username})
        try:
            pk = info.json()["user"]["pk"]
        except Exception:
            continue
        get(f"timeline {username}", f"{API}/feed/user/{pk}/", {"count": 12, "max_id": ""})
        get(f"reels {username}", f"{API}/feed/reels_media/", {"reel_pk_ids": pk})
        clips = get(f"clips {username}", f"{API}/feed/user/{pk}/reel_media/")
        try:
            item = clips.json()["items"][0]
            candidate = item["image_versions2"]["candidates"][0]["url"]
            get("cdn media", candidate)
        except Exception:
            pass


if __name__ == "__main__":
    main()
