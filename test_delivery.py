"""One-off check of the delivery path: real Telegram uploads, Instagram's CDN replaced by local files.

Run it with the test-delivery workflow. Nothing here is permanent: delete this file and
that workflow once the album path is proven.
"""

import io
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

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

    def __init__(self, payloads):
        self.payloads = payloads

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


def main():
    telegram = bot.Telegram(os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"])
    payloads = {f"fake://slide_{n}.jpg": jpeg(str(n)) for n in range(12)}
    video = mp4()
    if video:
        payloads["fake://clip_0.mp4"] = video
    payloads["fake://broken.jpg"] = b"not an image"
    bot.requests = FakeCdn(payloads)

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

    print("\n--- ۴) وضعیت نشست اینستاگرام (یک درخواست، فقط برای اطلاع) ---")
    try:
        api = bot.IGApi(bot.load_session_cookies())
        items = list(api.feed(max_pages=1))
        owners = sorted({(i.get("user") or {}).get("username") for i in items})
        print(f"فید زنده است: {len(items)} آیتم · کاربران: {', '.join(filter(None, owners))}")
    except Exception as exc:
        print(f"فید بسته است: {type(exc).__name__}: {exc}")

    print("\nپیام‌ها باید در تلگرام دیده شوند؛ اگر آن‌جا نیستند، لاگ بالا خطای تلگرام را چاپ کرده.")


if __name__ == "__main__":
    main()
