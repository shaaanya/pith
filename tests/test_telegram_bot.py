"""Receive-only Telegram bot channel, against a local fake of the Bot API."""
import pytest
from stubs.fake_telegram import FakeTelegram

from pith.adapters.telegram_bot import TelegramChannel, load_token
from pith.config import load_config

CHAT = 7


@pytest.fixture(name="fake")
def fake_fixture():
    with FakeTelegram() as f:
        yield f


def channel(svc, fake, **section):
    sec = {"api_base": fake.url, "poll_timeout": 0, "allowed_chat_ids": [CHAT], **section}
    return TelegramChannel(svc, sec, fake.token)


def rows(svc):
    return svc.conn.execute("SELECT * FROM inbox_items ORDER BY external_id").fetchall()


def offset(svc):
    r = svc.conn.execute("SELECT value FROM channel_state WHERE channel='telegram' AND key='offset'")
    r = r.fetchone()
    return int(r[0]) if r else None


def test_bare_url_submits_url_item(svc, fake):
    fake.message(CHAT, "https://example.com/a")
    assert channel(svc, fake).poll() == 1
    (r,) = rows(svc)
    assert r["payload_text"] == "https://example.com/a" and r["kind_hint"] == "url"
    assert r["adapter"] == "telegram"


def test_text_with_urls_one_item_per_url_with_context(svc, fake):
    text = "read https://a.example/x and https://b.example/y."
    mid = fake.message(CHAT, text)
    assert channel(svc, fake).poll() == 2
    rs = rows(svc)
    assert [r["external_id"] for r in rs] == [f"{CHAT}:{mid}:0", f"{CHAT}:{mid}:1"]
    assert {r["payload_text"] for r in rs} == {"https://a.example/x", "https://b.example/y"}
    assert all(r["user_context"] == text for r in rs)


def test_plain_text_is_note(svc, fake):
    mid = fake.message(CHAT, "remember the quokkas")
    assert channel(svc, fake).poll() == 1
    (r,) = rows(svc)
    assert r["payload_text"] == "remember the quokkas" and r["kind_hint"] == "text"
    assert r["external_id"] == f"{CHAT}:{mid}"


def test_document_downloaded_as_file_with_caption_context(svc, fake):
    fake.files["f1"] = b"%PDF-1.4 hello"
    fake.message(CHAT, document={"file_id": "f1", "file_name": "a.pdf",
                                 "mime_type": "application/pdf", "file_size": 14},
                 caption="why I saved it")
    assert channel(svc, fake).poll() == 1
    (r,) = rows(svc)
    assert r["kind_hint"] == "file" and r["original_filename"] == "a.pdf"
    assert r["mime"] == "application/pdf" and r["user_context"] == "why I saved it"
    assert svc.blobs.path(r["blob_sha256"]).read_bytes() == b"%PDF-1.4 hello"


def test_photo_uses_largest_size(svc, fake):
    fake.files["small"], fake.files["big"] = b"s", b"BIGPNG"
    fake.message(CHAT, photo=[{"file_id": "small", "width": 10, "height": 10},
                              {"file_id": "big", "width": 800, "height": 600}])
    assert channel(svc, fake).poll() == 1
    (r,) = rows(svc)
    assert svc.blobs.path(r["blob_sha256"]).read_bytes() == b"BIGPNG"


def test_oversize_file_skipped_and_later_update_still_processed(svc, fake):
    svc.cfg.max_fetch_bytes = 10
    fake.files["big"] = b"x" * 100
    fake.files["nosize"] = b"y" * 50  # no file_size announced: caught while downloading
    fake.message(CHAT, document={"file_id": "big", "file_size": 100})
    fake.message(CHAT, document={"file_id": "nosize"})
    last = fake.message(CHAT, "still here")
    assert channel(svc, fake).poll() == 1
    assert [r["payload_text"] for r in rows(svc)] == ["still here"]
    assert offset(svc) == last + 1


def test_unfetchable_download_skipped_and_later_update_still_processed(svc, fake):
    fake.files["gone"] = b"x"
    fake.broken.add("gone")  # getFile works, the download itself answers 404
    fake.message(CHAT, document={"file_id": "gone", "file_size": 1})
    last = fake.message(CHAT, "next one")
    assert channel(svc, fake).poll() == 1
    assert [r["payload_text"] for r in rows(svc)] == ["next one"] and offset(svc) == last + 1


