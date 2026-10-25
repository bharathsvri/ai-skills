#!/usr/bin/env python3
"""serve.py: preview a static site locally, the way static hosts serve it.

Part of the BUILD master skill (github.com/Jakeschincariol/master-skills).
Python 3 standard library only. Works on macOS and Linux.

Why not plain `python3 -m http.server`? This adds what a real preview needs:
  * no-cache headers, so every edit shows on a normal reload
  * correct types for modern files (.mjs, .wasm, .webp, .avif, .woff2, ...)
  * byte ranges (Safari refuses to play <video> from a server without them)
  * host-style 404s: your own 404.html is served with status 404
  * --clean-urls: /about serves about.html (Netlify, GitHub Pages behaviour)
  * --spa: unknown routes without a file extension serve index.html
  * a free-port search and a --lan URL to open the site on your phone

Examples:
  python3 serve.py site/                 # http://127.0.0.1:8000/
  python3 serve.py site/ --lan           # also prints a URL for your phone
  python3 serve.py dist/ --spa --port 5000

Exit codes: 0 stopped normally (Ctrl+C), 2 bad arguments or could not bind.
"""
from __future__ import annotations

import argparse
import functools
import os
import socket
import sys
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.0.0"

# Types that older mimetypes tables get wrong or do not know.
TYPES = {
    ".html": "text/html", ".htm": "text/html",
    ".css": "text/css",
    ".js": "text/javascript", ".mjs": "text/javascript", ".cjs": "text/javascript",
    ".json": "application/json", ".map": "application/json",
    ".webmanifest": "application/manifest+json",
    ".wasm": "application/wasm",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".avif": "image/avif", ".ico": "image/x-icon",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf",
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav", ".ogg": "audio/ogg",
    ".vtt": "text/vtt", ".txt": "text/plain", ".xml": "application/xml",
    ".pdf": "application/pdf", ".zip": "application/zip",
}

# File extensions that mean "this is an asset, not a page route" for --spa.
_ROUTE_EXTS = {"", ".html", ".htm"}


def parse_range(header: str, size: int):
    """Parse a single 'bytes=' Range header.

    Returns (start, end) inclusive, the string "full" when the header should be
    ignored (multi-range or malformed), or None when the range is unsatisfiable.
    """
    h = (header or "").strip()
    if not h.lower().startswith("bytes=") or "," in h:
        return "full"
    spec = h[6:].strip()
    if "-" not in spec:
        return "full"
    first, last = spec.split("-", 1)
    try:
        if first == "":
            n = int(last)
            if n <= 0:
                return None
            start, end = max(0, size - n), size - 1
        else:
            start = int(first)
            end = int(last) if last else size - 1
            end = min(end, size - 1)
    except ValueError:
        return "full"
    if start < 0 or start > end or start >= size:
        return None
    return start, end


