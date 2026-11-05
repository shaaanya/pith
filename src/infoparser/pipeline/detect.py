import re
from pathlib import PurePosixPath
from urllib.parse import urlparse

_VIDEO_HOSTS = ("youtube.com", "youtu.be", "instagram.com", "tiktok.com", "vimeo.com")
_EXT = {
    "pdf": "pdf", "mp3": "audio", "wav": "audio", "m4a": "audio", "ogg": "audio", "flac": "audio",
    "mp4": "video", "mov": "video", "mkv": "video", "webm": "video",
    "png": "image", "jpg": "image", "jpeg": "image", "gif": "image", "webp": "image", "heic": "image",
    "docx": "document", "pptx": "document", "xlsx": "document", "epub": "document",
    "txt": "text", "md": "text", "markdown": "text", "rst": "text",
    "py": "code", "js": "code", "ts": "code", "go": "code", "rs": "code", "java": "code", "c": "code",
    "cpp": "code", "sh": "code", "rb": "code", "swift": "code",
}
_MAGIC = [(b"%PDF", "pdf"), (b"\x89PNG", "image"), (b"\xff\xd8\xff", "image"), (b"GIF8", "image"),
          (b"PK\x03\x04", "document")]
_CODE = re.compile(r"```|^\s*(def |class |import |function |#include|public class )", re.M)


def _by_ext(name: str | None) -> str | None:
    ext = PurePosixPath(name or "").suffix.lstrip(".").lower()
    return _EXT.get(ext)


def detect(row, blobs) -> str:
    url = row["canonical_url"]
    if url:
        p = urlparse(url)
        host = (p.hostname or "").removeprefix("www.")
        if any(host == h or host.endswith("." + h) for h in _VIDEO_HOSTS):
            return "video"
        return {"video": "video", "audio": "audio", "pdf": "pdf", "image": "image"}.get(_by_ext(p.path), "web")
    if row["blob_sha256"]:
        ct = _by_ext(row["original_filename"])
        head = b""
        if ct is None:
            with open(blobs.path(row["blob_sha256"]), "rb") as f:
                head = f.read(4096)
        if ct is None:
            ct = next((c for m, c in _MAGIC if head.startswith(m)), None)
        if ct is None and row["mime"]:
            ct = {"application/pdf": "pdf"}.get(row["mime"]) or (
                row["mime"].split("/")[0] if row["mime"].split("/")[0] in ("audio", "video", "image") else None)
        if ct is None:
            ct = "text"
        return ct
    return "code" if _CODE.search(row["payload_text"] or "") else "note"
