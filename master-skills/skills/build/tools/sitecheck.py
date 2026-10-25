#!/usr/bin/env python3
"""sitecheck.py: crawl a local folder or a live site and report what is broken.

Part of the BUILD master skill (github.com/Jakeschincariol/master-skills).
Python 3 standard library only. Works on macOS and Linux.

It reads the HTML your server actually sends (it does not run JavaScript) and
checks every same-origin page it can reach for:
  broken links, missing #anchors, broken images/scripts/styles/fonts/media,
  missing <title>, viewport, description, lang, doctype, charset,
  images without alt or width/height, heavy or oversized images,
  mixed content, duplicate ids, unlabeled form fields, unnamed icon
  links/buttons, placeholder links, lorem ipsum, leftover localhost URLs,
  noindex, favicon and social preview image.

Examples:
  python3 sitecheck.py site/                         # serves the folder itself
  python3 sitecheck.py http://127.0.0.1:8000/ --depth 5
  python3 sitecheck.py https://example.com --external --report qa/sitecheck.json
  python3 sitecheck.py site/ --json > report.json
  python3 sitecheck.py --list-rules

Exit codes: 0 no errors (warnings allowed unless --strict), 1 problems found,
2 could not run (bad arguments, start page unreachable or not HTML).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import http.client
import json
import os
import re
import socket
import ssl
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict, namedtuple
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Dict, List, Optional

VERSION = "1.0.0"
USER_AGENT = "sitecheck/%s (+https://github.com/Jakeschincariol/master-skills)" % VERSION
PAGE_CAP = 5 * 1024 * 1024      # bytes read from an HTML page
CSS_CAP = 4 * 1024 * 1024       # bytes read from a stylesheet
IMAGE_CAP = 32 * 1024 * 1024    # bytes read from an image (to measure weight)

# Rule id -> (severity, what it means, how to fix). Errors first; this order is
# also the report order.
RULES = OrderedDict([
    ("broken-link", ("error", "Link to a page that does not load",
                     "Fix the href or create the page. Paths are case-sensitive on most hosts.")),
    ("broken-anchor", ("error", "Link to an #id that does not exist on the target page",
                       "Add the id to the target section or correct the href.")),
    ("broken-asset", ("error", "Image, script, stylesheet, font or media file that does not load",
                      "Fix the path (case-sensitive on most hosts) or add the missing file.")),
    ("external-link", ("error", "External link is dead (404, 410 or the domain does not resolve)",
                       "Update or remove the link.")),
    ("external-asset", ("error", "External image, script, stylesheet or font does not load",
                        "Fix the URL or self-host the file.")),
    ("missing-title", ("error", "Page has no <title>",
                       "Add a specific <title> in <head> (what the page is, then the brand).")),
    ("missing-viewport", ("error", "No viewport meta tag, so phones show the desktop layout zoomed out",
                          'Add <meta name="viewport" content="width=device-width, initial-scale=1">.')),
    ("zoom-disabled", ("error", "Viewport blocks pinch zoom (user-scalable=no or maximum-scale below 2)",
                       "Remove user-scalable=no and maximum-scale; people with low vision need zoom.")),
    ("missing-lang", ("error", "<html> has no lang attribute",
                      'Add the page language, for example <html lang="en">.')),
    ("missing-doctype", ("error", "No <!doctype html>, so the page renders in quirks mode",
                         "Make <!doctype html> the very first line of the file.")),
    ("img-missing-alt", ("error", "Image without alt text",
                         'Add alt="what the image shows". Use alt="" only for purely decorative images.')),
    ("unlabeled-field", ("error", "Form field without a label",
                         'Add <label for="field-id">, wrap the field in <label>, or add aria-label. '
                         "A placeholder is not a label.")),
    ("unnamed-link", ("error", "Link with no text or accessible name (usually an icon link)",
                      'Add visible text or aria-label="where it goes".')),
    ("unnamed-button", ("error", "Button with no text or accessible name (usually an icon button)",
                        'Add visible text or aria-label="what it does".')),
    ("duplicate-id", ("error", "The same id is used more than once on a page",
                      "Make every id unique; anchors, labels and scripts pick the wrong element otherwise.")),
    ("mixed-content", ("error", "HTTPS page loads a resource or submits a form over plain HTTP",
                       "Use https:// (or a relative URL) for every resource and form action.")),
    ("local-url", ("error", "Points at localhost or a file:// path that visitors cannot reach",
                   "Use a relative URL or the real production URL.")),
    ("missing-description", ("warn", "No meta description",
                             'Add <meta name="description" content="one or two plain sentences">; '
                             "search results and link previews use it.")),
    ("missing-charset", ("warn", "No character encoding declared",
                         'Add <meta charset="utf-8"> as the first element in <head>.')),
    ("missing-h1", ("warn", "Page has no <h1>",
                    "Give every page one clear <h1> that says what the page is.")),
    ("img-missing-size", ("warn", "Image without width and height, so the layout jumps while it loads",
                          "Add width and height attributes with the image's real pixel size; "
                          "CSS can still scale it (img { height: auto; }).")),
    ("image-heavy", ("warn", "Image file is heavy",
                     "Resize to about 2x its displayed width and compress (WebP or AVIF, "
                     "or JPEG quality 75 to 85).")),
    ("image-oversized", ("warn", "Image has far more pixels than the size it is displayed at",
                         "Export it at about 2x the width attribute, or add srcset with smaller versions.")),
    ("placeholder-link", ("warn", 'Link goes nowhere (href="#", empty href or javascript:)',
                          "Point it at a real page or section, or use a <button> if it runs code.")),
    ("lorem-ipsum", ("warn", "Placeholder lorem ipsum text left on the page",
                     "Replace it with the owner's real words.")),
    ("noindex", ("warn", "Search engines are told not to index this page",
                 "Remove robots noindex before launch unless the page should stay out of search.")),
    ("missing-favicon", ("warn", "No favicon, so browsers log a 404 for /favicon.ico",
                         'Add <link rel="icon" href="/favicon.svg"> (or .png / .ico).')),
    ("missing-og-image", ("warn", "No og:image, so shared links show no preview image",
                          'Add <meta property="og:image" content="https://your-domain/share.png"> '
                          "(1200x630, absolute URL).")),
    ("relative-og-image", ("warn", "og:image is a relative URL; most link previews ignore it",
                           "Use an absolute https:// URL for og:image.")),
    ("external-unverified", ("warn", "External URL could not be verified (blocked, rate limited, "
                                     "server error or timed out)",
                             "Open it in a browser and confirm it works.")),
])

LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
FONT_EXT = {".woff2", ".woff", ".ttf", ".otf", ".eot"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".ico", ".bmp"}
MEDIA_EXT = {".mp4", ".m4v", ".webm", ".mov", ".mp3", ".m4a", ".wav", ".ogg", ".vtt"}
PAGE_EXT = {"", ".html", ".htm", ".php", ".asp", ".aspx", ".jsp", ".shtml"}
_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")
_WS_RE = re.compile(r"[\t\n\r]")
_LOREM_RE = re.compile(r"\blorem\s+ipsum\b", re.I)


# --------------------------------------------------------------------------
# URL helpers
# --------------------------------------------------------------------------
def is_local_host(host: Optional[str]) -> bool:
    h = (host or "").lower().strip("[]")
    return (h in LOCAL_HOSTS or h.startswith("127.") or h.endswith(".localhost")
            or h.endswith(".local") or h.endswith(".test"))


def normalize(url: str) -> Optional[str]:
    """Canonical form used for de-duplication: lowercase scheme and host, no
    default port, percent-encoded path, no fragment. None if the URL is invalid."""
    try:
        p = urllib.parse.urlsplit(url)
        scheme = p.scheme.lower()
        host = p.hostname or ""
        port = p.port
    except ValueError:
        return None
    if scheme not in ("http", "https") or not host:
        return None
    try:
        host.encode("ascii")
    except UnicodeEncodeError:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            return None
    netloc = "[%s]" % host if ":" in host else host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc += ":%d" % port
    path = urllib.parse.quote(p.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = urllib.parse.quote(p.query, safe="=&%/?:@!$'()*+,;-._~")
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def origin_of(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    return "%s://%s" % (p.scheme, p.netloc)


def resolve(raw: Optional[str], base: str):
    """Resolve an attribute URL. Returns (kind, url, fragment).

    kind: http | empty | js | file | skip (mailto:, tel:, data:, ...) | invalid
    """
    if raw is None:
        return "empty", "", None
    u = _WS_RE.sub("", raw).strip()
    if not u:
        return "empty", "", None
    m = _SCHEME_RE.match(u)
    if m:
        scheme = m.group(1).lower()
        if scheme == "javascript":
            return "js", u, None
        if scheme == "file":
            return "file", u, None
        if scheme not in ("http", "https"):
            return "skip", u, None
    absolute = urllib.parse.urljoin(base, u)
    absolute, frag = urllib.parse.urldefrag(absolute)
    has_frag = "#" in u
    norm = normalize(absolute)
    if norm is None:
        return "invalid", u, None
    return "http", norm, (frag if has_frag else None)


def display(url: str, origins) -> str:
    """Short form for reports: path for same-origin URLs, full URL otherwise."""
    if url and origin_of(url) in origins:
        p = urllib.parse.urlsplit(url)
        return ((p.path or "/") + ("?" + p.query if p.query else "")
                + ("#" + p.fragment if p.fragment else ""))
    return url


def looks_like_page(url: str) -> bool:
    path = urllib.parse.urlsplit(url).path
    return os.path.splitext(path)[1].lower() in PAGE_EXT


def kind_from_ext(url: str, default: str = "other") -> str:
    ext = os.path.splitext(urllib.parse.urlsplit(url).path)[1].lower()
    if ext in FONT_EXT:
        return "font"
    if ext in IMG_EXT:
        return "img"
    if ext in MEDIA_EXT:
        return "media"
    if ext == ".css":
        return "css"
    if ext in (".js", ".mjs"):
        return "js"
    return default


def parse_srcset(value: str) -> List[str]:
    """URLs from a srcset/imagesrcset value (descriptors dropped)."""
    urls, i, n = [], 0, len(value or "")
    s = value or ""
    while i < n:
        while i < n and (s[i].isspace() or s[i] == ","):
            i += 1
        if i >= n:
            break
        j = i
        while j < n and not s[j].isspace():
            j += 1
        url = s[i:j]
        if url.endswith(","):
            url = url.rstrip(",")
            i = j
        else:
            depth = 0
            while j < n:
                c = s[j]
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth = max(0, depth - 1)
                elif c == "," and depth == 0:
                    j += 1
                    break
                j += 1
            i = j
        if url:
            urls.append(url)
    return urls


_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_CSS_URL_RE = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)\s]*))\s*\)", re.I)
_CSS_IMPORT_RE = re.compile(r"@import\s+(?:\"([^\"]+)\"|'([^']+)')", re.I)


def css_urls(css: str):
    """(url, offset, kind) triples referenced by CSS: url(...) and @import.

    kind is "css" for @import targets, otherwise guessed from the extension.
    """
    # Blank out comments but keep offsets stable for line numbers.
    css = _CSS_COMMENT_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), css or "")
    out = []
    for m in _CSS_URL_RE.finditer(css):
        u = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        if u and not u.lower().startswith(("data:", "#", "about:", "var(")):
            is_import = re.search(r"@import\s*$", css[max(0, m.start() - 24):m.start()], re.I)
            out.append((u, m.start(), "css" if is_import else kind_from_ext(u)))
    for m in _CSS_IMPORT_RE.finditer(css):
        u = (m.group(1) or m.group(2) or "").strip()
        if u:
            out.append((u, m.start(), "css"))
    return out


def image_size(data: bytes):
    """(width, height) from PNG, GIF, JPEG, WebP or AVIF headers, else None."""
    if not data:
        return None
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR" and len(data) >= 24:
            return struct.unpack(">II", data[16:24])
        if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
            return struct.unpack("<HH", data[6:10])
        if data[:2] == b"\xff\xd8":
            i, n = 2, len(data)
            while i + 9 < n:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker == 0xFF:
                    i += 1
                    continue
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                seg = struct.unpack(">H", data[i + 2:i + 4])[0]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                              0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w, h
                i += 2 + seg
            return None
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
            chunk = data[12:16]
            if chunk == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
                w = struct.unpack("<H", data[26:28])[0] & 0x3FFF
                h = struct.unpack("<H", data[28:30])[0] & 0x3FFF
                return w, h
            if chunk == b"VP8L" and data[20] == 0x2F:
                bits = int.from_bytes(data[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            if chunk == b"VP8X":
                return (int.from_bytes(data[24:27], "little") + 1,
                        int.from_bytes(data[27:30], "little") + 1)
        if data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis", b"mif1"):
            k = data.find(b"ispe")
            if k != -1 and k + 16 <= len(data):
                return struct.unpack(">II", data[k + 8:k + 16])
    except (struct.error, IndexError):
        return None
    return None


def human_bytes(n: Optional[int]) -> str:
    if n is None:
        return "unknown size"
    if n >= 1024 * 1024:
        return "%.1f MB" % (n / 1048576.0)
    return "%d KB" % round(n / 1024.0)


# --------------------------------------------------------------------------
# HTML analysis
# --------------------------------------------------------------------------
Ref = namedtuple("Ref", "cat kind raw line img_index")


def _has_aria_name(a: Dict[str, str]) -> bool:
    return any((a.get(k) or "").strip() for k in ("aria-label", "aria-labelledby", "title"))


class PageParser(HTMLParser):
    """Collects everything sitecheck needs from one HTML document in one pass."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.doctype = None
        self.html_lang = None
        self.title = None
        self.metas = []
        self.base_href = None
        self.refs = []
        self.ids = {}
        self.anchor_names = set()
        self.imgs = []
        self.icon_links = 0
        self.h1 = 0
        self.label_for = set()
        self.controls = []
        self.unnamed = []
        self.styles = []          # (css text, first line)
        self.style_attrs = []     # (css text, line)
        self._in_title = False
        self._svg = 0
        self._svg_title = False
        self._skip = 0
        self._template = 0
        self._label_depth = 0
        self._style_buf = None
        self._collect = []
        self._text = []
        self._text_len = 0

    # -- helpers -----------------------------------------------------------
    def _asset(self, kind, raw, line, img_index=None):
        self.refs.append(Ref("asset", kind, raw, line, img_index))

    def _close_collector(self, c):
        if not (c["named"] or "".join(c["text"]).strip()):
            self.unnamed.append((c["kind"], c["line"]))

    def _control(self, tag, a, line, typ=None):
        self.controls.append({
            "line": line, "tag": tag, "type": typ, "id": (a.get("id") or "").strip(),
            "named": _has_aria_name(a), "in_label": self._label_depth > 0,
            "placeholder": bool((a.get("placeholder") or "").strip()),
        })

    # -- parser callbacks --------------------------------------------------
    def handle_decl(self, decl):
        if decl.lower().startswith("doctype") and self.doctype is None:
            self.doctype = decl

    def handle_starttag(self, tag, attrs):
        a = {}
        for k, v in attrs:
            if k not in a:
                a[k] = v if v is not None else ""
        line = self.getpos()[0]
        if a.get("id") and not self._template:
            ident = a["id"].strip()
            if ident:
                self.ids.setdefault(ident, []).append(line)
        if a.get("style"):
            self.style_attrs.append((a["style"], line))

        if tag == "svg":
            self._svg += 1
        elif tag == "html":
            if self.html_lang is None:
                self.html_lang = a.get("lang", "")
        elif tag == "title":
            if self._svg:
                self._svg_title = True
            else:
                self._in_title = True
                if self.title is None:
                    self.title = ""
        elif tag == "meta":
            self.metas.append(a)
        elif tag == "base":
            if self.base_href is None and a.get("href"):
                self.base_href = a["href"]
        elif tag == "link":
            self._link_tag(a, line)
        elif tag == "script":
            self._skip += 1
            if a.get("src") is not None:
                self._asset("js", a["src"], line)
        elif tag == "style":
            self._skip += 1
            self._style_buf = (line, [])
        elif tag == "template":
            self._template += 1
            self._skip += 1
        elif tag == "img":
            self._img(a, line)
        elif tag == "source":
            if a.get("src"):
                self._asset("media", a["src"], line)
            for u in parse_srcset(a.get("srcset", "")):
                self._asset("img", u, line)
        elif tag in ("video", "audio"):
            if a.get("src"):
                self._asset("media", a["src"], line)
            if tag == "video" and a.get("poster"):
                self._asset("img", a["poster"], line)
        elif tag == "track":
            if a.get("src"):
                self._asset("media", a["src"], line)
        elif tag in ("iframe", "embed", "frame"):
            if a.get("src"):
                self._asset("frame", a["src"], line)
        elif tag == "object":
            if a.get("data"):
                self._asset("frame", a["data"], line)
        elif tag == "input":
            self._input(a, line)
        elif tag in ("select", "textarea"):
            self._control(tag, a, line)
        elif tag == "label":
            self._label_depth += 1
            if a.get("for"):
                self.label_for.add(a["for"].strip())
        elif tag == "form":
            if a.get("action"):
                self.refs.append(Ref("form", "form", a["action"], line, None))
        elif tag == "h1":
            self.h1 += 1
        elif tag in ("a", "area"):
            if a.get("name"):
                self.anchor_names.add(a["name"].strip())
            if "href" in a:
                self.refs.append(Ref("link", "page", a["href"], line, None))
                if tag == "a":
                    self._collect.append({"kind": "link", "line": line,
                                          "named": _has_aria_name(a), "text": []})
                elif not ((a.get("alt") or "").strip() or _has_aria_name(a)):
                    self.unnamed.append(("link", line))
        elif tag == "button":
            self._collect.append({"kind": "button", "line": line,
                                  "named": _has_aria_name(a), "text": []})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in ("a", "button", "label", "svg", "title", "script", "style", "template"):
            return
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "title":
            if self._svg_title:
                self._svg_title = False
            else:
                self._in_title = False
        elif tag == "svg":
            self._svg = max(0, self._svg - 1)
        elif tag == "script":
            self._skip = max(0, self._skip - 1)
        elif tag == "style":
            self._skip = max(0, self._skip - 1)
            if self._style_buf is not None:
                line, chunks = self._style_buf
                self.styles.append(("".join(chunks), line))
                self._style_buf = None
        elif tag == "template":
            self._template = max(0, self._template - 1)
            self._skip = max(0, self._skip - 1)
        elif tag == "label":
            self._label_depth = max(0, self._label_depth - 1)
        elif tag in ("a", "button"):
            kind = "link" if tag == "a" else "button"
            for i in range(len(self._collect) - 1, -1, -1):
                if self._collect[i]["kind"] == kind:
                    self._close_collector(self._collect.pop(i))
                    break

    def handle_data(self, data):
        if self._style_buf is not None:
            self._style_buf[1].append(data)
            return
        if self._in_title:
            self.title += data
            return
        if self._skip:
            return
        if self._collect and data.strip():
            for c in self._collect:
                c["text"].append(data)
        if self._text_len < 400000:
            self._text.append(data)
            self._text_len += len(data)

    def close(self):
        super().close()
        while self._collect:
            self._close_collector(self._collect.pop())
        if self._style_buf is not None:
            line, chunks = self._style_buf
            self.styles.append(("".join(chunks), line))
            self._style_buf = None

    # -- element handlers --------------------------------------------------
    def _link_tag(self, a, line):
        rel = set((a.get("rel") or "").lower().split())
        href = a.get("href")
        if href is not None and href.strip():
            if "stylesheet" in rel:
                self._asset("css", href, line)
            elif rel & {"icon", "apple-touch-icon", "apple-touch-icon-precomposed", "mask-icon"}:
                self._asset("img", href, line)
                if "icon" in rel:
                    self.icon_links += 1
            elif "manifest" in rel:
                self._asset("other", href, line)
            elif rel & {"preload", "modulepreload"}:
                kind = {"image": "img", "style": "css", "script": "js", "font": "font",
                        "video": "media", "audio": "media", "track": "media"}.get(
                    (a.get("as") or "").lower(), "js" if "modulepreload" in rel else "other")
                self._asset(kind, href, line)
        for u in parse_srcset(a.get("imagesrcset", "")):
            self._asset("img", u, line)

    def _img(self, a, line):
        style = (a.get("style") or "").lower()
        info = {
            "line": line, "src": a.get("src"), "alt": a.get("alt"),
            "width": a.get("width"), "height": a.get("height"), "srcset": a.get("srcset"),
            "hidden": (a.get("aria-hidden") or "").lower() == "true"
                      or (a.get("role") or "").lower() in ("presentation", "none"),
            "styled_size": "aspect-ratio" in style
                           or (re.search(r"(^|;|\s)width\s*:", style) is not None
                               and re.search(r"(^|;|\s)height\s*:", style) is not None),
        }
        self.imgs.append(info)
        index = len(self.imgs) - 1
        src = a.get("src")
        if src is not None:
            self._asset("img", src, line, img_index=index)
        for u in parse_srcset(a.get("srcset", "")):
            self._asset("img", u, line)
        if (a.get("alt") or "").strip():
            for c in self._collect:
                c["named"] = True

    def _input(self, a, line):
        typ = (a.get("type") or "text").strip().lower()
        if typ in ("hidden", "submit", "reset", "button"):
            return
        if typ == "image":
            if a.get("src"):
                self._asset("img", a["src"], line)
            if not ((a.get("alt") or "").strip() or _has_aria_name(a)):
                self.unnamed.append(("button", line))
            return
        self._control("input", a, line, typ)

    @property
    def text(self) -> str:
        return " ".join(self._text)


