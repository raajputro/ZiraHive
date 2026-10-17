"""Shows ZiraHive on smart TVs at home (DLNA / UPnP media server).

TVs look for media servers with SSDP (multicast on the home network), then browse folders over
HTTP + SOAP. This module does both, and answers each browse by asking ZiraHive
(GET /api/dlna/browse). The videos and songs themselves go straight from ZiraHive to the TV,
with links that each play one title for 12 hours.

It runs inside the ZiraHive app on a Windows PC (Docker Desktop can't use multicast), or with
`zirahive-sync tv` on any computer at home.
"""
from __future__ import annotations

import logging
import socket
import struct
import threading
import time
import uuid
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

log = logging.getLogger("zirahive_sync.dlna")

SSDP_ADDR, SSDP_PORT = "239.255.255.250", 1900
MAX_AGE = 1800
DEVICE = "urn:schemas-upnp-org:device:MediaServer:1"
CDS = "urn:schemas-upnp-org:service:ContentDirectory:1"
CMS = "urn:schemas-upnp-org:service:ConnectionManager:1"
SERVER = "Windows/10 UPnP/1.0 ZiraHive/1.0"
DLNA_FLAGS = "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000"

Fetch = Callable[[str], dict]  # folder id -> the /api/dlna/browse answer


def local_ip() -> str:
    """This computer's address on the home network (the one its internet traffic leaves by)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))  # no packet is sent; it only picks the route
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def media_base(server: str, lan_url: str | None, ip: str) -> str:
    """Where the TV fetches videos: ZiraHive's home address if it has one set, else the address
    this app uses, with localhost swapped for this PC's address (the TV isn't this PC)."""
    if lan_url:
        return lan_url.rstrip("/")
    parts = urlsplit(server.rstrip("/"))
    host = parts.hostname or ""
    if host in ("localhost", "127.0.0.1", "::1") or host.startswith("127."):
        netloc = ip + (f":{parts.port}" if parts.port else "")
        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    return server.rstrip("/")


def _duration(sec: float | None) -> str | None:
    if not sec:
        return None
    h, rem = divmod(float(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:06.3f}"


def didl(entries: list[str]) -> str:
    return ('<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" xmlns:dlna="urn:schemas-dlna-org:metadata-1-0/">'
            + "".join(entries) + "</DIDL-Lite>")


def folder_xml(fid: str, parent: str, title: str, count: int | None = None) -> str:
    child = f' childCount="{count}"' if count is not None else ""
    return (f'<container id="{escape(fid)}" parentID="{escape(parent)}" restricted="1" searchable="0"{child}>'
            f"<dc:title>{escape(title)}</dc:title><upnp:class>object.container.storageFolder</upnp:class></container>")


def item_xml(it: dict, parent: str, base: str) -> str:
    video = it["kind"] == "video"
    cls = "object.item.videoItem.movie" if video else "object.item.audioItem.musicTrack"
    attrs = []
    if it.get("size"):
        attrs.append(f'size="{int(it["size"])}"')
    if d := _duration(it.get("duration")):
        attrs.append(f'duration="{d}"')
    res = (f'<res protocolInfo="http-get:*:{escape(it["mime"])}:{DLNA_FLAGS}" {" ".join(attrs)}>'
           f'{escape(base + it["path"])}</res>')
    extra = ""
    if it.get("art"):
        extra += f'<upnp:albumArtURI dlna:profileID="JPEG_TN">{escape(base + it["art"])}</upnp:albumArtURI>'
    if it.get("artist"):
        extra += f"<upnp:artist>{escape(it['artist'])}</upnp:artist><dc:creator>{escape(it['artist'])}</dc:creator>"
    if it.get("album"):
        extra += f"<upnp:album>{escape(it['album'])}</upnp:album>"
    if it.get("track_no"):
        extra += f"<upnp:originalTrackNumber>{int(it['track_no'])}</upnp:originalTrackNumber>"
    if it.get("year"):
        extra += f"<dc:date>{int(it['year'])}-01-01</dc:date>"
    return (f'<item id="{escape(it["id"])}" parentID="{escape(parent)}" restricted="1">'
            f"<dc:title>{escape(it['title'])}</dc:title><upnp:class>{cls}</upnp:class>{extra}{res}</item>")


def _soap(action: str, service: str, body: str) -> bytes:
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{action}Response xmlns:u="{service}">{body}</u:{action}Response></s:Body></s:Envelope>').encode()


def _soap_fault(code: int, text: str) -> bytes:
    return ('<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><s:Fault>'
            '<faultcode>s:Client</faultcode><faultstring>UPnPError</faultstring><detail>'
            f'<UPnPError xmlns="urn:schemas-upnp-org:control-1-0"><errorCode>{code}</errorCode>'
            f'<errorDescription>{escape(text)}</errorDescription></UPnPError></detail></s:Fault></s:Body></s:Envelope>').encode()


def _scpd(actions: str, variables: str) -> bytes:
    return ('<?xml version="1.0"?><scpd xmlns="urn:schemas-upnp-org:service-1-0"><specVersion><major>1</major>'
            f"<minor>0</minor></specVersion><actionList>{actions}</actionList>"
            f"<serviceStateTable>{variables}</serviceStateTable></scpd>").encode()


def _action(name: str, args: list[tuple[str, str, str]]) -> str:
    a = "".join(f"<argument><name>{n}</name><direction>{d}</direction><relatedStateVariable>{v}</relatedStateVariable>"
                f"</argument>" for n, d, v in args)
    return f"<action><name>{name}</name><argumentList>{a}</argumentList></action>"


def _var(name: str, kind: str, events: bool = False) -> str:
    return f'<stateVariable sendEvents="{"yes" if events else "no"}"><name>{name}</name><dataType>{kind}</dataType></stateVariable>'


CDS_SCPD = _scpd(
    _action("Browse", [("ObjectID", "in", "A_ARG_TYPE_ObjectID"), ("BrowseFlag", "in", "A_ARG_TYPE_BrowseFlag"),
                       ("Filter", "in", "A_ARG_TYPE_Filter"), ("StartingIndex", "in", "A_ARG_TYPE_Index"),
                       ("RequestedCount", "in", "A_ARG_TYPE_Count"), ("SortCriteria", "in", "A_ARG_TYPE_SortCriteria"),
                       ("Result", "out", "A_ARG_TYPE_Result"), ("NumberReturned", "out", "A_ARG_TYPE_Count"),
                       ("TotalMatches", "out", "A_ARG_TYPE_Count"), ("UpdateID", "out", "A_ARG_TYPE_UpdateID")])
    + _action("GetSearchCapabilities", [("SearchCaps", "out", "SearchCapabilities")])
    + _action("GetSortCapabilities", [("SortCaps", "out", "SortCapabilities")])
    + _action("GetSystemUpdateID", [("Id", "out", "SystemUpdateID")]),
    "".join(_var(n, t) for n, t in [("A_ARG_TYPE_ObjectID", "string"), ("A_ARG_TYPE_BrowseFlag", "string"),
                                    ("A_ARG_TYPE_Filter", "string"), ("A_ARG_TYPE_Index", "ui4"),
                                    ("A_ARG_TYPE_Count", "ui4"), ("A_ARG_TYPE_SortCriteria", "string"),
                                    ("A_ARG_TYPE_Result", "string"), ("A_ARG_TYPE_UpdateID", "ui4"),
                                    ("SearchCapabilities", "string"), ("SortCapabilities", "string")])
    + _var("SystemUpdateID", "ui4", events=True))

CMS_SCPD = _scpd(
    _action("GetProtocolInfo", [("Source", "out", "SourceProtocolInfo"), ("Sink", "out", "SinkProtocolInfo")])
    + _action("GetCurrentConnectionIDs", [("ConnectionIDs", "out", "CurrentConnectionIDs")]),
    _var("SourceProtocolInfo", "string", True) + _var("SinkProtocolInfo", "string", True)
    + _var("CurrentConnectionIDs", "string", True))

PROTOCOLS = ",".join(f"http-get:*:{m}:*" for m in (
    "video/mp4", "video/x-matroska", "video/x-msvideo", "video/quicktime", "video/webm", "video/mp2t", "video/mpeg",
    "video/x-ms-wmv", "audio/mpeg", "audio/mp4", "audio/flac", "audio/ogg", "audio/wav", "audio/x-ms-wma", "image/webp"))


class DlnaServer:
    def __init__(self, name: str, udn: str, server_url: str, fetch: Fetch, http_port: int = 8201,
                 ssdp_port: int = SSDP_PORT, ip: str | None = None):
        self.name, self.udn, self.server_url, self.fetch = name, udn, server_url, fetch
        self.ip = ip or local_ip()
        self.ssdp_port = ssdp_port
        self.stopping = threading.Event()
        self._cache: dict[str, tuple[float, dict]] = {}
        self._parents: dict[str, str] = {"0": "-1"}
        self.update_id = int(time.time()) % 1_000_000
        try:
            self.httpd = ThreadingHTTPServer(("", http_port), self._handler())
        except OSError:  # the port is taken: any free one
            self.httpd = ThreadingHTTPServer(("", 0), self._handler())
        self.httpd.daemon_threads = True
        self.http_port = self.httpd.server_address[1]
        self.ssdp: socket.socket | None = None

    # ---------------------------------------------------------------- lifecycle
    @property
    def location(self) -> str:
        return f"http://{self.ip}:{self.http_port}/description.xml"

    def start(self) -> None:
        threading.Thread(target=self.httpd.serve_forever, name="dlna-http", daemon=True).start()
        self.ssdp = self._ssdp_socket()
        threading.Thread(target=self._ssdp_loop, name="dlna-ssdp", daemon=True).start()
        threading.Thread(target=self._announce_loop, name="dlna-notify", daemon=True).start()
        log.info("Showing ZiraHive to TVs at %s", self.location)

    def stop(self) -> None:
        self.stopping.set()
        try:
            self._notify("ssdp:byebye")
        except OSError:
            pass
        self.httpd.shutdown()
        self.httpd.server_close()
        if self.ssdp:
            self.ssdp.close()

    # ---------------------------------------------------------------- SSDP
    def _ssdp_socket(self) -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", self.ssdp_port))
        try:
            mreq = struct.pack("4s4s", socket.inet_aton(SSDP_ADDR), socket.inet_aton(self.ip))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(self.ip))
        except OSError as exc:  # no multicast here (e.g. tests): answers to direct searches still work
            log.warning("multicast unavailable: %s", exc)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s.settimeout(1.0)
        return s

    def _targets(self) -> list[tuple[str, str]]:
        """(NT / ST, USN) pairs this device announces."""
        u = f"uuid:{self.udn}"
        return [("upnp:rootdevice", f"{u}::upnp:rootdevice"), (u, u), (DEVICE, f"{u}::{DEVICE}"),
                (CDS, f"{u}::{CDS}"), (CMS, f"{u}::{CMS}")]

    def _notify(self, nts: str) -> None:
        if not self.ssdp:
            return
        for nt, usn in self._targets():
            msg = (f"NOTIFY * HTTP/1.1\r\nHOST: {SSDP_ADDR}:{SSDP_PORT}\r\nCACHE-CONTROL: max-age={MAX_AGE}\r\n"
                   f"LOCATION: {self.location}\r\nNT: {nt}\r\nNTS: {nts}\r\nSERVER: {SERVER}\r\nUSN: {usn}\r\n\r\n")
            self.ssdp.sendto(msg.encode(), (SSDP_ADDR, SSDP_PORT))

    def _announce_loop(self) -> None:
        while not self.stopping.is_set():
            try:
                self._notify("ssdp:alive")
            except OSError as exc:
                log.debug("notify failed: %s", exc)
            self.stopping.wait(MAX_AGE // 3)

    def search_replies(self, st: str) -> list[str]:
        out = []
        for nt, usn in self._targets():
            if st in ("ssdp:all", nt):
                out.append(f"HTTP/1.1 200 OK\r\nCACHE-CONTROL: max-age={MAX_AGE}\r\nDATE: {formatdate(usegmt=True)}\r\n"
                           f"EXT:\r\nLOCATION: {self.location}\r\nSERVER: {SERVER}\r\nST: {nt}\r\nUSN: {usn}\r\n"
                           "Content-Length: 0\r\n\r\n")
        return out

    def _ssdp_loop(self) -> None:
        while not self.stopping.is_set():
            try:
                data, addr = self.ssdp.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            text = data.decode(errors="replace")
            if not text.startswith("M-SEARCH"):
                continue
            headers = {k.strip().lower(): v.strip() for k, _, v in
                       (ln.partition(":") for ln in text.split("\r\n")[1:] if ":" in ln)}
            if headers.get("man", "").strip('"') != "ssdp:discover":
                continue
            for reply in self.search_replies(headers.get("st", "")):
                try:
                    self.ssdp.sendto(reply.encode(), addr)
                except OSError:
                    pass

    # ---------------------------------------------------------------- content
    def description(self) -> bytes:
        return ('<?xml version="1.0"?><root xmlns="urn:schemas-upnp-org:device-1-0" '
                'xmlns:dlna="urn:schemas-dlna-org:device-1-0"><specVersion><major>1</major><minor>0</minor></specVersion>'
                f"<device><deviceType>{DEVICE}</deviceType><dlna:X_DLNADOC>DMS-1.50</dlna:X_DLNADOC>"
                f"<friendlyName>{escape(self.name)}</friendlyName><manufacturer>ZiraHive</manufacturer>"
                "<manufacturerURL>https://github.com/</manufacturerURL><modelName>ZiraHive</modelName>"
                f"<modelNumber>1</modelNumber><UDN>uuid:{self.udn}</UDN>"
                "<iconList><icon><mimetype>image/png</mimetype><width>120</width><height>120</height><depth>24</depth>"
                "<url>/icon.png</url></icon></iconList><serviceList>"
                f"<service><serviceType>{CDS}</serviceType><serviceId>urn:upnp-org:serviceId:ContentDirectory</serviceId>"
                "<SCPDURL>/ContentDirectory.xml</SCPDURL><controlURL>/ctl/ContentDirectory</controlURL>"
                "<eventSubURL>/evt/ContentDirectory</eventSubURL></service>"
                f"<service><serviceType>{CMS}</serviceType><serviceId>urn:upnp-org:serviceId:ConnectionManager</serviceId>"
                "<SCPDURL>/ConnectionManager.xml</SCPDURL><controlURL>/ctl/ConnectionManager</controlURL>"
                "<eventSubURL>/evt/ConnectionManager</eventSubURL></service>"
                f"</serviceList><presentationURL>{escape(self.server_url)}</presentationURL></device></root>").encode()

    def folder(self, fid: str) -> dict:
        hit = self._cache.get(fid)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
        data = self.fetch(fid)
        self._cache[fid] = (time.time(), data)
        for f in data.get("folders", []):
            self._parents[f["id"]] = fid
        for it in data.get("items", []):
            self._parents[it["id"]] = fid
        return data

    def browse(self, object_id: str, flag: str, start: int, count: int) -> tuple[str, int, int]:
        """(DIDL-Lite, number returned, total)."""
        if flag == "BrowseMetadata":
            if object_id == "0":
                root = self.folder("0")
                return didl([folder_xml("0", "-1", self.name, len(root["folders"]) + len(root["items"]))]), 1, 1
            parent = self._parents.get(object_id)
            if parent is None:
                raise KeyError(object_id)
            siblings = self.folder(parent)
            for f in siblings.get("folders", []):
                if f["id"] == object_id:
                    return didl([folder_xml(f["id"], parent, f["title"], f.get("count"))]), 1, 1
            for it in siblings.get("items", []):
                if it["id"] == object_id:
                    return didl([item_xml(it, parent, self._base(siblings))]), 1, 1
            raise KeyError(object_id)
        data = self.folder(object_id)
        base = self._base(data)
        entries = ([folder_xml(f["id"], object_id, f["title"], f.get("count")) for f in data.get("folders", [])]
                   + [item_xml(it, object_id, base) for it in data.get("items", [])])
        total = len(entries)
        page = entries[start:start + count] if count else entries[start:]
        return didl(page), len(page), total

    def _base(self, data: dict) -> str:
        return media_base(self.server_url, data.get("lan_url"), self.ip)

    def control(self, path: str, action: str, body: bytes) -> tuple[int, bytes]:
        if path.endswith("ConnectionManager"):
            if action == "GetProtocolInfo":
                return 200, _soap(action, CMS, f"<Source>{PROTOCOLS}</Source><Sink></Sink>")
            if action == "GetCurrentConnectionIDs":
                return 200, _soap(action, CMS, "<ConnectionIDs>0</ConnectionIDs>")
            return 500, _soap_fault(401, "Invalid Action")
        if action == "GetSearchCapabilities":
            return 200, _soap(action, CDS, "<SearchCaps></SearchCaps>")
        if action == "GetSortCapabilities":
            return 200, _soap(action, CDS, "<SortCaps></SortCaps>")
        if action == "GetSystemUpdateID":
            return 200, _soap(action, CDS, f"<Id>{self.update_id}</Id>")
        if action != "Browse":
            return 500, _soap_fault(401, "Invalid Action")
        args = {}
        for el in ET.fromstring(body).iter():
            tag = el.tag.rsplit("}", 1)[-1]
            if tag in ("ObjectID", "BrowseFlag", "StartingIndex", "RequestedCount"):
                args[tag] = (el.text or "").strip()
        try:
            result, n, total = self.browse(args.get("ObjectID", "0"), args.get("BrowseFlag", "BrowseDirectChildren"),
                                           int(args.get("StartingIndex") or 0), int(args.get("RequestedCount") or 0))
        except KeyError:
            return 500, _soap_fault(701, "No such object")
        except Exception as exc:  # ZiraHive unreachable or signed out
            log.warning("browse %s failed: %s", args.get("ObjectID"), exc)
            return 500, _soap_fault(720, "Cannot process the request")
        return 200, _soap("Browse", CDS, f"<Result>{escape(result)}</Result><NumberReturned>{n}</NumberReturned>"
                                         f"<TotalMatches>{total}</TotalMatches><UpdateID>{self.update_id}</UpdateID>")

    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = SERVER

            def log_message(self, fmt, *args):  # noqa: A002
                log.debug("%s " + fmt, self.client_address[0], *args)

            def _send(self, status: int, body: bytes, ctype: str = 'text/xml; charset="utf-8"', extra=None) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("EXT", "")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                path = self.path.split("?")[0]
                if path == "/description.xml":
                    self._send(200, server.description())
                elif path == "/ContentDirectory.xml":
                    self._send(200, CDS_SCPD)
                elif path == "/ConnectionManager.xml":
                    self._send(200, CMS_SCPD)
                elif path == "/icon.png":
                    self._send(200, _icon(), "image/png")
                else:
                    self._send(404, b"", "text/plain")

            do_HEAD = do_GET  # noqa: N815

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                soap_action = (self.headers.get("SOAPACTION") or "").strip('"')
                action = soap_action.rsplit("#", 1)[-1]
                try:
                    status, out = server.control(self.path, action, body)
                except ET.ParseError:
                    status, out = 500, _soap_fault(402, "Invalid Args")
                self._send(status, out)

            def do_SUBSCRIBE(self):  # noqa: N802
                # TVs subscribe to change events; nothing changes that they need to hear about
                self._send(200, b"", "text/plain", {"SID": f"uuid:{uuid.uuid4()}", "TIMEOUT": "Second-1800"})

            def do_UNSUBSCRIBE(self):  # noqa: N802
                self._send(200, b"", "text/plain")

        return Handler


_ICON: bytes | None = None


def _icon() -> bytes:
    """The ZiraHive mark, drawn once (Pillow is already needed for the tray icon)."""
    global _ICON
    if _ICON is None:
        import io

        from PIL import Image

        im = Image.new("RGB", (480, 480), (32, 42, 68))
        hive(im, (201, 166, 107), (32, 42, 68), radius=160)
        im = im.resize((120, 120), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        _ICON = buf.getvalue()
    return _ICON


def hive(im, fg, bg, radius: float) -> None:
    """Draws the ZiraHive mark (a honeycomb cell holding a smaller one) in the middle of `im`."""
    import math

    from PIL import ImageDraw

    d = ImageDraw.Draw(im)
    cx, cy = im.width / 2, im.height / 2

    def cell(r):
        return [(cx + r * math.cos(math.radians(90 + 60 * i)), cy + r * math.sin(math.radians(90 + 60 * i)))
                for i in range(6)]
    d.polygon(cell(radius), fill=fg)
    d.polygon(cell(radius * 0.78), fill=bg)
    d.polygon(cell(radius * 0.36), fill=fg)
