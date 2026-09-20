"""Poll Instagram accounts for new posts and stories, forward them to Telegram."""

import base64
import json
import os
import pickle
import random
import shutil
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

import requests
import yaml
from instaloader import Instaloader, Profile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


STATE_KEEP_POSTS = 400
STATE_KEEP_STORIES = 600
TELEGRAM_PHOTO_LIMIT = 10 * 1024 * 1024
TELEGRAM_VIDEO_LIMIT = 50 * 1024 * 1024
TELEGRAM_PAUSE = 1.5
MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".mp4"}
PROXY_LIST_URLS = [
    "https://cdn.jsdelivr.net/gh/proxyscrape/free-proxy-list@main/proxies/protocols/http/data.txt",
    "https://cdn.jsdelivr.net/gh/proxyscrape/free-proxy-list@main/proxies/protocols/https/data.txt",
]


def read_int_env(name, default):
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else default


MAX_NEW_PER_RUN = read_int_env("MAX_NEW_PER_RUN", 10)
PROXY_TRIES = read_int_env("PROXY_TRIES", 8)
RUN_BUDGET = read_int_env("RUN_BUDGET", 600)
ROUTE_BUDGET = read_int_env("ROUTE_BUDGET", 150)

RUN_DEADLINE = float("inf")
ROUTE_DEADLINE = float("inf")


def set_run_deadline():
    global RUN_DEADLINE
    RUN_DEADLINE = time.monotonic() + RUN_BUDGET


def set_route_deadline():
    global ROUTE_DEADLINE
    ROUTE_DEADLINE = min(time.monotonic() + ROUTE_BUDGET, RUN_DEADLINE)


def check_time():
    """Raise out of a scan when the job would otherwise be killed by the runner."""
    if time.monotonic() > ROUTE_DEADLINE:
        raise TooSlow("وقت این روش تمام شد")
    if time.monotonic() > RUN_DEADLINE:
        raise RateLimited("وقت کل job تمام شد")


def direct_session():
    """A session that ignores proxy env vars, for Telegram and GitHub calls."""
    session = requests.Session()
    session.trust_env = False
    return session


class RateLimited(Exception):
    """Instagram throttled this address; another route may still work."""


class TooSlow(RateLimited):
    """This route is too dead to be worth another second."""


class SessionDead(Exception):
    """Instagram wants a human again; no proxy fixes this."""


def classify(exc):
    text = f"{type(exc).__name__}: {exc}".lower()
    if "checkpoint" in text or "feedback required" in text or "login" in text:
        return "dead"
    if "429" in text or "too many requests" in text:
        return "rate"
    return None


def rethrow(exc):
    kind = classify(exc)
    if kind == "dead":
        raise SessionDead(exc) from exc
    if kind == "rate":
        raise RateLimited(exc) from exc


def load_config(path):
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    accounts = [str(a).strip().lstrip("@") for a in data.get("accounts", [])]
    if not accounts:
        sys.exit("config.yaml: هیچ اکانتی در لیست accounts تعریف نشده است.")
    mode = str(data.get("mode", "auto")).strip().lower()
    if mode not in {"auto", "api", "feed", "profile"}:
        sys.exit("config.yaml: مقدار mode باید auto یا api یا feed یا profile باشد.")
    urls = [str(u).strip() for u in data.get("proxy_urls", []) if str(u).strip()]
    return {
        "accounts": accounts,
        "mode": mode,
        "stories": bool(data.get("stories", True)),
        "proxies": bool(data.get("proxies", True)),
        "proxy_urls": urls or PROXY_LIST_URLS,
        "max_post_age_hours": int(data.get("max_post_age_hours", 24) or 24),
        "max_story_age_hours": int(data.get("max_story_age_hours", 4) or 4),
        "max_stories_per_run": int(data.get("max_stories_per_run", 6) or 6),
    }


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
        request_timeout=20.0,
        max_connection_attempts=2,
        fatal_status_codes=[429],
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


def load_session_cookies():
    """The pickled instaloader session is a plain cookie name-to-value dict."""
    blob = os.environ.get("IG_SESSION_B64", "").strip()
    if not blob:
        sys.exit("متغیر IG_SESSION_B64 لازم است.")
    return {k: str(v) for k, v in pickle.loads(base64.b64decode(blob)).items()}