@dataclass
class Finding:
    rule: str
    page: str = ""
    url: str = ""
    line: int = 0
    detail: str = ""
    also: int = 0

    @property
    def severity(self) -> str:
        return RULES[self.rule][0]

    def to_dict(self) -> dict:
        return {"severity": self.severity, "rule": self.rule, "page": self.page, "url": self.url,
                "line": self.line, "detail": self.detail, "also_on": self.also,
                "fix": RULES[self.rule][2]}


@dataclass
class PageAnalysis:
    url: str
    title: str = ""
    findings: List[Finding] = field(default_factory=list)
    links: list = field(default_factory=list)      # (target, fragment, line, raw)
    assets: list = field(default_factory=list)     # (target, kind, line, img_index)
    targets: set = field(default_factory=set)      # ids and <a name> values
    imgs: list = field(default_factory=list)
    icon_links: int = 0


def _meta(metas, key, value):
    for m in metas:
        if (m.get(key) or "").strip().lower() == value:
            return m
    return None


def _viewport_blocks_zoom(content: str) -> bool:
    params = {}
    for part in re.split(r"[,;]", content or ""):
        if "=" in part:
            k, v = part.split("=", 1)
            params[k.strip().lower()] = v.strip().lower()
    if params.get("user-scalable") in ("no", "0"):
        return True
    try:
        return float(params["maximum-scale"]) < 2
    except (KeyError, ValueError):
        return False


