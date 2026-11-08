# ------------------------------------------------------------------
# labelprinter - optional password for the web page and API
# Date: 2026-11-08 16:01 GMT
# Developer: Ash @ Distant Galaxy (@distantgalaxy-net)
#
# The password is OFF by default (blank) - fine when the page is only
# reachable from a trusted home network. It can be set, changed or
# removed in the Settings tab.
#
# How it's stored:
#   /data/auth.json    {"password_hash": "scrypt:..."} - a one-way hash
#                      (Werkzeug/scrypt), so the password can't be read back
#                      from the file. Kept apart from settings.json so the
#                      settings API can never return or overwrite it.
#   /data/secret.key   random key that signs the login cookie; created on
#                      first run. Deleting it logs every browser out.
#
# Logging in:
#   - Browsers: the /login page sets a signed session cookie (30 days).
#   - Scripts / Home Assistant: HTTP Basic auth with any username and the
#     password, e.g. rest_command's `username:`/`password:` options.
#
# Forgotten password: set RESET_PASSWORD: "true" in docker-compose.yml,
# restart once (the password is removed), then take the line out again.
# ------------------------------------------------------------------
import json
import os
import secrets
import time
from datetime import timedelta

from werkzeug.security import check_password_hash, generate_password_hash

MIN_LENGTH = 8                    # shortest password we accept
SESSION_DAYS = 30                 # how long a phone stays logged in
FAILED_LOGIN_DELAY = 1.0          # seconds; slows down password guessing


class Auth:
    """Password storage and checks for one data folder."""

    def __init__(self, data_dir):
        """Remember where auth.json and secret.key live (nothing is read yet)."""
        self.file = os.path.join(data_dir, "auth.json")
        self.key_file = os.path.join(data_dir, "secret.key")

    # ------------------------------------------------------------ storage
    def _hash(self):
        """The stored password hash, or "" when no password is set."""
        try:
            with open(self.file, encoding="utf-8") as fh:
                return json.load(fh).get("password_hash", "")
        except (FileNotFoundError, json.JSONDecodeError):
            return ""

    def _write(self, data):
        """Write auth.json atomically, readable only by the container user."""
        tmp = self.file + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, self.file)

    def secret_key(self):
        """Return the cookie-signing key, creating a random one on first use."""
        try:
            with open(self.key_file, "rb") as fh:
                key = fh.read()
            if len(key) >= 32:
                return key
        except FileNotFoundError:
            pass
        key = secrets.token_bytes(32)
        fd = os.open(self.key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(key)
        return key

    # ------------------------------------------------------------ queries
    def enabled(self):
        """True when a password has been set."""
        return bool(self._hash())

    def version(self):
        """Short tag that changes whenever the password changes.

        Stored in each login session, so changing or removing the password
        logs out every other browser.
        """
        return self._hash()[-16:]

    def check(self, password):
        """True if `password` matches. Failed attempts are slowed down."""
        stored = self._hash()
        ok = bool(stored) and check_password_hash(stored, password or "")
        if not ok:
            time.sleep(FAILED_LOGIN_DELAY)
        return ok

    # ------------------------------------------------------------ changes
    def set_password(self, new_password):
        """Hash and save a new password. Returns an error message or None."""
        if len(new_password or "") < MIN_LENGTH:
            return f"Use at least {MIN_LENGTH} characters."
        self._write({"password_hash": generate_password_hash(new_password)})
        return None

    def remove(self):
        """Turn the password off (delete auth.json)."""
        try:
            os.remove(self.file)
        except FileNotFoundError:
            pass

    def reset_from_env(self):
        """If RESET_PASSWORD is true in the environment, remove the password.

        Used to recover from a forgotten password. Returns True if it did.
        """
        if os.environ.get("RESET_PASSWORD", "").strip().lower() in ("1", "true", "yes"):
            self.remove()
            return True
        return False


def session_lifetime():
    """How long a browser login lasts (used for Flask's permanent sessions)."""
    return timedelta(days=SESSION_DAYS)
