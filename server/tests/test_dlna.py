"""Smart TVs (DLNA): the browse API and the UPnP server in the PC app."""
from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

from app.services import jobs
from conftest import make_rich_video, make_video

sys.path.insert(0, str(Path(__file__).parents[2] / "sync-client"))

from zirahive_sync.dlna import DlnaServer, media_base  # noqa: E402

DIDL_NS = {"d": "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/", "dc": "http://purl.org/dc/elements/1.1/",
           "upnp": "urn:schemas-upnp-org:metadata-1-0/upnp/"}


async def _library(client, tmp_path):
    make_rich_video(tmp_path / "movies" / "Dhaka Nights (2024)")
    for s, e in ((1, 1), (1, 2), (2, 1)):
        make_video(tmp_path / "shows" / "Bhai Bhai" / f"Season {s}" / f"Bhai Bhai S{s:02d}E{e:02d}.mp4", seconds=1)
    for name, kind in (("Movies", "movies"), ("Series", "shows")):
        r = await client.post("/api/libraries", json={"name": name, "path": str(tmp_path / name.lower().replace("series", "shows")),
                                                      "kind": kind})
        assert r.status_code == 201, r.text
    await jobs.drain_local()


async def test_browse_api_for_tvs(client, admin, tmp_path):
    await _library(client, tmp_path)
    root = (await client.get("/api/dlna/browse")).json()
    names = {f["title"]: f["id"] for f in root["folders"]}
    assert set(names) == {"Movies", "Series"}

    movies = (await client.get("/api/dlna/browse", params={"id": names["Movies"]})).json()
    film = movies["items"][0]
    assert film["title"] == "Dhaka Nights" and film["mime"] == "video/x-matroska" and film["duration"] > 19
    assert film["path"].startswith("/api/media/") and "/stream?token=" in film["path"]

    shows = (await client.get("/api/dlna/browse", params={"id": names["Series"]})).json()
    series = shows["folders"][0]
    assert series["title"] == "Bhai Bhai" and not shows["items"]
    seasons = (await client.get("/api/dlna/browse", params={"id": series["id"]})).json()
    assert [(f["title"], f["count"]) for f in seasons["folders"]] == [("Season 1", 2), ("Season 2", 1)]
    s1 = (await client.get("/api/dlna/browse", params={"id": seasons["folders"][0]["id"]})).json()
    assert [i["title"] for i in s1["items"]] == ["Episode 1", "Episode 2"] and s1["parent"] == series["id"]

    # the TV plays the link without signing in, and gets the DLNA answers it asks for
    client.headers.pop("Authorization")
    client.cookies.clear()
    head = await client.head(film["path"], headers={"getcontentFeatures.dlna.org": "1"})
    assert head.status_code == 200 and head.headers["contentfeatures.dlna.org"].startswith("DLNA.ORG_OP=01")
    assert int(head.headers["content-length"]) == film["size"] and head.content == b""
    part = await client.get(film["path"], headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100
    assert (await client.get("/api/dlna/browse")).status_code == 401


def test_media_address_for_the_tv():
    assert media_base("http://localhost:8080", None, "192.168.0.7") == "http://192.168.0.7:8080"
    assert media_base("http://localhost:8080", "http://192.168.0.9:8080/", "192.168.0.7") == "http://192.168.0.9:8080"
    assert media_base("http://192.168.0.9:8080", None, "192.168.0.7") == "http://192.168.0.9:8080"


def _soap_browse(port: int, object_id: str, flag: str = "BrowseDirectChildren") -> ET.Element:
    body = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
            '<u:Browse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">'
            f"<ObjectID>{object_id}</ObjectID><BrowseFlag>{flag}</BrowseFlag><Filter>*</Filter>"
            "<StartingIndex>0</StartingIndex><RequestedCount>0</RequestedCount><SortCriteria></SortCriteria>"
            "</u:Browse></s:Body></s:Envelope>")
    r = httpx.post(f"http://127.0.0.1:{port}/ctl/ContentDirectory", content=body, headers={
        "SOAPACTION": '"urn:schemas-upnp-org:service:ContentDirectory:1#Browse"', "Content-Type": 'text/xml; charset="utf-8"'})
    assert r.status_code == 200, r.text
    result = next(el.text for el in ET.fromstring(r.content).iter() if el.tag == "Result")
    return ET.fromstring(result)


async def test_tv_finds_and_browses_zirahive(client, admin, tmp_path, monkeypatch):
    await _library(client, tmp_path)
    monkeypatch.setenv("ZIRAHIVE_LAN_URL", "http://192.168.1.20:8080")
    from app.config import get_settings
    get_settings.cache_clear()
    loop = asyncio.get_running_loop()

    def fetch(folder_id: str) -> dict:  # what dlna_fetcher does, against the in-process server
        r = asyncio.run_coroutine_threadsafe(client.get("/api/dlna/browse", params={"id": folder_id}), loop).result(30)
        r.raise_for_status()
        return r.json()

    tv = DlnaServer("ZiraHive (test)", "1234-abcd", "http://localhost:8080", fetch, http_port=0, ssdp_port=0,
                    ip="127.0.0.1")
    tv.start()
    try:
        # a TV searching for media servers gets an answer pointing at the description
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(3)
        s.sendto(b'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 1\r\n'
                 b"ST: urn:schemas-upnp-org:device:MediaServer:1\r\n\r\n", ("127.0.0.1", tv.ssdp.getsockname()[1]))
        reply = (await asyncio.to_thread(s.recvfrom, 4096))[0].decode()
        s.close()
        assert reply.startswith("HTTP/1.1 200 OK") and f"LOCATION: {tv.location}" in reply
        desc = (await asyncio.to_thread(httpx.get, tv.location)).text
        assert "<friendlyName>ZiraHive (test)</friendlyName>" in desc and "ContentDirectory" in desc

        root = await asyncio.to_thread(_soap_browse, tv.http_port, "0")
        folders = {c.find("dc:title", DIDL_NS).text: c.get("id") for c in root.findall("d:container", DIDL_NS)}
        assert set(folders) == {"Movies", "Series"}
        movies = await asyncio.to_thread(_soap_browse, tv.http_port, folders["Movies"])
        item = movies.find("d:item", DIDL_NS)
        assert item.find("dc:title", DIDL_NS).text == "Dhaka Nights"
        assert item.find("upnp:class", DIDL_NS).text == "object.item.videoItem.movie"
        res = item.find("d:res", DIDL_NS)
        assert res.text.startswith("http://192.168.1.20:8080/api/media/") and "token=" in res.text
        assert res.get("protocolInfo").startswith("http-get:*:video/x-matroska:DLNA.ORG_OP=01")
        assert res.get("duration").startswith("0:00:2")
        meta = await asyncio.to_thread(_soap_browse, tv.http_port, item.get("id"), "BrowseMetadata")
        assert meta.find("d:item", DIDL_NS).get("parentID") == folders["Movies"]
    finally:
        tv.stop()
