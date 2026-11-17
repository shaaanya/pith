"""Filesystem drop-folder adapter (iCloud-safe).

A file is submitted only when: not hidden / `.icloud` stub / `.part|.tmp|.crdownload`, not a
symlink escaping the folder, within max_fetch_bytes, mtime older than MIN_AGE seconds and size
unchanged across `stable_polls` consecutive polls. It is moved to `<dir>/.processed/` only AFTER
submit() returned; a crash in between leaves the file, and the next poll re-submits it harmlessly
(Inbox dedupes by canonical URL / content sha). `.url`, `.webloc` and `.txt/.md` files whose every
non-empty line is a URL become one URL submission per URL."""
from __future__ import annotations

import logging
import os
import plistlib
import re
import shutil
import time
import uuid
from pathlib import Path

log = logging.getLogger(__name__)
MIN_AGE = 2.0
_SKIP_SUFFIX = (".icloud", ".part", ".tmp", ".crdownload")
_URL = re.compile(r"https?://\S+")


def _link_urls(p: Path) -> list[str] | None:
    """URLs if `p` is a link file, else None (-> submitted as a plain file)."""
    ext = p.suffix.lower()
    try:
        if ext == ".webloc":
            u = plistlib.loads(p.read_bytes()).get("URL")
            return [u] if isinstance(u, str) and _URL.fullmatch(u) else None
        if ext == ".url":
            m = re.search(r"^URL=(\S+)\s*$", p.read_text("utf-8", "replace"), re.M)
            return [m[1]] if m and _URL.fullmatch(m[1]) else None
        if ext in (".txt", ".md") and p.stat().st_size <= 1_000_000:
            lines = [ln.strip() for ln in p.read_text("utf-8").splitlines() if ln.strip()]
            return lines if lines and all(_URL.fullmatch(ln) for ln in lines) else None
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    return None


class FsAdapter:
    """Polls drop folders and submits settled files to the inbox."""

    name = "fs"

    def __init__(self, inbox, dirs: list[Path], stable_polls: int = 2, interval: float = 5.0):
        self.inbox, self.dirs, self.stable_polls = inbox, [Path(d) for d in dirs], stable_polls
        self.interval = interval
        self._seen: dict[Path, tuple[int, int]] = {}  # path -> (size, consecutive stable polls)
        self.skipped: dict[Path, str] = {}

    def _skip(self, p: Path, reason: str) -> None:
        """Remember and report (once per file) a file left in place, never submitted."""
        if p not in self.skipped:
            log.warning("fs adapter: skipping %s (%s); the file is left in the folder", p, reason)
        self.skipped[p] = reason

    def _candidate(self, d: Path, p: Path) -> os.stat_result | None:
        """stat of `p` if it is a regular, in-folder, not oversize file; else None."""
        if p.name.startswith(".") or p.name.endswith(_SKIP_SUFFIX):
            return None
        try:
            if p.is_symlink() and not p.resolve().is_relative_to(d.resolve()):
                self._skip(p, "symlink outside folder")
                return None
            st = p.stat() if p.is_file() else None
        except OSError:
            return None
        if st and st.st_size > self.inbox.cfg.max_fetch_bytes:
            self._skip(p, "larger than max_fetch_bytes")
            return None
        self.skipped.pop(p, None)  # fixed since: warn again if it goes bad again
        return st

    def _eligible(self, d: Path, p: Path) -> bool:
        """True once `p` is old enough and its size was stable for `stable_polls` polls."""
        st = self._candidate(d, p)
        if st is None:
            return False
        if time.time() - st.st_mtime < MIN_AGE:
            self._seen.pop(p, None)
            return False
        size, n = self._seen.get(p, (-1, 0))
        n = n + 1 if size == st.st_size else 1
        self._seen[p] = (st.st_size, n)
        return n >= self.stable_polls

    def poll(self) -> int:
        """One scan of every folder; returns how many files were submitted and moved."""
        done = 0
        self.skipped = {p: r for p, r in self.skipped.items() if p.exists() or p.is_symlink()}
        for d in self.dirs:
            if not d.is_dir():
                continue
            for p in sorted(d.iterdir()):
                if not self._eligible(d, p):
                    continue
                try:
                    self._submit(p)
                    self._move(d, p)
                except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                    # leave the file in place; retried next poll
                    log.warning("fs adapter: %s not processed", p, exc_info=True)
                    continue
                self._seen.pop(p, None)
                done += 1
        return done

    def _submit(self, p: Path) -> None:
        st = p.stat()
        # the same unchanged file re-seen after a crash is a no-op
        key = f"{p.name}:{st.st_size}:{st.st_mtime_ns}"
        urls = _link_urls(p)
        if urls:
            for u in urls:
                self.inbox.submit(adapter=self.name, text=u, user_context=f"from {p.name}",
                                  external_id=f"{key}:{u}")
        else:
            self.inbox.submit(adapter=self.name, file=p, filename=p.name, external_id=key)

    @staticmethod
    def _move(d: Path, p: Path) -> None:
        dest = d / ".processed"
        dest.mkdir(exist_ok=True)
        target = dest / p.name
        if target.exists():
            target = dest / f"{uuid.uuid4().hex[:8]}-{p.name}"
        shutil.move(str(p), str(target))

    def run_forever(self, interval: float = 5.0, stop=None) -> None:
        """Poll until `stop` (a threading.Event) is set; forever when it is None."""
        while not (stop and stop.is_set()):
            self.poll()
            if stop is None:
                time.sleep(interval)
            else:
                stop.wait(interval)