class IGApi:
    """Instagram's private app API. The web API answers 429 to this runner; these endpoints are the
    ones the official app uses, so they are asked with the app's own identity. The identity was
    checked on 2026-09-20: it does not lift a checkpoint, but it is what the API expects."""

    BASE = "https://i.instagram.com/api/v1"
    HEADERS = {
        "X-IG-App-ID": "567067343352427",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "X-IG-Connection-Type": "WIFI",
        "User-Agent": (
            "Instagram 448.0.0.0.20 Android (34/14; 420dpi; 1080x2221; Google; Pixel 8 Pro; "
            "shiba; samsung; en_US)"
        ),
    }

    def __init__(self, cookies):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.session.cookies.update(cookies)
        # The app's rank_token is "<user id>_<uuid>"; the random one the web page uses is a guess.
        user_id = cookies.get("ds_user_id") or ""
        self.rank_token = f"{user_id}_{uuid.uuid4().hex}" if user_id else uuid.uuid4().hex

    def _request(self, path, params=None):
        """One GET, retried for the two things waiting fixes: a throttle and a dropped connection."""
        delay = 20
        for attempt in (1, 2, 3):
            check_time()
            try:
                resp = self.session.get(self.BASE + path, params=params, timeout=30)
            except (requests.ConnectionError, requests.Timeout) as exc:
                problem = f"قطع اتصال ({type(exc).__name__})"
            else:
                if resp.status_code != 429:
                    return resp
                problem = "۴۲۹ اینستاگرام"
                waited = resp.headers.get("Retry-After", "")
                if waited.isdigit():
                    delay = max(delay, min(int(waited), 60))
            if attempt == 3:
                raise RateLimited(f"{path}: {problem} · بعد از سه تلاش")
            print(f"{path}: {problem} — {delay} ثانیه صبر")
            time.sleep(delay)
            delay *= 2

    def _json(self, path, params=None):
        resp = self._request(path, params)
        if resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError:
                raise RateLimited(f"{path}: پاسخ JSON نیست") from None
            if data.get("status") == "fail":
                raise RateLimited(f"{path}: {str(data.get('message'))[:160]}")
            return data
        # Without the body we cannot tell a throttle from a challenge, so quote what Instagram said.
        detail = " ".join(resp.text[:200].split())
        if resp.status_code in (401, 403) or "feedback_required" in detail or "checkpoint" in detail:
            challenged = "checkpoint" in detail or "challenge" in detail
            reason = "چالش انسانی" if challenged else "ورود دوباره"
            raise SessionDead(
                f"{path}: کد {resp.status_code} · {reason} · {detail[:120]}"
                + (" · https://www.instagram.com/challenge/" if challenged else "")
            )
        raise RateLimited(f"{path}: کد {resp.status_code} · {detail}")

    def feed(self, max_pages=3):
        """Yield media items of the logged-in account's own timeline, newest first."""
        cursor = None
        for number in range(max_pages):
            params = {"rank_token": self.rank_token}
            if cursor:
                params["max_id"] = cursor
            else:
                params["media_id"] = ""
            try:
                data = self._json("/feed/timeline/", params)
            except SessionDead:
                raise
            except RateLimited as exc:
                if number == 0:
                    raise
                # A stale cursor must not throw away the pages we already have.
                print(f"صفحه‌ی {number + 1} فید نیامد: {exc}")
                return
            for entry in data.get("feed_items", []):
                if entry.get("media_or_ad"):
                    yield entry["media_or_ad"]
            cursor = data.get("next_max_id")
            if not cursor or not data.get("more_available"):
                return

    def reel(self, pk):
        """Active story reel of one account, or None when it has no stories."""
        try:
            data = self._json("/feed/reels_media/", {"reel_ids": pk})
        except SessionDead:
            raise
        except RateLimited as exc:
            print(f"استوری‌های pk={pk} گرفته نشد: {exc}")
            return None
        return (data.get("reels") or {}).get(str(pk))


def best_candidate(versions):
    candidates = (versions or {}).get("candidates") or []
    return candidates[0]["url"] if candidates else None


def api_media_urls(item):
    """Every slide of an item as a direct CDN url."""
    urls = []
    for slide in item.get("carousel_media") or [item]:
        urls.append((slide.get("video_versions") or [{}])[0].get("url") or best_candidate(slide.get("image_versions2")))
    return [u for u in urls if u]


