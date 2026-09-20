"""One-off check of the delivery path: real Telegram uploads, Instagram's CDN replaced by local files.

Run it with the test-delivery workflow. Nothing here is permanent: delete this file and
that workflow once the album path is proven.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

import bot

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

bot.TELEGRAM_PAUSE = 0.3


def jpeg(label):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (900, 600), (24, 48 + hash(label) % 180, 120))
    draw = ImageDraw.Draw(img)
    draw.text((60, 280), f"slide {label}", fill="white")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def mp4():
    try:
        import imageio_ffmpeg

        out = Path(tempfile.mkdtemp()) / "clip.mp4"
        subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc=size=480x360:rate=10", "-t", "1", "-pix_fmt", "yuv420p", str(out)],
            check=True,
        )
        return out.read_bytes()
    except Exception as exc:
        print(f"ویدیو ساخته نشد، تست فقط با عکس: {exc}")
        return None


class FakeCdn:
    """Stands in for the Instagram CDN so the test never touches Instagram."""

    def __init__(self, payloads, real):
        self.payloads = payloads
        self.Session = real.Session  # IGApi below still needs a real session

    def get(self, url, timeout=None):
        class Resp:
            status_code = 200
            content = self.payloads[url]

            def raise_for_status(self):
                pass

        return Resp()


def carousel(slides, video_at=None, video=None):
    media = []
    for n in range(slides):
        if n == video_at and video:
            media.append({"video_versions": [{"url": f"fake://clip_{n}.mp4"}]})
        else:
            media.append({"image_versions2": {"candidates": [{"url": f"fake://slide_{n}.jpg"}]}})
    return {
        "code": "TESTALBUM",
        "pk": 1,
        "taken_at": int(time.time()),
        "user": {"username": "testpage"},
        "caption": {"text": "تست آلبوم 😈💋 " + ("متن بلند " * 300)},
        "carousel_media": media,
    }


class StubResponse:
    def __init__(self, code, body="", headers=None):
        self.status_code = code
        self.text = body
        self.headers = headers or {}

    def json(self):
        return json.loads(self.text)


class StubSession:
    """Feeds IGApi canned answers so the retry logic can be watched without calling Instagram."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.cookies = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        item = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


def check_api_client():
    api = bot.IGApi({"sessionid": "x", "ds_user_id": "1234567890"})
    print("app-id:", api.session.headers["X-IG-App-ID"], "· WWW-Claim:",
          "X-IG-WWW-Claim" in api.session.headers, "· rank_token:", api.rank_token)
    print("UA:", api.session.headers["User-Agent"][:40], "…")

    ok = StubResponse(200, json.dumps({"feed_items": [{"media_or_ad": {"code": "A", "taken_at": 1}}],
                                       "next_max_id": "c2", "more_available": True}))
    api.session = StubSession([StubResponse(429, "throttled", {"Retry-After": "1"}), ok])
    bot.set_run_deadline()
    bot.set_route_deadline()
    waits = []
    real_sleep = time.sleep
    time.sleep = lambda seconds: waits.append(seconds)
    try:
        items = list(api.feed(max_pages=1))
        print(f"۴۲۹ → تلاش دوباره: آیتم‌ها {items} · صبرها {waits}")

        api.session = StubSession([StubResponse(400, '{"message":"checkpoint_required","lock":true}')])
        try:
            list(api.feed(max_pages=1))
            print("چالش: خطا نداد — این غلط است")
        except bot.SessionDead as exc:
            print("چالش درست به SessionDead می‌رسد:", str(exc)[:110])

        api.session = StubSession([requests.exceptions.Timeout()])
        try:
            list(api.feed(max_pages=1))
            print("قطع اتصال: خطا نداد — این غلط است")
        except bot.RateLimited as exc:
            print(f"قطع اتصال بعد از {len(api.session.calls)} تلاش می‌گوید: {exc}")
    finally:
        time.sleep = real_sleep


class Recorder:
    """Counts what Telegram would have received, in order, without uploading 100 files."""

    def __init__(self):
        self.sent = []

    def send_album(self, paths, caption=None):
        self.sent.append((len(paths), caption))
        return True

    def send_media(self, path, caption=None):
        self.sent.append((1, caption))
        return True


