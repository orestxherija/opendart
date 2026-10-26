"""Keep guide fetching on the official host without redirects or real network access."""

from __future__ import annotations

from email.message import Message
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import HTTPHandler, HTTPSHandler
from urllib.response import addinfourl

import pytest

from scripts.api_reference.snapshot import BASE, read_guide


@pytest.fixture
def guide_http(monkeypatch):
    """Exercise urllib's real response handlers with synthetic HTTP responses."""
    calls = []
    streams = []
    reply = {"status": 200, "body": "<html>공시 guide</html>".encode(), "location": None}

    def respond(self, request):
        calls.append((request.full_url, request.timeout))
        headers = Message()
        if reply["location"] is not None:
            headers["Location"] = reply["location"]
        stream = BytesIO(reply["body"])
        streams.append(stream)
        response = addinfourl(stream, headers, request.full_url, reply["status"])
        response.msg = "Synthetic response"
        return response

    monkeypatch.setattr(HTTPHandler, "http_open", respond)
    monkeypatch.setattr(HTTPSHandler, "https_open", respond)
    return reply, calls, streams


@pytest.mark.parametrize(
    ("name", "path"),
    [("DE001", "/guide/main.do?apiGrpCd=DE001"), ("AE00001", "/guide/detail.do?apiId=AE00001")],
)
def test_official_guide_is_fetched_and_cached(tmp_path, guide_http, name, path):
    reply, calls, streams = guide_http
    url = BASE + path
    cache = tmp_path / "html"
    html = read_guide(name, url, cache)
    assert html == reply["body"].decode("utf-8")
    assert calls == [(url, 60)]
    assert streams[0].closed
    assert (cache / (name + ".html")).read_text(encoding="utf-8") == html
    assert read_guide(name, url, cache) == html
    assert len(calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://engopendart.fss.or.kr/guide/main.do",
        "https://127.0.0.1/guide/main.do",
        "https://[::1]/guide/main.do",
        "https://10.0.0.1/guide/main.do",
        "https://169.254.169.254/guide/main.do",
        "https://attacker.invalid/guide/main.do",
        "https://engopendart.fss.or.kr.attacker.invalid/guide/main.do",
        "https://engopendart.fss.or.kr@attacker.invalid/guide/main.do",
        "https://user:password@engopendart.fss.or.kr/guide/main.do",
        "https://engopendart.fss.or.kr:8443/guide/main.do",
        "https://engopendart.fss.or.kr/engapi/company.json",
        "https://engopendart.fss.or.kr/guide/../internal",
        "https://engopendart.fss.or.kr/guide/detail.do#fragment",
        "//engopendart.fss.or.kr/guide/main.do",
        "file:///etc/passwd",
    ],
)
@pytest.mark.parametrize("cached", [False, True])
def test_unexpected_guide_url_is_rejected_before_io(tmp_path, guide_http, url, cached):
    _, calls, _ = guide_http
    if cached:
        (tmp_path / "DE001.html").write_text("cached HTML", encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected guide URL"):
        read_guide("DE001", url, tmp_path)
    assert calls == []


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize(
    "location",
    [
        "http://169.254.169.254/latest/meta-data/",
        "https://127.0.0.1/internal",
        "https://attacker.invalid/guide/detail.do",
        "//attacker.invalid/guide/detail.do",
        "/guide/detail.do?apiId=AE00001",
    ],
)
def test_redirect_is_rejected_without_requesting_destination(
    tmp_path, guide_http, status, location
):
    reply, calls, streams = guide_http
    reply.update(status=status, location=location)
    url = BASE + "/guide/main.do?apiGrpCd=DE001"
    with pytest.raises(HTTPError) as caught:
        read_guide("DE001", url, tmp_path)
    try:
        assert caught.value.code == status
        assert calls == [(url, 60)]
        assert not (tmp_path / "DE001.html").exists()
    finally:
        caught.value.close()
    assert streams[0].closed


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "../outside",
        "../../outside",
        "/etc/passwd",
        r"..\outside",
        "AE00001/../../outside",
        "AE00001%2f..",
        "AE00001\0",
        "DE007",
        "AE0000",
        "AE000001",
        "AE\uff11\uff12\uff13\uff14\uff15",
        "DE001.html",
    ],
)
@pytest.mark.parametrize("cached", [False, True])
def test_invalid_guide_identifiers_are_rejected_before_io(tmp_path, guide_http, name, cached):
    _, calls, _ = guide_http
    cache = tmp_path / "cache"
    cache.mkdir()
    (tmp_path / "outside.html").write_text("private", encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected guide identifier"):
        read_guide(name, BASE + "/guide/main.do", cache if cached else None)
    assert calls == []
    assert list(cache.iterdir()) == []


@pytest.mark.parametrize("exists", [False, True])
def test_cache_symlink_cannot_read_or_write_outside_directory(tmp_path, guide_http, exists):
    _, calls, _ = guide_http
    cache = tmp_path / "cache"
    cache.mkdir()
    outside = tmp_path / "outside.html"
    if exists:
        outside.write_text("private", encoding="utf-8")
    (cache / "DE001.html").symlink_to(outside)
    with pytest.raises(ValueError, match="Guide cache path must stay within its directory"):
        read_guide("DE001", BASE + "/guide/main.do", cache)
    assert calls == []
    if exists:
        assert outside.read_text(encoding="utf-8") == "private"
    else:
        assert not outside.exists()