def api_caption(owner, item, link=True):
    stamp = datetime.fromtimestamp(item.get("taken_at") or 0, timezone.utc).strftime("%Y-%m-%d %H:%M")
    lines = [f"{owner} · {stamp}"]
    text = ((item.get("caption") or {}).get("text") or "").strip()
    if text:
        lines.append(text)
    if link and item.get("code"):
        lines.append(f"https://www.instagram.com/p/{item['code']}/")
    return "\n".join(lines)


def seen_key(item):
    """The id a delivered item is remembered by; posts and stories both carry a code."""
    return str(item.get("code") or item.get("pk"))


def deliver_api_item(telegram, item, seen, owner=None, story=False):
    """Download one private-API item from the CDN and upload it. Returns False if nothing arrived."""
    owner = owner or (item.get("user") or {}).get("username") or "?"
    key = seen_key(item)
    tmp = tempfile.mkdtemp()
    try:
        paths = []
        for index, url in enumerate(api_media_urls(item), start=1):
            suffix = Path(url.split("?")[0]).suffix or ".jpg"
            try:
                resp = requests.get(url, timeout=60)
                resp.raise_for_status()
            except Exception as exc:
                print(f"دریافت {key} اسلاید {index} ناموفق بود: {exc}")
                continue
            path = Path(tmp) / f"{key}_{index}{suffix}"
            path.write_bytes(resp.content)
            paths.append(path)
        if not paths:
            return False
        text = api_caption(owner, item, link=not story)
        print(f"→ {key}: {text[:120]!r}")
        # Telegram caps an album at 10 files, so a longer carousel is split into follow-up albums.
        chunks = [[p] for p in paths] if story else [paths[i : i + 10] for i in range(0, len(paths), 10)]
        sent_ok = True
        for number, chunk in enumerate(chunks, start=1):
            head = text if number == 1 else f"{owner} · ادامه، بخش {number}"
            if len(chunk) > 1:
                result = telegram.send_album(chunk, head)
            else:
                result = telegram.send_media(chunk[0], head)
            sent_ok = sent_ok and bool(result)
        if not sent_ok:
            # Leave it unseen so the next run retries it instead of losing the post.
            return False
        seen.add(key)
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_api(api, telegram, tracker, accounts, fresh_hours=24, story_hours=4, story_cap=6):
    """Follow the accounts through the feed and their story reels, without instaloader."""
    wanted = set(accounts)
    horizon = time.time() - fresh_hours * 3600
    story_horizon = time.time() - story_hours * 3600
    candidates, stale = [], 0
    for item in api.feed():
        check_time()
        user = item.get("user") or {}
        account = user.get("username")
        if account not in wanted:
            continue
        tracker.set_pk(account, user.get("pk"))
        if seen_key(item) in tracker.posts(account):
            continue
        # The home feed is ranked, not chronological, so it hands us month-old posts too.
        if (item.get("taken_at") or 0) < horizon:
            stale += 1
            continue
        candidates.append(item)
    if stale:
        print(f"{stale} آیتم قدیمی‌تر از {fresh_hours} ساعت رد شد.")

    # Take the newest ones, then send them oldest-first so the chat reads in order.
    candidates.sort(key=lambda item: item.get("taken_at") or 0, reverse=True)
    batch = candidates[:MAX_NEW_PER_RUN]
    if len(candidates) > len(batch):
        print(f"{len(candidates) - len(batch)} آیتم برای اجرای بعدی می‌ماند.")
    delivered = 0
    for item in sorted(batch, key=lambda item: item.get("taken_at") or 0):
        account = (item.get("user") or {}).get("username")
        if deliver_api_item(telegram, item, tracker.posts(account)):
            delivered += 1
            tracker.save()

    # A reel holds a whole day of stories, so they get their own, much tighter window:
    # anything older than a few poll intervals is history the user already walked past.
    for account in accounts:
        pk = tracker.pk(account)
        if not pk:
            continue
        reel = api.reel(pk)
        seen_stories = tracker.stories(account)
        # Story items carry no username of their own, so the caption takes it from the loop.
        pending = [
            s
            for s in (reel or {}).get("items") or []
            if seen_key(s) not in seen_stories and (s.get("taken_at") or 0) >= story_horizon
        ]
        pending.sort(key=lambda story: story.get("taken_at") or 0)
        for story in pending[:story_cap]:
            check_time()
            if deliver_api_item(telegram, story, seen_stories, owner=account, story=True):
                delivered += 1
                tracker.save()
    return delivered


