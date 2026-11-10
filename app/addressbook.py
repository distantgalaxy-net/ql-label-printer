# ------------------------------------------------------------------
# labelprinter - saved addresses, encrypted on disk
# Date: 2026-11-10 11:40 GMT (updated; first written 2026-11-10 10:00 GMT)
# Developer: Ash @ Distant Galaxy (@distantgalaxy-net)
#
# Address labels can be saved under the person's name so they can be
# reprinted later without finding the contact again.
#
# How they're stored:
#   data/addresses.enc  every saved address, as one encrypted block
#                       (Fernet: AES-128-CBC + HMAC-SHA256, from the
#                       `cryptography` library). Unreadable without the key.
#   data/addresses.key  the key, created on first save. Both files are
#                       written with mode 600 (only the app's user can
#                       read them) and are git- and Docker-ignored.
# Encryption rather than hashing: a hash can't be turned back into the
# address, so nothing could be reprinted. Keep addresses.key out of
# off-site backups if you want copies of addresses.enc to stay unreadable.
#
# Saved addresses are never part of settings.json or GET /api/settings:
# the page only gets the list of names, and one full entry when picked.
# ------------------------------------------------------------------
import json
import os
import secrets
import threading

from cryptography.fernet import Fernet, InvalidToken

# Fields kept for each saved address (all text), and their length limits
FIELDS = {"name": 200, "address": 1000, "icon": 30, "note": 500, "note_align": 10}
MAX_ENTRIES = 1000


class AddressBookError(Exception):
    """The saved addresses couldn't be read (e.g. the key file was replaced)."""


class AddressBook:
    """Saved address labels, encrypted in DATA_DIR."""

    def __init__(self, data_dir):
        """Remember where the encrypted file and its key live."""
        self.file = os.path.join(data_dir, "addresses.enc")
        self.key_file = os.path.join(data_dir, "addresses.key")
        self._lock = threading.Lock()

    # ------------------------------------------------------------ files
    def _write_private(self, path, data: bytes):
        """Write a file only the app's user can read (mode 600), atomically."""
        tmp = path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)

    def _fernet(self, create=False):
        """The cipher, using the key file (created on first save)."""
        if not os.path.exists(self.key_file):
            if not create:
                return None
            self._write_private(self.key_file, Fernet.generate_key())
        with open(self.key_file, "rb") as fh:
            return Fernet(fh.read().strip())

    def _load(self):
        """All entries, decrypted: [{id, name, address, icon, note, note_align}]."""
        if not os.path.exists(self.file):
            return []
        cipher = self._fernet()
        if cipher is None:
            raise AddressBookError("The saved addresses' key file (addresses.key) is missing.")
        try:
            with open(self.file, "rb") as fh:
                entries = json.loads(cipher.decrypt(fh.read()))
        except (InvalidToken, ValueError) as exc:
            raise AddressBookError("The saved addresses can't be read with the current key file.") from exc
        return entries if isinstance(entries, list) else []

    def _store(self, entries):
        """Encrypt and save all entries."""
        cipher = self._fernet(create=True)
        self._write_private(self.file, cipher.encrypt(json.dumps(entries, ensure_ascii=False).encode()))

    # ------------------------------------------------------------ use
    def names(self):
        """[{id, name}] sorted by name: what the page's list shows."""
        with self._lock:
            entries = self._load()
        return sorted(({"id": e["id"], "name": e["name"]} for e in entries), key=lambda e: e["name"].lower())

    def get(self, entry_id):
        """One saved address by id, or None."""
        with self._lock:
            return next((e for e in self._load() if e["id"] == entry_id), None)

    def save(self, data):
        """Save an address label under its name. A name already saved
        (ignoring capitals) is updated. Returns (entry, updated, error)."""
        entry = {k: str(data.get(k) or "").strip()[:limit] for k, limit in FIELDS.items()}
        if not entry["name"]:
            return None, False, "Type the name first: the label is saved under it."
        if entry["note_align"] not in ("left", "center"):
            entry["note_align"] = "left"
        with self._lock:
            entries = self._load()
            match = next((e for e in entries if e["name"].lower() == entry["name"].lower()), None)
            if match:
                match.update(entry)
                entry = match
            else:
                if len(entries) >= MAX_ENTRIES:
                    return None, False, f"You can save up to {MAX_ENTRIES} address labels."
                entry = {"id": secrets.token_hex(8), **entry}
                entries.append(entry)
            self._store(entries)
        return entry, bool(match), None

    def delete(self, entry_id):
        """Delete a saved address. Returns its name, or None if it wasn't there."""
        with self._lock:
            entries = self._load()
            match = next((e for e in entries if e["id"] == entry_id), None)
            if not match:
                return None
            self._store([e for e in entries if e["id"] != entry_id])
        return match["name"]
