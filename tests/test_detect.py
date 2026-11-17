from pith.pipeline.detect import detect


def row(**kw):
    base = dict(kind_hint="text", payload_text=None, canonical_url=None, original_filename=None,
                mime=None, blob_sha256=None)
    return {**base, **kw}


class Blobs:
    def __init__(self, tmp_path, data=b""):
        self.p = tmp_path / "b"
        self.p.write_bytes(data)

    def path(self, sha):
        return self.p


def test_detect_url_and_file_types(tmp_path):
    assert detect(row(kind_hint="url", canonical_url="https://www.youtube.com/watch?v=1"), None) == "video"
    assert detect(row(kind_hint="url", canonical_url="https://x.org/a.pdf"), None) == "pdf"
    assert detect(row(kind_hint="url", canonical_url="https://x.org/post"), None) == "web"
    assert detect(row(kind_hint="text", payload_text="just a thought"), None) == "note"
    assert detect(row(kind_hint="text", payload_text="```py\nx=1\n```"), None) == "code"
    assert detect(row(kind_hint="file", original_filename="a.pdf", blob_sha256="x"), Blobs(tmp_path)) == "pdf"
    assert detect(row(kind_hint="file", original_filename="a.mp3", blob_sha256="x"), Blobs(tmp_path)) == "audio"
    assert detect(row(kind_hint="file", original_filename="a.md", blob_sha256="x"), Blobs(tmp_path)) == "text"
    assert detect(row(kind_hint="file", original_filename="a.docx", blob_sha256="x"), Blobs(tmp_path)) == "document"
    assert detect(row(kind_hint="file", original_filename="noext", blob_sha256="x"), Blobs(tmp_path, b"%PDF-1.4")) == "pdf"
    assert detect(row(kind_hint="file", original_filename="noext", blob_sha256="x"), Blobs(tmp_path, b"\x89PNG\r\n")) == "image"
    assert detect(row(kind_hint="file", original_filename="noext", blob_sha256="x"), Blobs(tmp_path, b"hello")) == "text"
    assert detect(row(kind_hint="file", original_filename="x.py", blob_sha256="x"), Blobs(tmp_path, b"def f():\n  pass")) == "code"


def test_detect_media_by_magic_without_extension(tmp_path):
    f = lambda data: detect(row(kind_hint="file", original_filename="noext", blob_sha256="x"), Blobs(tmp_path, data))
    assert f(b"RIFF\x00\x00\x00\x00WAVEfmt ") == "audio"
    assert f(b"ID3\x04\x00\x00\x00\x00\x00\x0a\x00") == "audio"
    assert f(b"ID3 x is a text file about things") == "text"
    assert f(b"ID3") == "text"
    assert f(b"\x00\x00\x00\x20ftypheic\x00") == "image" and f(b"\x00\x00\x00\x20ftypavif\x00") == "image"
    assert f(b"OggS\x00") == "audio" and f(b"fLaC\x00") == "audio"
    assert f(b"\x00\x00\x00\x20ftypM4A \x00") == "audio"
    assert f(b"\x00\x00\x00\x20ftypisom\x00") == "video"
    assert f(b"\x1a\x45\xdf\xa3\x00") == "video"
    assert detect(row(kind_hint="url", canonical_url="https://v.example/a.m4a"), None) == "audio"
    assert detect(row(kind_hint="url", canonical_url="https://www.tiktok.com/@u/video/1"), None) == "video"
    assert detect(row(kind_hint="file", original_filename="a.MOV", blob_sha256="x"), Blobs(tmp_path)) == "video"