class Telegram:
    def __init__(self, token, chat_id):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id
        self.session = direct_session()

    def _post(self, method, payload, files=None):
        url = f"{self.base}/{method}"
        resp = self.session.post(url, data=payload, files=files, timeout=120)
        if resp.status_code == 429:
            time.sleep(resp.json().get("parameters", {}).get("retry_after", 5))
            for fh in (files or {}).values():
                fh.seek(0)  # a retried upload reads from where it stopped, and Telegram gets an empty file
            resp = self.session.post(url, data=payload, files=files, timeout=120)
        if not resp.ok:
            print(f"تلگرام {method} خطا: {resp.text[:300]}")
        if files:
            time.sleep(TELEGRAM_PAUSE)  # a bot may post about one message per second per chat
        return resp.json().get("ok")

    def _kind(self, path):
        suffix = path.suffix.lower()
        size = path.stat().st_size
        if suffix in {".jpg", ".jpeg", ".png"}:
            return "photo" if size <= TELEGRAM_PHOTO_LIMIT else "document"
        return "video" if size <= TELEGRAM_VIDEO_LIMIT else "document"

    def send_media(self, path, caption):
        method = "send" + self._kind(path).capitalize()
        field = method.removeprefix("send").lower() or "photo"
        with open(path, "rb") as fh:
            return self._post(
                method,
                {"chat_id": self.chat_id, "caption": caption[:1024]},
                {field: fh},
            )

    def send_album(self, paths, caption):
        """One Instagram post as one Telegram album; the caption sits on the first slide."""
        media, handles = [], {}
        for index, path in enumerate(paths):
            entry = {"type": self._kind(path), "media": f"attach://file{index}"}
            if index == 0:
                entry["caption"] = caption[:1024]
            media.append(entry)
            handles[f"file{index}"] = open(path, "rb")
        try:
            return self._post("sendMediaGroup", {"chat_id": self.chat_id, "media": json.dumps(media)}, handles)
        finally:
            for fh in handles.values():
                fh.close()

    def notify(self, text):
        return self._post("sendMessage", {"chat_id": self.chat_id, "text": text[:4096]})


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


class Tracker:
    """One Seen list per account, mirrored into the state dict and onto disk."""

    def __init__(self, state):
        self.state = state
        self._posts = {}
        self._stories = {}

    def _entry(self, account):
        return self.state.setdefault(account, {"posts": [], "stories": [], "draining": False, "pk": None})

    def _seen(self, account, bucket, keep, cache):
        if account not in cache:
            cache[account] = Seen(self._entry(account)[bucket], keep)
        return cache[account]

    def posts(self, account):
        return self._seen(account, "posts", STATE_KEEP_POSTS, self._posts)

    def stories(self, account):
        return self._seen(account, "stories", STATE_KEEP_STORIES, self._stories)

    def draining(self, account):
        return bool(self._entry(account).get("draining"))

    def set_draining(self, account, value):
        self._entry(account)["draining"] = bool(value)

    def pk(self, account):
        return self._entry(account).get("pk")

    def set_pk(self, account, pk):
        if pk:
            self._entry(account)["pk"] = int(pk)

    def save(self):
        for account, seen in self._posts.items():
            self._entry(account)["posts"] = seen.as_list()
        for account, seen in self._stories.items():
            self._entry(account)["stories"] = seen.as_list()
        save_state("state.json", self.state)


class ProxyPool:
    """Free proxy lists from ProxyScrape, shuffled so each attempt takes a different route."""

    def __init__(self, urls):
        self.session = direct_session()
        found = []
        seen = set()
        for url in urls:
            try:
                resp = self.session.get(url, timeout=30)
                resp.raise_for_status()
            except Exception as exc:
                print(f"لیست پروکسی گرفته نشد ({url}): {exc}")
                continue
            for line in resp.text.splitlines():
                proxy = line.strip()
                if proxy.count(":") >= 2 and proxy not in seen:
                    seen.add(proxy)
                    found.append(proxy)
        random.shuffle(found)
        self.queue = found[:PROXY_TRIES]
        print(f"{len(self.queue)} پروکسی برای آزمایش آماده است.")

    def routes(self):
        """The direct address first, then every proxy."""
        return [None] + self.queue


