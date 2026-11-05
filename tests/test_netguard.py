"""SSRF guard: untrusted fetches reach public addresses only; redirects are re-checked per hop."""
import ipaddress
import socket

import pytest
from stubs.http_fixture_server import FixtureServer, Route

from infoparser import netguard
from infoparser.pipeline.extractors import web

PRIVATE = [
    "http://127.0.0.1/x",
    "http://localhost/x",
    "http://10.1.2.3/x",
    "http://192.168.0.5/x",
    "http://172.16.0.1/x",
    "http://169.254.169.254/latest/meta-data/",
    "http://0.0.0.0/x",
    "http://224.0.0.1/x",
    "http://[::1]/x",
    "http://[::]/x",
    "http://[fe80::1]/x",
    "http://[fc00::1]/x",
    "http://[::ffff:127.0.0.1]/x",
    "http://[::ffff:7f00:1]/x",
    "http://[64:ff9b::7f00:1]/x",
    "http://2130706433/x",
    "http://0x7f000001/x",
    "http://0177.0.0.1/x",
    "http://127.1/x",
    "http://public.test@127.0.0.1/x",
    "http://127.0.0.1#@public.test/x",
]


@pytest.fixture(autouse=True)
def stub_dns(monkeypatch):
    """Names resolve through a table; nothing touches the network."""
    table = {"localhost": ["127.0.0.1", "::1"], "public.test": ["93.184.216.34"],
             "rebind.test": ["93.184.216.34", "10.0.0.5"], "other.test": ["93.184.216.35"]}

    def fake(host):
        if host not in table:
            raise netguard.BlockedURL(f"cannot resolve {host!r}")
        return table[host]

    monkeypatch.setattr(netguard, "resolve", fake)


@pytest.mark.parametrize("url", PRIVATE)
def test_untrusted_refuses_non_public(url):
    """Private, loopback, link-local, metadata, IPv6, mapped and odd IPv4 forms are all refused."""
    with pytest.raises(netguard.BlockedURL):
        netguard.check_url(url, allow_private=False)
    with pytest.raises(netguard.BlockedURL):
        web.fetch(url, max_bytes=100, untrusted=True)


@pytest.mark.parametrize("url", ["http://public.test/x", "https://93.184.216.34/x",
                                 "http://[2606:2800:220:1::1]/x"])
def test_public_addresses_pass(url):
    """Ordinary public addresses pass the guard."""
    netguard.check_url(url, allow_private=False)
    assert not netguard.private_target(url)


def test_mixed_records_and_unresolvable_are_refused():
    """One private record among public ones, or no answer at all, is refused."""
    with pytest.raises(netguard.BlockedURL):
        netguard.check_url("http://rebind.test/", allow_private=False)
    with pytest.raises(netguard.BlockedURL):
        netguard.check_url("http://nxdomain.test/", allow_private=False)
    assert not netguard.private_target("http://rebind.test/")  # mixed counts as public


def _deny(host):
    raise netguard.BlockedURL(host)


@pytest.fixture
def public_loopback(monkeypatch):
    """Treat 127.0.0.1 as a public address so a loopback stub server can play 'the internet'."""
    real = netguard.is_public
    monkeypatch.setattr(netguard, "is_public",
                        lambda ip: ip == ipaddress.ip_address("127.0.0.1") or real(ip))
    monkeypatch.setattr(netguard, "resolve",
                        lambda h: ["127.0.0.1"] if h.endswith(".pub") else _deny(h))
    real_gai = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda h, *a, **k: real_gai("127.0.0.1" if h.endswith(".pub") else h,
                                                    *a, **k))


@pytest.mark.parametrize("untrusted", [True, False])
@pytest.mark.usefixtures("public_loopback")
def test_public_target_is_fetched(untrusted):
    """A public target is fetched under both trusts."""
    with FixtureServer({"/ok": Route(b"hello", ctype="text/plain")}) as srv:
        port = srv.base.rsplit(":", 1)[1]
        res = web.fetch(f"http://a.pub:{port}/ok", max_bytes=100, untrusted=untrusted)
        assert res.body == b"hello" and srv.hits == ["/ok"]


@pytest.mark.parametrize("untrusted", [True, False])
@pytest.mark.parametrize("target", [
    "http://10.0.0.5/x", "http://169.254.169.254/x", "http://[::1]/x",
    "http://0x0a000005/x", "http://[::ffff:10.0.0.1]/x"])
@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
@pytest.mark.usefixtures("public_loopback")
def test_redirect_from_public_to_private_is_refused(untrusted, target, code):
    """Every redirect status to a private target is refused for both trusts."""
    routes = {"/r": Route(b"", code, headers={"Location": target})}
    with FixtureServer(routes) as srv:
        port = srv.base.rsplit(":", 1)[1]
        with pytest.raises(netguard.BlockedURL):
            web.fetch(f"http://a.pub:{port}/r", max_bytes=100, untrusted=untrusted)


@pytest.mark.parametrize("untrusted", [True, False])
@pytest.mark.usefixtures("public_loopback")
def test_every_hop_is_rechecked(untrusted):
    """A public -> public -> private chain is stopped at the third hop, before any connect."""
    routes = {"/1": Route(b"", 302),
              "/2": Route(b"", 302, headers={"Location": "http://10.0.0.5/3"})}
    with FixtureServer(routes) as srv:
        port = srv.base.rsplit(":", 1)[1]
        routes["/1"].headers["Location"] = f"http://b.pub:{port}/2"
        with pytest.raises(netguard.BlockedURL):
            web.fetch(f"http://a.pub:{port}/1", max_bytes=100, untrusted=untrusted)
        assert srv.hits == ["/1", "/2"]


def test_direct_submission_of_a_private_url_still_works():
    """A user may submit a loopback URL directly; the same URL is refused when untrusted."""
    with FixtureServer({"/ok": Route(b"hi", ctype="text/plain"),
                        "/r": Route(b"", 302, headers={"Location": "/ok"})}) as srv:
        assert web.fetch(srv.base + "/r", max_bytes=100).body == b"hi"
        with pytest.raises(netguard.BlockedURL):  # same URL is refused when untrusted
            web.fetch(srv.base + "/ok", max_bytes=100, untrusted=True)


@pytest.mark.usefixtures("public_loopback")
def test_peer_address_is_checked_after_connect(monkeypatch):
    """Rebinding gap: a pre-check fooled into passing is caught on the connected peer."""
    monkeypatch.setattr(netguard, "is_public", lambda ip: str(ip) != "127.0.0.1")
    monkeypatch.setattr(netguard, "check_url", lambda *a, **k: None)  # pre-check fooled
    with FixtureServer({"/ok": Route(b"x", ctype="text/plain")}) as srv:
        port = srv.base.rsplit(":", 1)[1]
        with pytest.raises(netguard.BlockedURL, match="connection"):
            web.fetch(f"http://a.pub:{port}/ok", max_bytes=100, untrusted=True)
        assert not srv.hits  # the request was never sent


def test_untrusted_row_is_decided_by_adapter():
    """Rows from the Telegram importer are untrusted; direct adapters are not."""
    row = {"adapter": "telegram_export"}
    assert netguard.untrusted(row) and not netguard.untrusted({"adapter": "http"})
