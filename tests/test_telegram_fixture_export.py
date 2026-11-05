"""Telegram Desktop `result.json` importer against a FIXTURE-BASED export.

FIXTURE-BASED: built by hand from the documented Telegram Desktop export shape. No real export was
ever available, so nothing here is evidence about real exports.
"""
import json
import subprocess
import sys
import time

import pytest

from infoparser.adapters.telegram_export import import_export
from infoparser.pipeline import runner
from infoparser.worker import Failed, NeedsClarification, Processed

NOT_INCLUDED = "(File not included. Change data exporting settings to download.)"
LINK = "https://example.org/read?utm_source=tg"


def msg(mid, text="", **kw):
    """A Telegram Desktop message dict."""
    return {"id": mid, "type": "message", "date": f"2024-03-{(mid % 28) + 1:02d}T10:00:00",
            "date_unixtime": "1709287200", "from": "Alice", "from_id": "user1", "text": text,
            "text_entities": [{"type": "plain", "text": text}] if isinstance(text, str) else [],
            **kw}


def write_export(root, messages, **top):
    """Write result.json (+ media written by the caller) and return its path."""
    root.mkdir(exist_ok=True)
    path = root / "result.json"
    path.write_text(json.dumps({"name": "Friends", "type": "private_group", "id": 4242,
                                "messages": messages, **top}, ensure_ascii=False), "utf-8")
    return path


@pytest.fixture(name="export")
def export_fixture(tmp_path):
    """An export directory with the documented message kinds and real media files."""
    root = tmp_path / "ChatExport_2024-03-01"
    (root / "photos").mkdir(parents=True)
    (root / "files").mkdir()
    (root / "voice_messages").mkdir()
    (root / "stickers").mkdir()
    (root / "photos" / "photo_1@01-03-2024_10-00-00.jpg").write_bytes(b"\xff\xd8\xff\xe0jpeg-ish")
    (root / "files" / "notes.txt").write_text("Sourdough hydration notes: 75 percent.", "utf-8")
    (root / "voice_messages" / "audio_1.ogg").write_bytes(b"OggS" + b"\0" * 60)
    (root / "stickers" / "sticker.webp").write_bytes(b"RIFF\0\0\0\0WEBPVP8 ")
    entities = [{"type": "plain", "text": "Read "}, {"type": "link", "text": LINK},
                {"type": "plain", "text": " then "},
                {"type": "text_link", "text": "this", "href": "https://example.com/b"},
                {"type": "bold", "text": " bold"}, {"type": "italic", "text": " it"},
                {"type": "pre", "text": "print('hi')", "language": "python"},
                {"type": "code", "text": "x=1"}, {"type": "mention", "text": "@bob"},
                {"type": "hashtag", "text": "#bread"}]
    messages = [
        {"id": 1, "type": "service", "date": "2024-03-01T09:00:00", "actor": "Alice",
         "actor_id": "user1", "action": "create_group", "title": "Friends", "text": ""},
        msg(2, "plain sourdough note"),
        {**msg(3, [e["text"] for e in entities[:1]] + entities[1:]), "text_entities": entities},
        msg(4, "forwarded wisdom", forwarded_from="Bob", reply_to_message_id=2),
        msg(5, "look at this", photo="photos/photo_1@01-03-2024_10-00-00.jpg", width=10, height=10),
        msg(6, "", file="voice_messages/audio_1.ogg", media_type="voice_message",
            mime_type="audio/ogg", duration_seconds=3),
        msg(7, "the doc", file="files/notes.txt", file_name="notes.txt", mime_type="text/plain"),
        msg(8, "", file="stickers/sticker.webp", media_type="sticker", sticker_emoji="x"),
        {"id": 9, "type": "service", "date": "2024-03-02T09:00:00", "actor": "Bob",
         "action": "pin_message", "message_id": 2, "text": ""},
        msg(10, "", photo=NOT_INCLUDED),
        msg(11, "caption for a photo that was not exported", photo=NOT_INCLUDED),
        msg(12, LINK),
        {**msg(13, "from a deleted account"), "from": None, "from_id": "user999"},
        msg(14, "Привет мир, 你好, emoji \U0001F35E, RTL שלום"),
    ]
    return write_export(root, messages)