class PreviewHandler(SimpleHTTPRequestHandler):
    """Static file handler that behaves like Netlify/Vercel/GitHub Pages."""

    server_version = "build-serve/" + VERSION
    spa = False
    clean_urls = False
    verbose = False
    quiet = False

    # ---- headers and types -------------------------------------------------
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def guess_type(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext in TYPES:
            return TYPES[ext]
        return super().guess_type(path)

    # ---- resolution --------------------------------------------------------
    def _resolve(self):
        """Return (filesystem path, status) or (None, None) after a redirect."""
        parts = urllib.parse.urlsplit(self.path)
        url_path = parts.path or "/"
        fs_path = self.translate_path(self.path)
        if os.path.isdir(fs_path):
            if not url_path.endswith("/"):
                target = urllib.parse.urlunsplit(("", "", url_path + "/", parts.query, ""))
                self.send_response(HTTPStatus.MOVED_PERMANENTLY)
                self.send_header("Location", target)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None, None
            index = os.path.join(fs_path, "index.html")
            return (index, HTTPStatus.OK) if os.path.isfile(index) else self._not_found(url_path)
        if os.path.isfile(fs_path):
            return fs_path, HTTPStatus.OK
        return self._not_found(url_path)

    def _not_found(self, url_path):
        ext = os.path.splitext(url_path)[1].lower()
        if self.clean_urls and ext == "" and url_path not in ("", "/"):
            candidate = self.translate_path(url_path.rstrip("/") + ".html")
            if os.path.isfile(candidate):
                return candidate, HTTPStatus.OK
        if self.spa and ext in _ROUTE_EXTS:
            index = os.path.join(self.directory, "index.html")
            if os.path.isfile(index):
                return index, HTTPStatus.OK
        custom = os.path.join(self.directory, "404.html")
        if os.path.isfile(custom):
            return custom, HTTPStatus.NOT_FOUND
        return "", HTTPStatus.NOT_FOUND

    def send_head(self):
        self._remaining = None
        fs_path, status = self._resolve()
        if fs_path is None:
            return None  # redirect already sent
        if fs_path == "":
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return None
        try:
            f = open(fs_path, "rb")
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return None
        try:
            st = os.fstat(f.fileno())
            size = st.st_size
            start, end = 0, size - 1
            rng = self.headers.get("Range")
            parsed = parse_range(rng, size) if (rng and status == HTTPStatus.OK and size) else "full"
            if parsed is None:
                f.close()
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            if parsed != "full":
                start, end = parsed
                self.send_response(HTTPStatus.PARTIAL_CONTENT)
                self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
            else:
                self.send_response(status)
            length = (end - start + 1) if size else 0
            self.send_header("Content-Type", self.guess_type(fs_path))
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Last-Modified", self.date_time_string(st.st_mtime))
            self.end_headers()
            f.seek(start)
            self._remaining = length
            return f
        except Exception:
            f.close()
            raise

    def copyfile(self, source, outputfile):
        remaining = getattr(self, "_remaining", None)
        try:
            if remaining is None:
                super().copyfile(source, outputfile)
                return
            while remaining > 0:
                chunk = source.read(min(65536, remaining))
                if not chunk:
                    break
                outputfile.write(chunk)
                remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the browser cancelled (normal for video seeking)

    # ---- logging -----------------------------------------------------------
    def log_request(self, code="-", size="-"):
        if self.quiet:
            return
        try:
            num = int(code)
        except (TypeError, ValueError):
            num = 0
        if self.verbose or num >= 400:
            sys.stderr.write("  %s %s %s\n" % (num or code, self.command, self.path))

    def log_message(self, format, *args):  # noqa: A002 (stdlib signature)
        if self.verbose and not self.quiet:
            super().log_message(format, *args)


def make_handler(root, spa=False, clean_urls=False, verbose=False, quiet=False):
    """Build a handler class bound to `root` with the given behaviour."""
    attrs = {"spa": spa, "clean_urls": clean_urls, "verbose": verbose, "quiet": quiet}
    handler = type("BoundPreviewHandler", (PreviewHandler,), attrs)
    return functools.partial(handler, directory=os.path.abspath(root))


def _port_in_use(host: str, port: int) -> bool:
    probe = "127.0.0.1" if host in ("", "0.0.0.0") else host
    try:
        with socket.create_connection((probe, port), timeout=0.25):
            return True
    except OSError:
        return False


def bind(host: str, port: int, handler, tries: int = 20) -> ThreadingHTTPServer:
    """Bind to `port`, or the next free port within `tries`. Port 0 picks any free port."""
    candidates = [0] if port == 0 else range(port, port + max(1, tries))
    last_error = None
    for p in candidates:
        if p and _port_in_use(host, p):
            last_error = OSError("port %d is in use" % p)
            continue
        try:
            server = ThreadingHTTPServer((host, p), handler)
            server.daemon_threads = True
            return server
        except OSError as exc:
            last_error = exc
    raise OSError("could not bind %s:%s (%s)" % (host, port, last_error))


def lan_ip():
    """Best-effort LAN address for testing on a phone. Sends no packets."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None
    finally:
        s.close()


def start(root, host="127.0.0.1", port=0, spa=False, clean_urls=False,
          verbose=False, quiet=True, tries=20):
    """Start a background server. Returns (server, base_url). Stop with stop(server)."""
    if not os.path.isdir(root):
        raise FileNotFoundError("not a directory: %s" % root)
    handler = make_handler(root, spa=spa, clean_urls=clean_urls, verbose=verbose, quiet=quiet)
    server = bind(host, port, handler, tries=tries)
    thread = threading.Thread(target=server.serve_forever, name="build-serve", daemon=True)
    thread.start()
    shown = "127.0.0.1" if host in ("", "0.0.0.0") else host
    return server, "http://%s:%d/" % (shown, server.server_address[1])


def stop(server) -> None:
    server.shutdown()
    server.server_close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="serve.py",
        description="Preview a static site locally the way static hosts serve it "
                    "(no-cache, modern MIME types, byte ranges, host-style 404s).",
        epilog="Example: python3 serve.py site/ --lan   (then open the printed URL)")
    ap.add_argument("dir", nargs="?", default=".", help="folder to serve (default: current folder)")
    ap.add_argument("--port", type=int, default=8000, help="port to try first (default 8000; 0 = any free port)")
    ap.add_argument("--host", default="127.0.0.1", help="address to bind (default 127.0.0.1, this computer only)")
    ap.add_argument("--lan", action="store_true", help="also listen on your Wi-Fi so a phone can open the site")
    ap.add_argument("--spa", action="store_true", help="serve index.html for unknown routes (single-page apps)")
    ap.add_argument("--clean-urls", action="store_true", help="serve about.html for /about (like Netlify, GitHub Pages)")
    ap.add_argument("--open", action="store_true", help="open the site in your default browser")
    ap.add_argument("--verbose", action="store_true", help="log every request (default: only 404s and errors)")
    ap.add_argument("--version", action="version", version="serve.py " + VERSION)
    args = ap.parse_args(argv)

    root = os.path.abspath(args.dir)
    if not os.path.isdir(root):
        print("serve.py: not a folder: %s" % args.dir, file=sys.stderr)
        return 2
    host = "0.0.0.0" if args.lan else args.host
    handler = make_handler(root, spa=args.spa, clean_urls=args.clean_urls, verbose=args.verbose)
    try:
        server = bind(host, args.port, handler)
    except OSError as exc:
        print("serve.py: %s" % exc, file=sys.stderr)
        return 2
    port = server.server_address[1]
    local = "http://127.0.0.1:%d/" % port
    print("Serving %s" % root)
    print("  Local:  %s" % local)
    if args.lan:
        ip = lan_ip()
        if ip:
            print("  Phone:  http://%s:%d/   (same Wi-Fi)" % (ip, port))
        else:
            print("  Phone:  no Wi-Fi address found")
    if not os.path.isfile(os.path.join(root, "index.html")) and not args.spa:
        print("  Note:   no index.html in this folder, so / will 404")
    modes = [m for m, on in (("spa fallback", args.spa), ("clean urls", args.clean_urls)) if on]
    if modes:
        print("  Mode:   " + ", ".join(modes))
    print("Logging 404s and errors. Ctrl+C to stop.")
    sys.stdout.flush()
    if args.open:
        webbrowser.open(local)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
