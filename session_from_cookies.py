"""Build IG_SESSION_B64 from cookies copied out of an already-logged-in browser.

No Instagram login happens here, so there is no checkpoint to pass. Write the
cookies into cookies.txt (git-ignored) as `name=value` lines, then run:

    .venv/Scripts/python session_from_cookies.py your_instagram_username

Minimum cookie names: sessionid, ds_user_id, csrftoken.
"""

import base64
import pickle
import sys
from pathlib import Path

from instaloader import Instaloader

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REQUIRED = {"sessionid", "csrftoken"}

if len(sys.argv) < 2:
    sys.exit("اسکرین‌نام را به‌عنوان آرگومان بده: python session_from_cookies.py username")
username = sys.argv[1]

cookie_path = Path(sys.argv[2] if len(sys.argv) > 2 else "cookies.txt")
if not cookie_path.exists():
    sys.exit(f"فایل {cookie_path} پیدا نشد. مقادیر کوکی را در آن بگذار.")

cookies = {}
for line in cookie_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        name, _, value = line.partition("=")
        cookies[name.strip()] = value.strip()

missing = REQUIRED - cookies.keys()
if missing:
    sys.exit(f"این کوکی‌ها در {cookie_path} نیستند: {', '.join(sorted(missing))}")

loader = Instaloader()
loader.context.load_session(username, cookies)

logged_in_as = loader.test_login()
if not logged_in_as:
    sys.exit("اینستاگرام این کوکی‌ها را به‌عنوان یک نشست فعال نشناخت. از تبِ لاگین‌شده کپی می‌کنی؟")
print(f"نشست فعال برای: {logged_in_as}")

session_file = Path("instagram.session")
with open(session_file, "wb") as fh:
    pickle.dump(cookies, fh)

print(f"\nفایل نشست ساخته شد: {session_file.resolve()}\n")
print("این مقدار را در secret به نام IG_SESSION_B64 بگذارید:\n")
print(base64.b64encode(session_file.read_bytes()).decode())
