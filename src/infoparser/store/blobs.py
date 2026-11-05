import hashlib
import os
import re
import tempfile
from pathlib import Path

_SHA = re.compile(r"[0-9a-f]{64}")


class BlobStore:
    """Content-addressed originals: root/ab/cd/<sha256>."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, sha: str) -> Path:
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):  # never build a path from unvalidated text
            raise ValueError("invalid blob id")
        return self.root / sha[:2] / sha[2:4] / sha

    def exists(self, sha: str) -> bool:
        try:
            return self.path(sha).is_file()
        except ValueError:
            return False

    def put_bytes(self, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        dest = self.path(sha)
        if not dest.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, dest)  # atomic: no partial blobs
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        return sha

    def put_file(self, path: Path) -> str:
        # ponytail: reads whole file into memory; stream if max_fetch_bytes grows
        return self.put_bytes(Path(path).read_bytes())
