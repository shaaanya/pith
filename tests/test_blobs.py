import hashlib

from infoparser.store.blobs import BlobStore


def test_blob_put_idempotent_and_sharded(tmp_path):
    bs = BlobStore(tmp_path / "blobs")
    sha = bs.put_bytes(b"hello")
    assert sha == hashlib.sha256(b"hello").hexdigest()
    assert bs.put_bytes(b"hello") == sha
    files = [p for p in (tmp_path / "blobs").rglob("*") if p.is_file()]
    assert len(files) == 1
    assert files[0] == bs.path(sha) == tmp_path / "blobs" / sha[:2] / sha[2:4] / sha
    assert bs.exists(sha) and not bs.exists("0" * 64)
    assert bs.path(sha).read_bytes() == b"hello"


def test_put_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"data")
    bs = BlobStore(tmp_path / "blobs")
    assert bs.put_file(f) == bs.put_bytes(b"data")