def rows(svc):
    """Inbox rows by external id suffix (message id)."""
    return {int(r["external_id"].split(":")[1]): r for r in svc.conn.execute(
        "SELECT * FROM inbox_items WHERE adapter='telegram_export'")}


def test_documented_shapes_are_imported_or_skipped_as_designed(svc, export):
    """Service messages skipped; text/entity/forwarded/reply/photo/voice/file messages submitted."""
    rep = import_export(svc.inbox, export)
    got = rows(svc)
    assert set(got) == {2, 3, 4, 5, 6, 7, 8, 11, 12, 13, 14}  # 1, 9 service; 10 media-less
    assert (rep.submitted, rep.skipped, rep.duplicates) == (len(got), 3, 0)
    assert "forwarded from Bob" in got[4]["user_context"]
    assert "Alice" in got[2]["user_context"] and "from" not in got[13]["user_context"]
    # entity list flattened to text; the text_link href kept; entities' links visible
    assert "Read" in got[3]["payload_text"] and "https://example.com/b" in got[3]["payload_text"]
    assert "print('hi')" in got[3]["payload_text"]
    assert got[5]["blob_sha256"] and got[5]["original_filename"].startswith("photo_1")
    assert got[7]["original_filename"] == "notes.txt"
    assert "[missing media" in got[11]["payload_text"] and got[11]["blob_sha256"] is None
    assert got[14]["payload_text"].startswith("Привет мир")


def test_default_never_fetches_url_only_message_and_flag_opts_in(svc, export):
    """URL-only message: note by default (verbatim), url submission with fetch_urls."""
    import_export(svc.inbox, export)
    r = rows(svc)[12]
    assert (r["kind_hint"], r["canonical_url"], r["payload_text"]) == ("text", None, LINK)
    assert svc.inbox.get(r["id"])["status"] == "pending"
    iid = r["id"]
    assert isinstance(runner.process(svc, iid), Processed)
    assert svc.inbox.get(iid)["content_type"] == "note"


def test_cli_flag_default_and_opt_in(tmp_path, export):
    """`import-telegram` stores notes by default; --fetch-urls stores a url submission."""
    def run(home, *extra):
        r = subprocess.run([sys.executable, "-m", "infoparser.cli", "--home", str(home),
                            "import-telegram", str(export), *extra],
                           capture_output=True, text=True, timeout=60, check=False,
                           env={"HOME": str(tmp_path / "h"), "PATH": "/usr/bin:/bin"})
        assert r.returncode == 0, r.stderr
        return r.stdout
    kinds = {}
    for name, extra in (("a", ()), ("b", ("--fetch-urls",))):
        home = tmp_path / name
        assert "submitted 11" in run(home, *extra)
        db = subprocess.run([sys.executable, "-c",
                             "import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);print(c.execute("
                             "\"select kind_hint from inbox_items where external_id='4242:12'\")"
                             ".fetchone()[0])", str(next(home.rglob("*.db")))],
                            capture_output=True, text=True, check=True).stdout.strip()
        kinds[name] = db
    assert kinds == {"a": "text", "b": "url"}


def test_whole_export_processes_without_crashing(svc, export):
    """Every imported item ends processed, needs_clarification or failed: nothing is left stuck."""
    import_export(svc.inbox, export)
    outcomes = {mid: type(runner.process(svc, r["id"])) for mid, r in rows(svc).items()}
    assert set(outcomes.values()) <= {Processed, NeedsClarification, Failed}
    assert outcomes[5] is NeedsClarification or outcomes[5] is Processed  # photo: OCR or asks
    assert outcomes[6] is NeedsClarification  # voice note: no whisper -> asks for text