def apply_proxy(proxy):
    """instaloader only ever uses requests sessions, which re-read these vars per request."""
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        os.environ.pop(key, None)
    if proxy:
        for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
            os.environ[key] = proxy


def caption_for(post):
    lines = [f"{post.owner_profile.username} · {post.date_utc:%Y-%m-%d %H:%M}"]
    if post.caption:
        lines.append(post.caption.strip())
    lines.append(post.url)
    return "\n".join(lines)


def collect_files(directory):
    return sorted(p for p in Path(directory).rglob("*") if p.suffix.lower() in MEDIA_SUFFIXES)


def deliver_post(loader, post, telegram, seen_posts):
    """Download one post and upload every slide. Returns False when nothing came through."""
    tmp = tempfile.mkdtemp()
    try:
        try:
            downloaded = loader.download_post(post, target=tmp)
        except Exception as exc:
            rethrow(exc)
            print(f"پست {post.shortcode} خطا: {exc}")
            return False
        if not downloaded:
            print(f"دانلود پست {post.shortcode} ناموفق بود")
            return False
        files = collect_files(tmp)
        owner = post.owner_profile.username
        text = caption_for(post)
        for index, path in enumerate(files):
            telegram.send_media(path, text if index == 0 else f"{owner} · اسلاید {index + 1}")
        seen_posts.add(post.shortcode)
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_feed(loader, telegram, tracker, accounts):
    """Take what Instagram already pushes into the logged-in account's own feed.

    This needs no per-profile request at all, so it survives pages being closed off,
    but the reading account must follow every target itself.
    """
    wanted = set(accounts)
    delivered = 0
    for post in loader.get_feed_posts():
        check_time()
        owner = post.owner_profile.username
        if owner not in wanted or post.shortcode in tracker.posts(owner):
            continue
        if delivered >= MAX_NEW_PER_RUN:
            break
        if deliver_post(loader, post, telegram, tracker.posts(owner)):
            delivered += 1
            tracker.save()
    return delivered


def run_profile(loader, telegram, tracker, accounts, want_stories):
    """Walk each account timeline and its stories, oldest-leftover aware."""
    delivered = 0
    scanned = 0
    blocked = None
    for username in accounts:
        check_time()
        try:
            profile = Profile.from_username(loader.context, username)
            delivered += fetch_new_posts(loader, profile, telegram, tracker)
            if want_stories:
                delivered += fetch_new_stories(loader, profile, telegram, tracker)
            scanned += 1
        except RateLimited:
            raise
        except Exception as exc:
            rethrow(exc)
            blocked = exc
            print(f"اکانت {username} خطا: {exc}")
        tracker.save()
    if scanned == 0 and blocked is not None:
        raise RateLimited(blocked)
    return delivered


def fetch_new_posts(loader, profile, telegram, tracker):
    """Return how many posts went out, leaving the draining flag set if leftovers remain."""
    username = profile.username
    seen_posts = tracker.posts(username)
    draining = tracker.draining(username)
    delivered = 0
    for post in profile.get_posts():
        check_time()
        if post.shortcode in seen_posts:
            if not draining:
                break
            continue
        if delivered >= MAX_NEW_PER_RUN:
            tracker.set_draining(username, True)
            return delivered
        if deliver_post(loader, post, telegram, seen_posts):
            delivered += 1
            tracker.save()
    tracker.set_draining(username, False)
    return delivered


def fetch_new_stories(loader, profile, telegram, tracker):
    username = profile.username
    seen_stories = tracker.stories(username)
    delivered = 0
    story = next(iter(loader.get_stories([profile.userid])), None)
    if story is None:
        return 0
    for item in story.get_items():
        check_time()
        if item.mediaid in seen_stories:
            continue
        if delivered >= MAX_NEW_PER_RUN:
            print(f"استوری‌های بیشترِ {username} به اجرای بعدی می‌ماند.")
            break
        tmp = tempfile.mkdtemp()
        try:
            try:
                loader.download_storyitem(item, target=tmp)
            except Exception as exc:
                rethrow(exc)
                print(f"استوری {item.mediaid} خطا: {exc}")
                continue
            for index, path in enumerate(collect_files(tmp)):
                text = f"{username} · استوری · {item.date_local:%H:%M}"
                telegram.send_media(path, text if index == 0 else f"{username} · استوری {index + 1}")
                delivered += 1
            seen_stories.add(item.mediaid)
            tracker.save()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return delivered


