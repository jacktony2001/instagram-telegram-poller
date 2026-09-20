"""Build IG_SESSION_B64 from cookies copied out of an already-logged-in browser.

No Instagram login happens here, so there is no checkpoint to pass. Write the
cookies into cookies.txt (git-ignored) as `name=value` lines, then run:

    .venv/Scripts/python session_from_cookies.py your_instagram_username

Minimum cookie names: sessionid, ds_user_id, csrftoken.

WARNING: cookies.txt and instagram.session are live logins for your account. Keep them
out of git and delete them when you are done; anyone who reads them can act as you.
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
    sys.exit("Give the username as an argument: python session_from_cookies.py username")
username = sys.argv[1]

cookie_path = Path(sys.argv[2] if len(sys.argv) > 2 else "cookies.txt")
if not cookie_path.exists():
    sys.exit(f"{cookie_path} was not found. Put the cookie values in it first.")

cookies = {}
for line in cookie_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        name, _, value = line.partition("=")
        cookies[name.strip()] = value.strip()

missing = REQUIRED - cookies.keys()
if missing:
    sys.exit(f"These cookies are missing from {cookie_path}: {', '.join(sorted(missing))}")

loader = Instaloader()
loader.context.load_session(username, cookies)

logged_in_as = loader.test_login()
if not logged_in_as:
    sys.exit("Instagram did not accept these cookies as a live session. Did you copy them from a logged-in tab?")
print(f"Live session for: {logged_in_as}")

session_file = Path("instagram.session")
with open(session_file, "wb") as fh:
    pickle.dump(cookies, fh)

print(f"\nSession file written: {session_file.resolve()}\n")
print("Put this value in the IG_SESSION_B64 secret. It is a login — treat it like a password:\n")
print(base64.b64encode(session_file.read_bytes()).decode())