def analyze(html_text: str, page_url: str, header_charset: str = "", headers=None,
            is_home: bool = False, site_is_local: bool = True) -> PageAnalysis:
    """Analyze one HTML document. Pure function: no network access."""
    headers = headers or {}
    p = PageParser()
    try:
        p.feed(html_text)
        p.close()
    except Exception:  # html.parser can choke on rare malformed markup; keep what we have
        pass
    out = PageAnalysis(url=page_url, title=(p.title or "").strip(), imgs=p.imgs,
                       icon_links=p.icon_links)
    out.targets = set(p.ids) | p.anchor_names
    base = page_url
    if p.base_href:
        kind, resolved, _ = resolve(p.base_href, page_url)
        if kind == "http":
            base = resolved
    https_page = page_url.startswith("https:")

    def add(rule, url="", line=0, detail=""):
        out.findings.append(Finding(rule, page=page_url, url=url or page_url, line=line, detail=detail))

    def check_location(kind, raw, url, line, what):
        if kind == "file":
            add("local-url", raw, line, "%s at line %d points at a file:// path" % (what, line))
            return
        if kind == "http" and not site_is_local and is_local_host(urllib.parse.urlsplit(url).hostname):
            add("local-url", url, line, "%s at line %d points at a local address" % (what, line))

    # Document-level checks.
    if not (p.doctype or "").lower().startswith("doctype html"):
        add("missing-doctype", detail="first line is not <!doctype html>")
    if not (p.html_lang or "").strip():
        add("missing-lang", detail="<html> has no lang")
    if not out.title:
        add("missing-title", detail="no <title>, or it is empty")
    viewport = _meta(p.metas, "name", "viewport")
    if viewport is None:
        add("missing-viewport", detail="no <meta name=\"viewport\">")
    elif _viewport_blocks_zoom(viewport.get("content", "")):
        add("zoom-disabled", detail='viewport is "%s"' % viewport.get("content", "").strip())
    desc = _meta(p.metas, "name", "description")
    if desc is None or not (desc.get("content") or "").strip():
        add("missing-description", detail="no meta description")
    has_charset = bool(header_charset) or any("charset" in m for m in p.metas) or any(
        "charset=" in (m.get("content") or "").lower() for m in p.metas
        if (m.get("http-equiv") or "").lower() == "content-type") or html_text.startswith("\ufeff")
    if not has_charset:
        add("missing-charset", detail="no <meta charset> and the server sent no charset")
    robots = " ".join((m.get("content") or "").lower() for m in p.metas
                      if (m.get("name") or "").lower() in ("robots", "googlebot"))
    if "noindex" in robots or "noindex" in str(headers.get("x-robots-tag", "")).lower():
        add("noindex", detail="robots noindex is set")
    if p.h1 == 0:
        add("missing-h1", detail="no <h1>")
    for ident, lines in p.ids.items():
        if len(lines) > 1:
            add("duplicate-id", line=lines[0], detail='id="%s" is used %d times (lines %s)'
                % (ident, len(lines), ", ".join(str(n) for n in lines[:8])))

    # Images: alt text and intrinsic size attributes.
    for img in p.imgs:
        kind, src, _ = resolve(img["src"], base)
        raw_src = (img["src"] or "").strip()
        where = src if kind == "http" else (
            "inline data: image" if raw_src.lower().startswith("data:") else (raw_src[:80] or "<img>"))
        if img["alt"] is None and not img["hidden"]:
            add("img-missing-alt", where, img["line"], "line %d" % img["line"])
        if not (img["width"] and img["height"]) and not img["styled_size"]:
            add("img-missing-size", where, img["line"], "line %d" % img["line"])

    # Form fields and accessible names.
    for c in p.controls:
        labeled = c["named"] or c["in_label"] or (c["id"] and c["id"] in p.label_for)
        if not labeled:
            what = "<%s%s>" % (c["tag"], ' type="%s"' % c["type"] if c["type"] else "")
            hint = " (has a placeholder, but a placeholder is not a label)" if c["placeholder"] else ""
            add("unlabeled-field", line=c["line"], detail="%s at line %d%s" % (what, c["line"], hint))
    for kind, line in p.unnamed:
        add("unnamed-link" if kind == "link" else "unnamed-button", line=line,
            detail="<%s> at line %d" % ("a" if kind == "link" else "button", line))

    if _LOREM_RE.search(p.text):
        add("lorem-ipsum", detail="lorem ipsum found in the page text")

    # Links, assets and forms.
    for ref in p.refs:
        kind, url, frag = resolve(ref.raw, base)
        if ref.cat == "link":
            stripped = _WS_RE.sub("", ref.raw or "").strip()
            if kind in ("empty", "js") or stripped == "#":
                add("placeholder-link", line=ref.line,
                    detail='href="%s" at line %d' % (stripped[:40], ref.line))
                continue
            check_location(kind, ref.raw, url, ref.line, "link")
            if kind == "http":
                out.links.append((url, frag, ref.line, ref.raw))
        elif ref.cat == "asset":
            if kind == "empty":
                if ref.kind == "img" and ref.img_index is not None:
                    add("broken-asset", line=ref.line, detail="<img> at line %d has an empty src" % ref.line)
                continue
            check_location(kind, ref.raw, url, ref.line, "resource")
            if kind != "http":
                continue
            if https_page and url.startswith("http:"):
                add("mixed-content", url, ref.line, "loaded over http at line %d" % ref.line)
            out.assets.append((url, ref.kind, ref.line, ref.img_index))
        elif ref.cat == "form":
            check_location(kind, ref.raw, url, ref.line, "form action")
            if kind == "http" and https_page and url.startswith("http:"):
                add("mixed-content", url, ref.line, "form submits over http at line %d" % ref.line)

    # CSS inside the page: <style> blocks and style="" attributes.
    blocks = [(css, line) for css, line in p.styles] + list(p.style_attrs)
    for css, start_line in blocks:
        for raw, offset, asset_kind in css_urls(css):
            kind, url, _ = resolve(raw, base)
            line = start_line + css.count("\n", 0, offset)
            check_location(kind, raw, url, line, "CSS url()")
            if kind != "http":
                continue
            if https_page and url.startswith("http:"):
                add("mixed-content", url, line, "CSS loads it over http at line %d" % line)
            out.assets.append((url, asset_kind, line, None))

    # Home page only: favicon is checked later (needs the network); og:image now.
    if is_home:
        og = _meta(p.metas, "property", "og:image") or _meta(p.metas, "name", "og:image")
        content = (og.get("content") or "").strip() if og else ""
        if not content:
            add("missing-og-image", detail="no og:image meta tag")
        else:
            kind, url, _ = resolve(content, base)
            if not re.match(r"^https?://", content, re.I):
                add("relative-og-image", url or content, 0, 'og:image is "%s"' % content[:80])
            if kind == "http":
                out.assets.append((url, "img", 0, None))
    return out