def test_reimport_is_a_noop(svc, export):
    """Same export twice: nothing new, everything counted as a duplicate."""
    first = import_export(svc.inbox, export)
    second = import_export(svc.inbox, export)
    assert (second.submitted, second.duplicates) == (0, first.submitted)


@pytest.mark.parametrize("target", ["../secret.txt", "/etc/hosts", "photos/../../secret.txt",
                                    "link_out.txt", ".", "photos"])
def test_media_path_cannot_escape_the_export_dir(svc, tmp_path, target):
    """A hostile `file` path never reads outside the export (symlink, ../, absolute, dir)."""
    (tmp_path / "secret.txt").write_text("TOP-SECRET-CONTENT", "utf-8")
    root = tmp_path / "exp"
    (root / "photos").mkdir(parents=True)
    (root / "link_out.txt").symlink_to(tmp_path / "secret.txt")
    path = write_export(root, [msg(1, "see attachment", file=target)])
    rep = import_export(svc.inbox, path)
    row = rows(svc)[1]
    assert rep.submitted == 1 and row["blob_sha256"] is None
    assert f"[missing media: {target}]" in row["payload_text"]
    assert "TOP-SECRET" not in json.dumps([dict(r) for r in svc.conn.execute(
        "SELECT * FROM inbox_items")])


def test_media_value_of_wrong_type_is_a_note_not_a_crash(svc, tmp_path):
    """`file`/`photo` as a list or number: note about missing media."""
    path = write_export(tmp_path / "e", [msg(1, "x", file=["a"]), msg(2, "y", photo=7)])
    assert import_export(svc.inbox, path).submitted == 2


@pytest.mark.parametrize("raw", [b"", b"{", b'{"messages": [{"id": 1, "type": "mess',
                                 b'[1, 2]', b'{"messages": "nope"}', b"\xff\xfe\x00\x00garbage",
                                 '{"messages": []}'.encode("utf-16")])
def test_malformed_truncated_or_wrongly_encoded_json_is_a_clean_error(svc, tmp_path, raw):
    """ValueError naming the file; nothing is imported; no traceback type leaks."""
    bad = tmp_path / "result.json"
    bad.write_bytes(raw)
    with pytest.raises(ValueError, match="not a Telegram export"):
        import_export(svc.inbox, bad)
    assert svc.conn.execute("SELECT count(*) FROM inbox_items").fetchone()[0] == 0


def test_utf8_bom_export_is_accepted(svc, tmp_path):
    """Editors and Windows tools add a UTF-8 BOM; the export is still valid JSON text."""
    path = write_export(tmp_path / "e", [msg(1, "bom note")])
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert import_export(svc.inbox, path).submitted == 1


def test_oversize_media_is_not_ingested(svc, tmp_path):
    """Exports hold multi-GB videos: files over max_fetch_bytes never enter the blob store."""
    root = tmp_path / "e"
    (root / "video_files").mkdir(parents=True)
    (root / "video_files" / "big.mp4").write_bytes(b"\0" * 2000)
    path = write_export(root, [msg(1, "big video", file="video_files/big.mp4")])
    svc.cfg.max_fetch_bytes = 1000
    import_export(svc.inbox, path)
    row = rows(svc)[1]
    assert row["blob_sha256"] is None and "max_fetch_bytes" in row["payload_text"]


def test_very_large_chat_imports_in_reasonable_time(svc, tmp_path):
    """3000 messages: all submitted once, idempotent re-import, well under a minute."""
    path = write_export(tmp_path / "e", [msg(i, f"message number {i} about topic {i % 17}")
                                         for i in range(1, 3001)])
    t0 = time.monotonic()
    assert import_export(svc.inbox, path).submitted == 3000
    assert time.monotonic() - t0 < 60
    assert import_export(svc.inbox, path).duplicates == 3000
