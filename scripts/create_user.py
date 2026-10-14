"""
Reset a member's password (or create a login) from the command line.

    uv run python scripts/create_user.py john          # prompts for the new password
    uv run python scripts/create_user.py john --admin  # also makes them an admin

Against Railway's database:
    railway run uv run python scripts/create_user.py john
(Admins can also reset any member's password from the Admin page.)
"""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import app.models  # noqa: E402,F401
from app.auth import MIN_PASSWORD, set_password  # noqa: E402
from app.db import init_db  # noqa: E402


def main() -> None:
    init_db()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    username = (args[0] if args else input("Username: ")).strip().lower()
    password = getpass.getpass("Password: ")
    if len(password) < MIN_PASSWORD:
        sys.exit("Type a password.")
    if password != getpass.getpass("Again: "):
        sys.exit("Passwords didn't match.")
    created = set_password(username, password, admin="--admin" in sys.argv)
    print(f"{'Created' if created else 'Updated password for'} {username!r}.")


if __name__ == "__main__":
    main()