def decode_html(body: bytes, charset: str) -> str:
    cs = charset
    if body.startswith(b"\xef\xbb\xbf"):
        return "\ufeff" + body[3:].decode("utf-8", errors="replace")
    if not cs:
        m = re.search(rb"<meta[^>]+charset\s*=\s*[\"']?([A-Za-z0-9_\-]+)", body[:4096], re.I)
        if m:
            cs = m.group(1).decode("ascii", "ignore")
    try:
        return body.decode(cs or "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------
@dataclass
class Result:
    url: str
    status: int = 0
    final_url: str = ""
    error: str = ""
    dns_fail: bool = False
    content_type: str = ""
    charset: str = ""
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    size: Optional[int] = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 400

    def describe(self) -> str:
        return ("HTTP %d" % self.status) if self.status else (self.error or "no response")


def describe_error(err) -> str:
    if isinstance(err, socket.gaierror):
        return "domain does not resolve"
    if isinstance(err, ssl.SSLCertVerificationError):
        return "TLS certificate not trusted (for a local dev certificate, add --insecure)"
    if isinstance(err, ConnectionRefusedError):
        return "connection refused (is the server running?)"
    if isinstance(err, (socket.timeout, TimeoutError)):
        return "timed out"
    text = str(err) or err.__class__.__name__
    return text[:160]


def is_html(res: Result) -> bool:
    if res.content_type:
        return res.content_type in ("text/html", "application/xhtml+xml")
    head = res.body[:512].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


class Fetcher:
    def __init__(self, timeout: float = 10.0, insecure: bool = False, user_agent: str = USER_AGENT):
        ctx = ssl.create_default_context()
        if insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self.timeout = timeout
        self.user_agent = user_agent
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
        self.count = 0
        self._lock = threading.Lock()

    def fetch(self, url: str, method: str = "GET", max_bytes: int = PAGE_CAP,
              extra_headers: Optional[dict] = None) -> Result:
        res = self._once(url, method, max_bytes, extra_headers)
        transient = (res.status == 0 and not res.dns_fail) or res.status in (502, 503, 504)
        if transient:
            time.sleep(0.4)
            res = self._once(url, method, max_bytes, extra_headers)
        return res

    def _once(self, url, method, max_bytes, extra_headers) -> Result:
        with self._lock:
            self.count += 1
        headers = {"User-Agent": self.user_agent, "Accept-Encoding": "identity",
                   "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
        if extra_headers:
            headers.update(extra_headers)
        res = Result(url=url)
        try:
            req = urllib.request.Request(url, method=method, headers=headers)
            with self.opener.open(req, timeout=self.timeout) as resp:
                res.status = resp.status
                res.final_url = resp.geturl() or url
                res.headers = {k.lower(): v for k, v in resp.headers.items()}
                if "content-type" in res.headers:
                    res.content_type = resp.headers.get_content_type()
                    res.charset = resp.headers.get_content_charset() or ""
                length = res.headers.get("content-length", "")
                if length.isdigit():
                    res.size = int(length)
                if method != "HEAD" and max_bytes:
                    data = resp.read(max_bytes + 1)
                    if len(data) <= max_bytes and res.status == 200:
                        res.size = len(data)
                    res.body = data[:max_bytes]
        except urllib.error.HTTPError as exc:
            res.status = exc.code
            res.final_url = exc.geturl() or url
            res.headers = {k.lower(): v for k, v in (exc.headers or {}).items()}
            try:
                exc.close()
            except Exception:
                pass
        except urllib.error.URLError as exc:
            res.error = describe_error(exc.reason)
            res.dns_fail = isinstance(exc.reason, socket.gaierror)
        except (socket.timeout, TimeoutError):
            res.error = "timed out after %gs" % self.timeout
        except (http.client.HTTPException, OSError, ValueError) as exc:
            res.error = describe_error(exc)
        return res

    def check(self, url: str, kind: str) -> Result:
        """Status check suited to the kind of URL (downloads images to weigh them)."""
        if kind == "img":
            return self.fetch(url, "GET", max_bytes=IMAGE_CAP)
        if kind == "css":
            return self.fetch(url, "GET", max_bytes=CSS_CAP)
        res = self.fetch(url, "HEAD", max_bytes=0)
        if res.status >= 400 or (res.status == 0 and not res.dns_fail and "timed out" not in res.error):
            extra = {"Range": "bytes=0-1023"} if kind == "media" else None
            res = self.fetch(url, "GET", max_bytes=2048, extra_headers=extra)
        return res


# --------------------------------------------------------------------------
# Crawl
# --------------------------------------------------------------------------
class StartError(Exception):
    pass


@dataclass
class Options:
    depth: int = 3
    limit: int = 100
    external: bool = False
    max_image_kb: int = 500
    timeout: float = 10.0
    workers: int = 8
    insecure: bool = False
    exclude: list = field(default_factory=list)
    ignore: set = field(default_factory=set)
    strict: bool = False


class Crawler:
    def __init__(self, opts: Options):
        self.opts = opts
        self.fetcher = Fetcher(timeout=opts.timeout, insecure=opts.insecure)
        self.results: Dict[str, Result] = {}
        self.pages: "OrderedDict[str, dict]" = OrderedDict()
        self.alias: Dict[str, str] = {}
        self.link_refs: "OrderedDict[str, list]" = OrderedDict()
        self.anchor_refs: list = []
        self.asset_refs: "OrderedDict[str, dict]" = OrderedDict()
        self.findings: List[Finding] = []
        self.origins: set = set()
        self.external_skipped: set = set()
        self.excluded = 0
        self.home = ""
        self.site_is_local = True
        self._exclude = [re.compile(x) for x in opts.exclude]

    # -- helpers -----------------------------------------------------------
    def internal(self, url: str) -> bool:
        return origin_of(url) in self.origins

    def excluded_url(self, url: str) -> bool:
        return any(rx.search(url) for rx in self._exclude)

    def _parallel(self, func, items):
        if not items:
            return []
        workers = max(1, min(self.opts.workers, len(items)))
        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(func, items))

    # -- phases ------------------------------------------------------------
    def run(self, start_url: str) -> dict:
        t0 = time.time()
        start = normalize(start_url)
        if start is None:
            raise StartError("not a valid http(s) URL: %s" % start_url)
        first = self.fetcher.fetch(start, "GET", max_bytes=PAGE_CAP)
        if not first.ok:
            raise StartError("could not load %s (%s)" % (start_url, first.describe()))
        if not is_html(first):
            raise StartError("%s is not an HTML page (content-type: %s)"
                             % (start_url, first.content_type or "unknown"))
        final = normalize(first.final_url or start) or start
        self.origins = {origin_of(start), origin_of(final)}
        self.home = final
        self.site_is_local = is_local_host(urllib.parse.urlsplit(final).hostname)

        seen = {start, final}
        level = [(start, first)]
        depth = 0
        while level:
            next_urls: List[str] = []
            for url, res in level:
                self._process_page(url, res, depth, next_urls, seen)
            depth += 1
            room = self.opts.limit - len(self.pages)
            if depth > self.opts.depth or room <= 0 or not next_urls:
                break
            batch = next_urls[:room]
            fetched = self._parallel(lambda u: self.fetcher.fetch(u, "GET", max_bytes=PAGE_CAP), batch)
            level = list(zip(batch, fetched))

        self._check_links()
        self._check_assets()
        self._check_anchors()
        self._check_favicon()
        return self._report(start_url, time.time() - t0)

    def _process_page(self, url, res, depth, next_urls, seen):
        self.results[url] = res
        if not res.ok:
            return
        final = normalize(res.final_url or url) or url
        self.alias[url] = final
        self.results.setdefault(final, res)
        if not self.internal(final) or final in self.pages or not is_html(res):
            return
        analysis = analyze(decode_html(res.body, res.charset), final, header_charset=res.charset,
                           headers=res.headers, is_home=(final == self.home),
                           site_is_local=self.site_is_local)
        res.body = b""  # free memory; analysis holds what we need
        self.pages[final] = {"url": final, "status": res.status, "depth": depth,
                             "title": analysis.title, "analysis": analysis}
        self.findings.extend(analysis.findings)
        for target, frag, line, _raw in analysis.links:
            if self.excluded_url(target):
                self.excluded += 1
                continue
            self.link_refs.setdefault(target, []).append((final, line))
            if frag is not None:
                self.anchor_refs.append((target, frag, final, line))
            if self.internal(target) and looks_like_page(target) and target not in seen:
                seen.add(target)
                next_urls.append(target)
        for target, kind, line, img_index in analysis.assets:
            self._add_asset(target, kind, final, line, img_index)

    def _add_asset(self, target, kind, page, line, img_index=None):
        if self.excluded_url(target):
            self.excluded += 1
            return
        entry = self.asset_refs.get(target)
        if entry is None:
            entry = self.asset_refs[target] = {"kind": kind, "refs": []}
        elif kind in ("img", "css") and entry["kind"] not in ("img", "css"):
            entry["kind"] = kind  # these kinds need the body, so they win
        entry["refs"].append((page, line, img_index))

    def _group(self, refs):
        pages = []
        for page, _line, *_rest in refs:
            if page not in pages:
                pages.append(page)
        return refs[0][0], refs[0][1], max(0, len(pages) - 1)

    def _classify(self, res: Result, internal: bool, cat: str) -> Optional[str]:
        if res.ok:
            return None
        if internal:
            return "broken-link" if cat == "link" else "broken-asset"
        if res.status in (404, 410) or res.dns_fail:
            return "external-link" if cat == "link" else "external-asset"
        return "external-unverified"

    def _check_links(self):
        todo = []
        for target in self.link_refs:
            if target in self.results:
                continue
            if self.internal(target) or self.opts.external:
                todo.append(target)
            else:
                self.external_skipped.add(target)
        for target, res in zip(todo, self._parallel(lambda u: self.fetcher.check(u, "page"), todo)):
            self.results[target] = res
        for target, refs in self.link_refs.items():
            res = self.results.get(target)
            if res is None:
                continue
            rule = self._classify(res, self.internal(target), "link")
            if rule:
                page, line, also = self._group(refs)
                self.findings.append(Finding(rule, page=page, url=target, line=line, also=also,
                                             detail="%s, linked from %s line %d"
                                             % (res.describe(), display(page, self.origins), line)))

    def _check_assets(self):
        checked = set()
        for _round in range(4):  # extra rounds pick up fonts/images found inside CSS
            todo = []
            for target, entry in self.asset_refs.items():
                if target in checked:
                    continue
                checked.add(target)
                if self.internal(target) or self.opts.external:
                    todo.append(target)
                else:
                    self.external_skipped.add(target)
            if not todo:
                break
            kinds = [self.asset_refs[t]["kind"] for t in todo]
            results = self._parallel(lambda pair: self.fetcher.check(*pair), list(zip(todo, kinds)))
            for target, res in zip(todo, results):
                self._judge_asset(target, res)

    def _judge_asset(self, target: str, res: Result):
        entry = self.asset_refs[target]
        refs = entry["refs"]
        page, line, also = self._group(refs)
        where = "%s line %d" % (display(page, self.origins), line) if line else display(page, self.origins)
        rule = self._classify(res, self.internal(target), "asset")
        if rule:
            self.findings.append(Finding(rule, page=page, url=target, line=line, also=also,
                                         detail="%s, used on %s" % (res.describe(), where)))
            res.body = b""
            return
        if entry["kind"] == "css" and self.internal(target) and res.body:
            css = res.body.decode("utf-8", errors="replace")
            base = normalize(res.final_url or target) or target
            for raw, offset, asset_kind in css_urls(css):
                kind, url, _ = resolve(raw, base)
                if kind == "http":
                    line_no = css.count("\n", 0, offset) + 1
                    if base.startswith("https:") and url.startswith("http:"):
                        self.findings.append(Finding("mixed-content", page=target, url=url, line=line_no,
                                                     detail="stylesheet loads it over http at line %d"
                                                     % line_no))
                    self._add_asset(url, asset_kind, target, line_no)
        if entry["kind"] == "img":
            self._judge_image(target, res, refs, page, line, also, where)
        res.body = b""

    def _judge_image(self, target, res, refs, page, line, also, where):
        size = res.size
        dims = image_size(res.body[:262144]) if res.body else None
        dim_text = " (%dx%d)" % dims if dims else ""
        if size is not None and size > self.opts.max_image_kb * 1024:
            self.findings.append(Finding("image-heavy", page=page, url=target, line=line, also=also,
                                         detail="%s%s, over the %d KB budget, used on %s"
                                         % (human_bytes(size), dim_text, self.opts.max_image_kb, where)))
        if not dims:
            return
        for ref_page, ref_line, img_index in refs:
            if img_index is None:
                continue
            info = self.pages.get(ref_page, {}).get("analysis")
            if info is None or img_index >= len(info.imgs):
                continue
            img = info.imgs[img_index]
            if img.get("srcset"):
                continue
            m = re.match(r"^\s*(\d+)", img.get("width") or "")
            if not m or int(m.group(1)) <= 0:
                continue
            shown = int(m.group(1))
            if dims[0] >= 800 and dims[0] >= 3 * shown:
                self.findings.append(Finding(
                    "image-oversized", page=ref_page, url=target, line=ref_line,
                    detail="%dx%d pixels shown at width=%d on %s line %d (about %dx too large)"
                    % (dims[0], dims[1], shown, display(ref_page, self.origins), ref_line,
                       dims[0] // shown)))
                break

    def _check_anchors(self):
        missing: "OrderedDict[tuple, list]" = OrderedDict()
        for target, frag, page, line in self.anchor_refs:
            if frag is None or frag in ("", "top") or frag.startswith((":~:", "!", "/")):
                continue
            dest = self.alias.get(target, target)
            info = self.pages.get(dest)
            if info is None:
                continue
            wanted = urllib.parse.unquote(frag)
            targets = info["analysis"].targets
            if wanted not in targets and frag not in targets:
                missing.setdefault((dest, wanted), []).append((page, line))
        for (dest, wanted), refs in missing.items():
            page, line, also = self._group(refs)
            self.findings.append(Finding("broken-anchor", page=page, url=dest + "#" + wanted, line=line,
                                         also=also, detail='no id="%s" on %s, linked from %s line %d'
                                         % (wanted, display(dest, self.origins),
                                            display(page, self.origins), line)))

    def _check_favicon(self):
        home = self.pages.get(self.home)
        if home is None or home["analysis"].icon_links:
            return
        res = self.fetcher.check(origin_of(self.home) + "/favicon.ico", "img")
        if not res.ok:
            self.findings.append(Finding("missing-favicon", page=self.home, url=self.home,
                                         detail="no <link rel=\"icon\"> and /favicon.ico is %s"
                                         % res.describe()))

    # -- report ------------------------------------------------------------
    def _report(self, target: str, seconds: float) -> dict:
        order = {rule: i for i, rule in enumerate(RULES)}
        page_order = {url: i for i, url in enumerate(self.pages)}
        findings = [f for f in self.findings if f.rule not in self.opts.ignore]
        findings.sort(key=lambda f: (order[f.rule], page_order.get(f.page, 10 ** 6), f.line, f.url))
        errors = sum(1 for f in findings if f.severity == "error")
        warnings = len(findings) - errors
        failed = errors > 0 or (self.opts.strict and warnings > 0)
        return {
            "tool": "sitecheck", "version": VERSION, "target": target, "start_url": self.home,
            "origins": sorted(self.origins),
            "options": {"depth": self.opts.depth, "limit": self.opts.limit,
                        "external": self.opts.external, "max_image_kb": self.opts.max_image_kb,
                        "strict": self.opts.strict, "ignore": sorted(self.opts.ignore)},
            "stats": {"pages": len(self.pages), "links": len(self.link_refs),
                      "assets": len(self.asset_refs), "external_skipped": len(self.external_skipped),
                      "excluded": self.excluded, "requests": self.fetcher.count,
                      "seconds": round(seconds, 2)},
            "summary": {"errors": errors, "warnings": warnings, "result": "fail" if failed else "pass"},
            "findings": [f.to_dict() for f in findings],
            "pages": [{"url": p["url"], "status": p["status"], "depth": p["depth"], "title": p["title"]}
                      for p in self.pages.values()],
        }


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def format_text(report: dict) -> str:
    origins = set(report["origins"])
    st, opts = report["stats"], report["options"]
    lines = ["sitecheck %s  %s" % (report["version"], report["start_url"]),
             "Checked %d page%s (depth %d, limit %d), %d links and %d assets in %.1fs."
             % (st["pages"], "" if st["pages"] == 1 else "s", opts["depth"], opts["limit"],
                st["links"], st["assets"], st["seconds"])]
    if st["external_skipped"]:
        lines.append("Not checked: %d external URL%s (add --external to include them)."
                     % (st["external_skipped"], "" if st["external_skipped"] == 1 else "s"))
    for severity, heading in (("error", "ERRORS"), ("warn", "WARNINGS")):
        group = [f for f in report["findings"] if f["severity"] == severity]
        if not group:
            continue
        lines.append("")
        lines.append("%s (%d)" % (heading, len(group)))
        current = None
        for f in group:
            if f["rule"] != current:
                if current is not None:
                    lines.append("    fix: " + RULES[current][2])
                current = f["rule"]
                lines.append("  %s: %s" % (current, RULES[current][1]))
            target = display(f["url"] or f["page"], origins)
            more = " (+%d more page%s)" % (f["also_on"], "" if f["also_on"] == 1 else "s") if f["also_on"] else ""
            lines.append("    %s  %s%s" % (target, f["detail"], more))
        lines.append("    fix: " + RULES[current][2])
    s = report["summary"]
    lines.append("")
    if s["result"] == "pass":
        tail = " Review the warnings before you ship." if s["warnings"] else ""
        lines.append("PASS: %d errors, %d warnings.%s" % (s["errors"], s["warnings"], tail))
    else:
        why = "Fix every error" if s["errors"] else "Fix the warnings (--strict)"
        lines.append("FAIL: %d errors, %d warnings. %s, then run sitecheck again."
                     % (s["errors"], s["warnings"], why))
    return "\n".join(lines)


def list_rules() -> str:
    width = max(len(r) for r in RULES)
    out = ["Rules (error = fails the check, warn = review before shipping):"]
    for rule, (sev, what, fix) in RULES.items():
        out.append("  %-*s  %-5s  %s" % (width, rule, sev, what))
        out.append("  %-*s         fix: %s" % (width, "", fix))
    return "\n".join(out)


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------
def check_site(target: str, opts: Options, spa: bool = False, clean_urls: bool = False) -> dict:
    """Check a URL, a folder or an .html file. Raises StartError when it cannot run."""
    if re.match(r"^https?://", target, re.I):
        return Crawler(opts).run(target)
    path = target[7:] if target.lower().startswith("file://") else target
    path = os.path.abspath(os.path.expanduser(urllib.parse.unquote(path)))
    if not os.path.exists(path):
        if re.match(r"^[\w.-]+\.[a-z]{2,}(:\d+)?(/.*)?$", target, re.I):
            return Crawler(opts).run("https://" + target)
        raise StartError("no such file, folder or URL: %s" % target)
    root, start_path = (os.path.dirname(path), "/" + os.path.basename(path)) if os.path.isfile(path) \
        else (path, "/")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import serve  # local module in the same folder
    server, base = serve.start(root, spa=spa, clean_urls=clean_urls, quiet=True)
    try:
        report = Crawler(opts).run(base.rstrip("/") + urllib.parse.quote(start_path))
        report["served_from"] = root
        return report
    finally:
        serve.stop(server)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="sitecheck.py",
        description="Crawl a local folder or a live site (same origin) and report broken links "
                    "and assets, missing page basics, accessibility basics, mixed content, "
                    "duplicate ids and heavy images.",
        epilog="Examples: sitecheck.py site/ | sitecheck.py https://example.com --external | "
               "sitecheck.py --list-rules")
    ap.add_argument("target", nargs="?", help="URL, folder, or .html file (folders are served for you)")
    ap.add_argument("--depth", type=int, default=3, help="link hops from the start page to crawl (default 3)")
    ap.add_argument("--limit", type=int, default=100, help="maximum pages to crawl (default 100)")
    ap.add_argument("--external", action="store_true", help="also check links and assets on other sites")
    ap.add_argument("--max-image-kb", type=int, default=500, help="image weight budget in KB (default 500)")
    ap.add_argument("--timeout", type=float, default=10.0, help="seconds per request (default 10)")
    ap.add_argument("--workers", type=int, default=8, help="parallel requests (default 8)")
    ap.add_argument("--insecure", action="store_true", help="accept self-signed TLS certificates")
    ap.add_argument("--exclude", action="append", default=[], metavar="REGEX",
                    help="skip URLs matching this regex (repeatable)")
    ap.add_argument("--ignore", action="append", default=[], metavar="RULE",
                    help="drop findings for a rule, e.g. --ignore missing-og-image (repeatable)")
    ap.add_argument("--strict", action="store_true", help="warnings also fail (exit 1)")
    ap.add_argument("--spa", action="store_true", help="folder mode: unknown routes serve index.html")
    ap.add_argument("--clean-urls", action="store_true", help="folder mode: /about serves about.html")
    ap.add_argument("--json", action="store_true", help="print the JSON report instead of text")
    ap.add_argument("--report", metavar="FILE", help="also write the JSON report to FILE")
    ap.add_argument("--list-rules", action="store_true", help="list every rule with its fix and exit")
    ap.add_argument("--version", action="version", version="sitecheck.py " + VERSION)
    args = ap.parse_args(argv)

    if args.list_rules:
        print(list_rules())
        return 0
    if not args.target:
        ap.print_usage(sys.stderr)
        print("sitecheck.py: give a URL, a folder or an .html file (or --list-rules)", file=sys.stderr)
        return 2
    ignore = {r.strip() for item in args.ignore for r in item.split(",") if r.strip()}
    unknown = sorted(ignore - set(RULES))
    if unknown:
        print("sitecheck.py: unknown rule(s): %s (see --list-rules)" % ", ".join(unknown), file=sys.stderr)
        return 2
    try:
        excludes = [re.compile(x) and x for x in args.exclude]
    except re.error as exc:
        print("sitecheck.py: bad --exclude regex: %s" % exc, file=sys.stderr)
        return 2
    if args.depth < 0 or args.limit < 1 or args.workers < 1:
        print("sitecheck.py: --depth must be >= 0, --limit and --workers >= 1", file=sys.stderr)
        return 2
    opts = Options(depth=args.depth, limit=args.limit, external=args.external,
                   max_image_kb=args.max_image_kb, timeout=args.timeout, workers=args.workers,
                   insecure=args.insecure, exclude=excludes, ignore=ignore, strict=args.strict)
    try:
        report = check_site(args.target, opts, spa=args.spa, clean_urls=args.clean_urls)
    except StartError as exc:
        print("sitecheck.py: %s" % exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 2
    if args.report:
        folder = os.path.dirname(os.path.abspath(args.report))
        os.makedirs(folder, exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_text(report))
    return 1 if report["summary"]["result"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
