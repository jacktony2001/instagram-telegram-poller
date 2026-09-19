"""Make the Instagram session once, locally, then paste it into the IG_SESSION_B64 secret."""

import base64
import sys
from pathlib import Path

from instaloader import Instaloader

username = sys.argv[1]
loader = Instaloader(quiet=True)
loader.interactive_login(username)

session_file = Path("instagram.session")
loader.save_session_to_file(str(session_file))
encoded = base64.b64encode(session_file.read_bytes()).decode()

print("\nاین مقدار را در secret به نام IG_SESSION_B64 بگذارید:\n")
print(encoded)
