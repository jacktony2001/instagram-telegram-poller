"""Build an Instagram session once, locally, and print it for the IG_SESSION_B64 secret.

    .venv/Scripts/python make_session.py your_ig_username      # windows
    python3 make_session.py your_ig_username                    # linux and mac

The password is asked with a hidden prompt. Setting IG_PASSWORD or IG_2FA_CODE in
the environment skips those prompts for non-interactive shells.

WARNING: logging in with a password from a datacenter or unfamiliar IP is what gets an
account checkpointed in the first place. Prefer session_from_cookies.py. Never commit
instagram.session, and delete it once the secret is set.
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
    sys.exit("Give the Instagram username as an argument: python make_session.py username")

username = sys.argv[1]
password = os.environ.get("IG_PASSWORD") or getpass.getpass(f"Password for {username}: ")

loader = Instaloader()
try:
    loader.login(username, password)
except TwoFactorAuthRequiredException:
    code = os.environ.get("IG_2FA_CODE") or input("Six-digit two-factor code: ")
    loader.two_factor_login(code.strip())

session_file = Path("instagram.session")
loader.save_session_to_file(str(session_file))

print(f"\nLogged in. Session file written: {session_file.resolve()}\n")
print("Put this value in the IG_SESSION_B64 secret. It is a login — treat it like a password:\n")
print(base64.b64encode(session_file.read_bytes()).decode())
