"""Build an Instagram session once, locally, and print it for the IG_SESSION_B64 secret.

Run from a terminal that has the project's virtualenv active, then:
    set IG_PASSWORD        (just the name, no value — cmd prompts you to type it invisibly)
    python make_session.py your_ig_username
"""

import base64
import getpass
import os
import sys
from pathlib import Path

from instaloader import Instaloader

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if len(sys.argv) < 2:
    sys.exit("اسکرین‌نام اینستاگرام را به‌عنوان آرگومان بده: python make_session.py username")

username = sys.argv[1]
password = os.environ.get("IG_PASSWORD") or getpass.getpass(f"رمز {username}: ")

loader = Instaloader()
loader.login(username, password)
if os.environ.get("IG_2FA_CODE"):
    loader.two_factor_login(os.environ["IG_2FA_CODE"])

session_file = Path("instagram.session")
loader.save_session_to_file(str(session_file))

print(f"\nورود موفق. فایل نشست ساخته شد: {session_file.resolve()}\n")
print("این مقدار را در secret به نام IG_SESSION_B64 بگذارید:\n")
print(base64.b64encode(session_file.read_bytes()).decode())