class BusyApi:
    """One heavy page: fresh posts, month-old posts mixed into the ranked feed, and 30 stories."""

    def __init__(self, now):
        self.page = {"username": "busypage", "pk": 777}
        fresh = [self.post(f"F{n}", now - n * 600) for n in range(14)]
        old = [self.post(f"O{n}", now - (30 + n) * 86400) for n in range(12)]
        self.items = fresh + old
        self.stories = [
            {"code": f"S{n}", "pk": 9000 + n, "taken_at": now - n * 900, "user": self.page,
             "image_versions2": {"candidates": [{"url": "fake://slide_0.jpg"}]}}
            for n in range(30)
        ]

    def post(self, tag, taken_at):
        return {"code": tag, "pk": hash(tag), "taken_at": taken_at, "user": self.page,
                "caption": {"text": f"پست {tag}"},
                "image_versions2": {"candidates": [{"url": "fake://slide_0.jpg"}]}}

    def feed(self):
        yield from self.items

    def reel(self, pk):
        return {"items": self.stories}


def check_busy_page(payloads):
    now = int(time.time())
    api = BusyApi(now)
    telegram = Recorder()
    real_requests = bot.requests
    bot.requests = FakeCdn(payloads, requests)
    bot.set_run_deadline()
    bot.set_route_deadline()
    try:
        count = bot.run_api(api, telegram, bot.Tracker({}), ["busypage"],
                            fresh_hours=24, story_hours=4, story_cap=6)
    finally:
        bot.requests = real_requests
    posts = [c for _, c in telegram.sent if "/p/" in c]
    stories = [c for _, c in telegram.sent if "/p/" not in c]
    print(f"ارسال شد: {count} آیتم · پیام‌ها: {len(telegram.sent)} (پست {len(posts)} + استوری {len(stories)})")
    print(f"سقف پست {bot.MAX_NEW_PER_RUN}: {len(posts) <= bot.MAX_NEW_PER_RUN} · سقف استوری ۶: {len(stories) <= 6} · "
          f"پست‌های ۳۰ روزه رد شدند: {not any('پست O' in c for c in posts)}")
    print("ترتیب زمانی پست‌ها (باید قدیمی به تازه):")
    stamps = [caption.split("\n")[0] for caption in posts]
    for stamp in stamps:
        print("   ", stamp)
    print("ترتیب درست است:", stamps == sorted(stamps))


def main():
    telegram = bot.Telegram(os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"])
    payloads = {f"fake://slide_{n}.jpg": jpeg(str(n)) for n in range(12)}
    video = mp4()
    if video:
        payloads["fake://clip_0.mp4"] = video
    payloads["fake://broken.jpg"] = b"not an image"
    bot.requests = FakeCdn(payloads, requests)

    print("\n--- ۱) کاروسل ۱۲ اسلایده: باید دو آلبوم بشود (۱۰ + ۲) ---")
    seen = set()
    item = carousel(12, video_at=0 if video else None, video=video)
    print("نتیجه:", bot.deliver_api_item(telegram, item, seen), "· seen:", seen)

    print("\n--- ۲) پست تک‌عکسی: باید یک پیام باشد ---")
    single = {"code": "TESTSINGLE", "pk": 2, "taken_at": int(time.time()), "user": {"username": "testpage"},
              "caption": {"text": "تست تک‌عکسی 🥳"}, "image_versions2": {"candidates": [{"url": "fake://slide_0.jpg"}]}}
    seen = set()
    print("نتیجه:", bot.deliver_api_item(telegram, single, seen), "· seen:", seen)

    print("\n--- ۳) اسلاید خراب: باید False بدهد و در seen نرود ---")
    broken = carousel(2)
    broken["carousel_media"] = [{"image_versions2": {"candidates": [{"url": "fake://missing.jpg"}]}}] * 2
    seen = set()
    print("نتیجه:", bot.deliver_api_item(telegram, broken, seen), "· seen:", seen)

    print("\n--- ۴) پیج شلوغ: ۱۴ پست تازه + ۱۲ پست ۳۰ روزه + ۳۰ استوری ---")
    check_busy_page(payloads)

    print("\n--- ۵) هدرها و تلاش دوباره، بدون تماس با اینستاگرام ---")
    bot.requests = requests  # from here on nothing is faked; the checks below never send
    check_api_client()

    print("\nپیام‌ها باید در تلگرام دیده شوند؛ اگر آن‌جا نیستند، لاگ بالا خطای تلگرام را چاپ کرده.")


if __name__ == "__main__":
    main()