def disable_workflow():
    """Turn the scheduler off through the GitHub API, because the runner cannot do it itself."""
    token = os.environ.get("ACTIONS_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    workflow = os.environ.get("WORKFLOW_FILE", "poll.yml").strip()
    if not token or not repo:
        print("برای خاموش کردن workflow متغیرهای ACTIONS_TOKEN و GITHUB_REPOSITORY لازم‌اند.")
        return False
    resp = direct_session().put(
        f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/disable",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )
    print(f"خاموش کردن workflow: کد {resp.status_code}")
    return resp.ok


def try_strategy(strategy, loader, telegram, tracker, accounts, routes):
    """Run a strategy over each route, rotating proxies whenever a route is blocked or dead."""
    blocked = None
    for proxy in routes:
        if time.monotonic() > RUN_DEADLINE:
            raise RateLimited(blocked or "وقت کل job تمام شد")
        apply_proxy(proxy)
        set_route_deadline()
        route = "اتصال مستقیم" if proxy is None else f"پروکسی {proxy}"
        print(f"امتحان با {route} …")
        try:
            count = strategy(loader, telegram, tracker, accounts)
            print(f"{route} جواب داد: {count} آیتم تازه.")
            return count
        except SessionDead:
            raise
        except RateLimited as exc:
            blocked = exc
            print(f"{route} نشد: {exc}")
        except Exception as exc:
            blocked = exc
            print(f"{route} بی‌نتیجه ماند: {exc}")
    raise RateLimited(blocked or "هیچ روشی کار نکرد")


def main():
    missing = [k for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not os.environ.get(k)]
    if missing:
        sys.exit(f"متغیرهای زیر تنظیم نشده‌اند: {', '.join(missing)}")
    set_run_deadline()
    config = load_config(os.environ.get("CONFIG", "config.yaml"))
    state = load_state("state.json")
    tracker = Tracker(state)
    telegram = Telegram(os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"])
    loader = build_loader()

    routes = ProxyPool(config["proxy_urls"]).routes() if config["proxies"] else [None]
    clients = {"api": IGApi(load_session_cookies()), "loader": loader}
    strategies = {
        "api": partial(
            run_api,
            fresh_hours=config["max_post_age_hours"],
            story_hours=config["max_story_age_hours"],
            story_cap=config["max_stories_per_run"],
        ),
        "feed": run_feed,
        "profile": partial(run_profile, want_stories=config["stories"]),
    }
    order = ["api", "profile"] if config["mode"] == "auto" else [config["mode"]]

    delivered = 0
    worked = []
    failures = []
    for name in order:
        if worked:
            break  # the api route already covers posts and stories, so one winner is enough
        try:
            client = clients["api"] if name == "api" else clients["loader"]
            delivered += try_strategy(strategies[name], client, telegram, tracker, config["accounts"], routes)
            worked.append(name)
        except SessionDead as exc:
            print(f"نشست اینستاگرام از کار افتاده: {exc}")
            telegram.notify(
                "⛔ اینستاگرام نشست را به بررسی کشیده؛ پروکسی فایده‌ای ندارد. "
                "یک نشست تازه بساز و IG_SESSION_B64 را عوض کن. ربات خودکار خاموش شد.\n"
                f"دلیل: {exc}"
            )
            disable_workflow()
            tracker.save()
            sys.exit(1)
        except RateLimited as exc:
            print(f"روش {name} به جایی نرسید: {exc}")
            failures.append(f"{name}: {exc}")

    tracker.save()
    if not worked:
        telegram.notify(
            "⛔ هیچ‌کدام از راه‌ها جواب نداد و workflow خودکار خاموش می‌شود تا اکانت زیر فشار نماند. "
            "برای روشن کردن دوباره به Actions برو.\n" + "\n".join(failures)
        )
        disable_workflow()
    else:
        print(f"جدید: {delivered} آیتم فرستاده شد با روش {' + '.join(worked)}")
        if delivered:
            telegram.notify(f"✅ {delivered} آیتم تازه از اینستاگرام ارسال شد.")


if __name__ == "__main__":
    main()
