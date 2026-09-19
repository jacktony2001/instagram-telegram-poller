"""Build an Instagram session once, locally, and print it for the IG_SESSION_B64 secret.

    .venv/Scripts/python make_session.py your_ig_username      # windows
    python3 make_session.py your_ig_username                    # linux and mac

The password is asked with a hidden prompt. Setting IG_PASSWORD or IG_2FA_CODE in
the environment skips those prompts for non-interactive shells.
"""

import base64
import getpass
import os
import sys
from pathlib import Path

from instaloader import Instaloader
from instaloader.exceptions import TwoFactorAuthRequiredException

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if len(sys.argv) < 2:
    sys.exit("اسکرین‌نام اینستاگرام را به‌عنوان آرگومان بده: python make_session.py username")

username = sys.argv[1]
password = os.environ.get("IG_PASSWORD") or getpass.getpass(f"رمز {username}: ")

loader = Instaloader()
try:
    loader.login(username, password)
except TwoFactorAuthRequiredException:
    code = os.environ.get("IG_2FA_CODE") or input("کد شش‌رقمی تایید دومرحله‌ای: ")
    loader.two_factor_login(code.strip())

session_file = Path("instagram.session")
loader.save_session_to_file(str(session_file))

print(f"\nورود موفق. فایل نشست ساخته شد: {session_file.resolve()}\n")
print("این مقدار را در secret به نام IG_SESSION_B64 بگذارید:\n")
print(base64.b64encode(session_file.read_bytes()).decode())
