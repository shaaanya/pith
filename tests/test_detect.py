from infoparser.pipeline.detect import detect


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
