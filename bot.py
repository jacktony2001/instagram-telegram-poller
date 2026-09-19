"""Poll Instagram accounts for new posts and stories, forward them to Telegram."""

import base64
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import requests
import yaml
from instaloader import Instaloader, Profile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def read_cap():
    raw = os.environ.get("MAX_NEW_PER_RUN", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else 10


MAX_NEW_PER_RUN = read_cap()
STATE_KEEP_POSTS = 400
STATE_KEEP_STORIES = 600
TELEGRAM_PHOTO_LIMIT = 10 * 1024 * 1024
TELEGRAM_VIDEO_LIMIT = 50 * 1024 * 1024
MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".mp4"}


def load_config(path):
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    accounts = [str(a).strip().lstrip("@") for a in data.get("accounts", [])]
    if not accounts:
        sys.exit("config.yaml: هیچ اکانتی در لیست accounts تعریف نشده است.")
    return accounts


def load_state(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_state(path, state):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def build_loader():
    loader = Instaloader(
        download_pictures=True,
        download_videos=True,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        post_metadata_txt_pattern="",
        storyitem_metadata_txt_pattern="",
        dirname_pattern="{target}",
        filename_pattern="{date:%Y%m%d}_{shortcode}{_num}.{ext}",
        request_timeout=60.0,
        quiet=True,
    )

    session_b64 = os.environ.get("IG_SESSION_B64", "").strip()
    if session_b64:
        username = os.environ.get("IG_USER") or sys.exit("با IG_SESSION_B64، متغیر IG_USER هم لازم است.")
        session_file = tempfile.NamedTemporaryFile(delete=False, suffix=".session").name
        try:
            with open(session_file, "wb") as fh:
                fh.write(base64.b64decode(session_b64))
            loader.load_session_from_file(username, session_file)
        finally:
            os.unlink(session_file)
    elif os.environ.get("IG_USER") and os.environ.get("IG_PASSWORD"):
        loader.login(os.environ["IG_USER"], os.environ["IG_PASSWORD"])
        loader.save_session_to_file("instagram.session")
        print("یک نشست تازه ساخته شد؛ محتوای instagram.session را در IG_SESSION_B64 بگذارید.")
    else:
        sys.exit("متغیر IG_SESSION_B64 یا جفت IG_USER/IG_PASSWORD لازم است.")
    return loader


class Telegram:
    def __init__(self, token, chat_id):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id

    def _post(self, method, payload, files=None):
        resp = requests.post(f"{self.base}/{method}", data=payload, files=files, timeout=120)
        if resp.status_code == 429:
            retry = resp.json().get("parameters", {}).get("retry_after", 5)
            time.sleep(retry)
            resp = requests.post(f"{self.base}/{method}", data=payload, files=files, timeout=120)
        if not resp.ok:
            print(f"تلگرام {method} خطا: {resp.text[:300]}")
        return resp.json().get("ok")

    def send_media(self, path, caption):
        suffix = path.suffix.lower()
        size = path.stat().st_size
        if suffix in {".jpg", ".jpeg", ".png"}:
            method = "sendPhoto" if size <= TELEGRAM_PHOTO_LIMIT else "sendDocument"
        else:
            method = "sendVideo" if size <= TELEGRAM_VIDEO_LIMIT else "sendDocument"
        with open(path, "rb") as fh:
            return self._post(
                method,
                {"chat_id": self.chat_id, "caption": caption[:1024]},
                {method.removeprefix("send").lower() or "photo": fh},
            )

    def notify(self, text):
        return self._post("sendMessage", {"chat_id": self.chat_id, "text": text[:4096]})


def caption_for(post):
    lines = [f"{post.owner_profile.username} · {post.date_utc:%Y-%m-%d %H:%M}"]
    if post.caption:
        lines.append(post.caption.strip())
    lines.append(post.url)
    return "\n".join(lines)


def collect_files(directory):
    return sorted(p for p in Path(directory).rglob("*") if p.suffix.lower() in MEDIA_SUFFIXES)


def fetch_new_posts(loader, profile, seen_posts, telegram, draining=False):
    """Return (delivered, still_draining).

    Posts arrive newest-first, so a seen shortcode normally ends the scan. After a
    run that hit MAX_NEW_PER_RUN the older leftovers must still be drained.
    """
    delivered = 0
    for post in profile.get_posts():
        if post.shortcode in seen_posts:
            if not draining:
                break
            continue
        if delivered >= MAX_NEW_PER_RUN:
            return delivered, True
        seen_posts.add(post.shortcode)
        tmp = tempfile.mkdtemp()
        try:
            if loader.download_post(post, target=tmp):
                files = collect_files(tmp)
                text = caption_for(post)
                for index, path in enumerate(files):
                    telegram.send_media(path, text if index == 0 else f"{post.owner_profile.username} · اسلاید {index + 1}")
                delivered += 1
            else:
                print(f"دانلود پست {post.shortcode} ناموفق بود")
        except Exception as exc:
            print(f"پست {post.shortcode} خطا: {exc}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return delivered, False


def fetch_new_stories(loader, profile, seen_stories, telegram):
    delivered = 0
    story = next(iter(loader.get_stories([profile.userid])), None)
    if story is None:
        return 0
    for item in story.get_items():
        if item.mediaid in seen_stories:
            continue
        if delivered >= MAX_NEW_PER_RUN:
            print(f"استوری‌های بیشترِ {profile.username} به اجرای بعدی می‌ماند.")
            break
        seen_stories.add(item.mediaid)
        tmp = tempfile.mkdtemp()
        try:
            loader.download_storyitem(item, target=tmp)
            for index, path in enumerate(collect_files(tmp)):
                text = f"{profile.username} · استوری · {item.date_local:%H:%M}"
                telegram.send_media(path, text if index == 0 else f"{profile.username} · استوری {index + 1}")
                delivered += 1
        except Exception as exc:
            print(f"استوری {item.mediaid} خطا: {exc}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return delivered


class Seen:
    """Insertion-ordered id history: a set for lookups, a list so trimming keeps the newest."""

    def __init__(self, ids, keep):
        self.order = list(ids)
        self.known = set(self.order)
        self.keep = keep

    def __contains__(self, key):
        return key in self.known

    def add(self, key):
        if key not in self.known:
            self.known.add(key)
            self.order.append(key)
            del self.order[: max(0, len(self.order) - self.keep)]

    def as_list(self):
        return self.order


def main():
    missing = [k for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not os.environ.get(k)]
    if missing:
        sys.exit(f"متغیرهای زیر تنظیم نشده‌اند: {', '.join(missing)}")
    accounts = load_config(os.environ.get("CONFIG", "config.yaml"))
    state = load_state("state.json")
    telegram = Telegram(os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"])
    loader = build_loader()

    totals = {"posts": 0, "stories": 0}
    for username in accounts:
        account = state.setdefault(username, {"posts": [], "stories": []})
        seen_posts = Seen(account["posts"], STATE_KEEP_POSTS)
        seen_stories = Seen(account["stories"], STATE_KEEP_STORIES)
        try:
            profile = Profile.from_username(loader.context, username)
            delivered, account["draining"] = fetch_new_posts(
                loader, profile, seen_posts, telegram, account.get("draining", False)
            )
            totals["posts"] += delivered
            totals["stories"] += fetch_new_stories(loader, profile, seen_stories, telegram)
        except Exception as exc:
            print(f"اکانت {username} خطا: {exc}")
            continue
        account["posts"], account["stories"] = seen_posts.as_list(), seen_stories.as_list()

    save_state("state.json", state)
    print(f"جدید: {totals['posts']} پست، {totals['stories']} استوری")
    if totals["posts"] or totals["stories"]:
        telegram.notify(f"✅ {totals['posts']} پست و {totals['stories']} استوری تازه ارسال شد.")


if __name__ == "__main__":
    main()