def test_bad_config_does_not_raise_at_construction(svc, fake):
    ch = TelegramChannel(svc, {"api_base": fake.url, "allowed_chat_ids": 5}, fake.token)
    with pytest.raises(TypeError):
        ch.poll()  # surfaces through run_channel as last_error, never as a dead run


def test_unknown_chat_ignored_and_offset_advances(svc, fake):
    last = fake.message(999, "hello from a stranger")
    assert channel(svc, fake).poll() == 0
    assert rows(svc) == [] and offset(svc) == last + 1


def test_sticker_and_edited_message_ignored_offset_advances(svc, fake):
    fake.message(CHAT, sticker={"file_id": "s"})
    last = fake.queue_update({"edited_message": {"message_id": 1, "chat": {"id": CHAT},
                                                 "text": "edited"}})
    assert channel(svc, fake).poll() == 0
    assert rows(svc) == [] and offset(svc) == last + 1


def test_offset_persisted_and_not_replayed(svc, fake):
    last = fake.message(CHAT, "one")
    ch = channel(svc, fake)
    assert ch.poll() == 1
    assert ch.poll() == 0
    bodies = fake.getupdates_bodies()
    assert bodies[1]["offset"] == last + 1 and len(rows(svc)) == 1
    assert channel(svc, fake).poll() == 0  # a new channel object resumes from stored state


def test_submit_failure_keeps_offset_and_redelivery_is_not_duplicate(svc, fake, monkeypatch):
    first = fake.message(CHAT, "first note")
    fake.message(CHAT, "second note")
    real, calls = svc.inbox.submit, []

    def flaky(**kw):
        calls.append(kw["external_id"])
        if len(calls) == 2:
            raise OSError("disk full")
        return real(**kw)
    monkeypatch.setattr(svc.inbox, "submit", flaky)
    ch = channel(svc, fake)
    with pytest.raises(OSError):
        ch.poll()
    assert offset(svc) == first + 1  # the handled update is confirmed, the failed one is not
    assert ch.poll() == 1
    assert [r["payload_text"] for r in rows(svc)] == ["first note", "second note"]


def test_token_never_in_error(svc, fake):
    ch = channel(svc, fake)
    fake.fail_next(401)
    with pytest.raises(RuntimeError) as e:
        ch.poll()
    assert fake.token not in str(e.value) and "401" in str(e.value)
    dead = TelegramChannel(svc, {"api_base": "http://127.0.0.1:9", "poll_timeout": 0}, fake.token)
    with pytest.raises(RuntimeError) as e:
        dead.poll()
    assert fake.token not in str(e.value)


def test_token_loading(tmp_path):
    cfg = load_config(env={"PITH_HOME": str(tmp_path / "home")})
    with pytest.raises(ValueError, match="telegram_token"):
        load_token(cfg, env={})
    cfg.home.mkdir(parents=True)
    (cfg.home / "telegram_token").write_text("  111:file-token\n")
    assert load_token(cfg, env={}) == "111:file-token"
    assert load_token(cfg, env={"PITH_TELEGRAM_TOKEN": "222:env-token"}) == "222:env-token"


def test_reply_to_a_saved_message_adds_a_note_not_a_new_item(svc, fake):
    mid = fake.message(CHAT, "https://example.com/reel")
    channel(svc, fake).poll()
    fake.message(CHAT, "just the music", reply_to_message={"message_id": mid})
    assert channel(svc, fake).poll() == 1
    (r,) = rows(svc)
    assert r["user_note"] == "just the music" and r["status"] == "pending"


def test_reply_to_an_unknown_message_is_saved_as_a_normal_note(svc, fake):
    fake.message(CHAT, "remember this", reply_to_message={"message_id": 999})
    assert channel(svc, fake).poll() == 1
    (r,) = rows(svc)
    assert r["payload_text"] == "remember this" and r["kind_hint"] != "url"


def test_reply_with_a_url_is_a_new_save(svc, fake):
    mid = fake.message(CHAT, "https://example.com/a")
    channel(svc, fake).poll()
    fake.message(CHAT, "https://example.com/b", reply_to_message={"message_id": mid})
    channel(svc, fake).poll()
    assert len(rows(svc)) == 2


def test_reply_to_text_with_url_and_context_finds_the_item(svc, fake):
    mid = fake.message(CHAT, "watch https://example.com/c later")
    channel(svc, fake).poll()
    fake.message(CHAT, "the soundtrack", reply_to_message={"message_id": mid})
    channel(svc, fake).poll()
    (r,) = rows(svc)
    assert r["user_note"] == "the soundtrack"
