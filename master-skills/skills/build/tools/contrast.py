#!/usr/bin/env python3
"""contrast.py: check WCAG contrast for text/background color pairs.

Part of the BUILD master skill (github.com/Jakeschincariol/master-skills).
Python 3 standard library only.

Reads hex (#rgb, #rrggbb, #rrggbbaa), rgb()/rgba(), hsl()/hsla(), oklch() and
common color names. It can also read your CSS custom properties, so you check
the actual tokens instead of retyping them. When a pair fails it suggests the
nearest passing color with the same hue (lightness adjusted in OKLCH).

Examples:
  python3 contrast.py "#6b7280" "#ffffff"
  python3 contrast.py "oklch(55% 0.12 250)" white --min large
  python3 contrast.py --css site/styles.css --pair ink:paper --pair muted:paper --pair paper:accent
  python3 contrast.py --css site/styles.css --dark --pair ink:paper

Thresholds (--min): text 4.5 (default, WCAG AA body text), large 3 (AA text
from 24px, or 18.66px bold), ui 3 (icons, input borders, focus rings), aaa 7.

Exit codes: 0 every pair passes, 1 at least one pair fails, 2 bad input.
"""
from __future__ import annotations

import argparse
import colorsys
import json
import math
import re
import sys

VERSION = "1.0.0"
THRESHOLDS = {"text": 4.5, "large": 3.0, "ui": 3.0, "aaa": 7.0}

NAMED = {
    "black": "#000000", "white": "#ffffff", "gray": "#808080", "grey": "#808080",
    "silver": "#c0c0c0", "red": "#ff0000", "maroon": "#800000", "yellow": "#ffff00",
    "olive": "#808000", "lime": "#00ff00", "green": "#008000", "aqua": "#00ffff",
    "cyan": "#00ffff", "teal": "#008080", "blue": "#0000ff", "navy": "#000080",
    "fuchsia": "#ff00ff", "magenta": "#ff00ff", "purple": "#800080", "orange": "#ffa500",
    "pink": "#ffc0cb", "brown": "#a52a2a", "gold": "#ffd700", "indigo": "#4b0082",
    "transparent": "#00000000",
}


class ColorError(ValueError):
    pass


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def _num(token: str, scale: float = 1.0) -> float:
    token = token.strip()
    if token.endswith("%"):
        return float(token[:-1]) / 100.0 * scale
    return float(token)


def _hue(token: str) -> float:
    t = token.strip().lower()
    if t.endswith("deg"):
        return float(t[:-3])
    if t.endswith("turn"):
        return float(t[:-4]) * 360.0
    if t.endswith("rad"):
        return math.degrees(float(t[:-3]))
    if t.endswith("grad"):
        return float(t[:-4]) * 0.9
    return float(t)


def _args(inner: str):
    """Split 'a b c / d' or 'a, b, c, d' into ([a, b, c], alpha or None)."""
    alpha = None
    if "/" in inner:
        inner, alpha_text = inner.split("/", 1)
        alpha = _num(alpha_text)
    parts = [p for p in re.split(r"[\s,]+", inner.strip()) if p]
    if alpha is None and len(parts) == 4:
        alpha = _num(parts.pop())
    return parts, alpha


def parse_color(text: str):
    """Return (r, g, b, a) with channels in 0..1. Raises ColorError."""
    s = (text or "").strip().lower()
    if s in NAMED:
        s = NAMED[s]
    try:
        if s.startswith("#"):
            h = s[1:]
            if len(h) in (3, 4):
                h = "".join(c * 2 for c in h)
            if len(h) not in (6, 8) or not re.fullmatch(r"[0-9a-f]+", h):
                raise ColorError("bad hex color: %s" % text)
            vals = [int(h[i:i + 2], 16) / 255.0 for i in range(0, len(h), 2)]
            return tuple(vals) if len(vals) == 4 else (vals[0], vals[1], vals[2], 1.0)
        m = re.fullmatch(r"(rgba?|hsla?|oklch)\((.*)\)", s)
        if not m:
            raise ColorError("unsupported color: %s" % text)
        fn, (parts, alpha) = m.group(1), _args(m.group(2))
        if len(parts) != 3:
            raise ColorError("expected 3 channels in %s" % text)
        a = 1.0 if alpha is None else alpha
        if fn.startswith("rgb"):
            r, g, b = (_num(p, 255.0) / 255.0 for p in parts)
            return _clamp(r), _clamp(g), _clamp(b), _clamp(a)
        if fn.startswith("hsl"):
            hue = _hue(parts[0]) % 360.0
            sat, light = _num(parts[1]), _num(parts[2])
            if not parts[1].endswith("%"):
                sat /= 100.0
            if not parts[2].endswith("%"):
                light /= 100.0
            r, g, b = colorsys.hls_to_rgb(hue / 360.0, _clamp(light), _clamp(sat))
            return r, g, b, _clamp(a)
        # oklch(L C H): L as 0..1 or %, C as number (or % of 0.4), H in degrees.
        light = _num(parts[0])
        chroma = _num(parts[1], 0.4)
        hue = 0.0 if parts[2] == "none" else _hue(parts[2])
        r, g, b = oklch_to_srgb(light, chroma, hue)
        return r, g, b, _clamp(a)
    except (ValueError, IndexError) as exc:
        if isinstance(exc, ColorError):
            raise
        raise ColorError("could not read color %r (%s)" % (text, exc))


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


# --------------------------------------------------------------------------
# Color math (WCAG 2.x luminance, OKLab/OKLCH conversions)
# --------------------------------------------------------------------------
def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_gamma(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def luminance(rgb) -> float:
    r, g, b = (_to_linear(c) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(fg, bg) -> float:
    """WCAG contrast ratio. Alpha in fg is composited over bg; bg alpha over white."""
    bg_rgb = composite(bg, (1.0, 1.0, 1.0, 1.0))
    fg_rgb = composite(fg, bg_rgb + (1.0,))
    l1, l2 = luminance(fg_rgb), luminance(bg_rgb)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def composite(top, under):
    a = top[3] if len(top) > 3 else 1.0
    return tuple(top[i] * a + under[i] * (1 - a) for i in range(3))


def srgb_to_oklch(rgb):
    r, g, b = (_to_linear(c) for c in rgb[:3])
    l_ = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m_ = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s_ = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in (l_, m_, s_))
    light = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return light, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360.0


def _oklch_to_linear(light, chroma, hue):
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    l_ = (light + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (light - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (light - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
            -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
            -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)


def oklch_to_srgb(light, chroma, hue):
    """OKLCH to sRGB 0..1, reducing chroma until the color fits the sRGB gamut."""
    light = _clamp(light)
    lo, hi = 0.0, max(0.0, chroma)
    lin = _oklch_to_linear(light, hi, hue)
    if all(-1e-6 <= c <= 1 + 1e-6 for c in lin):
        return tuple(_clamp(_to_gamma(_clamp(c))) for c in lin)
    for _ in range(24):
        mid = (lo + hi) / 2
        lin = _oklch_to_linear(light, mid, hue)
        if all(-1e-6 <= c <= 1 + 1e-6 for c in lin):
            lo = mid
        else:
            hi = mid
    lin = _oklch_to_linear(light, lo, hue)
    return tuple(_clamp(_to_gamma(_clamp(c))) for c in lin)


def to_hex(rgb) -> str:
    return "#" + "".join("%02x" % int(round(_clamp(c) * 255)) for c in rgb[:3])


def suggest(fg, bg, target: float):
    """Nearest color with fg's hue and chroma whose contrast against bg meets target.

    Moves OKLCH lightness away from the background. Returns (hex, ratio) or None.
    """
    bg_rgb = composite(bg, (1.0, 1.0, 1.0, 1.0))
    light, chroma, hue = srgb_to_oklch(composite(fg, bg_rgb + (1.0,)))
    bg_light = srgb_to_oklch(bg_rgb)[0]
    for direction in ((-1, 1) if bg_light >= 0.5 else (1, -1)):
        end = 0.0 if direction < 0 else 1.0
        cand = oklch_to_srgb(end, chroma, hue) + (1.0,)
        if ratio(cand, bg_rgb + (1.0,)) < target:
            continue
        lo, hi = light, end  # lo fails (or is the start), hi passes
        for _ in range(30):
            mid = (lo + hi) / 2
            if ratio(oklch_to_srgb(mid, chroma, hue) + (1.0,), bg_rgb + (1.0,)) >= target:
                hi = mid
            else:
                lo = mid
        rgb = oklch_to_srgb(hi, chroma, hue)
        # Round to hex and nudge one more step if rounding fell just short.
        for _ in range(8):
            hexed = parse_color(to_hex(rgb))
            r = ratio(hexed, bg_rgb + (1.0,))
            if r >= target:
                return to_hex(rgb), r
            hi = hi + direction * 0.005
            rgb = oklch_to_srgb(_clamp(hi), chroma, hue)
    return None


# --------------------------------------------------------------------------
# CSS custom properties
# --------------------------------------------------------------------------
_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_VAR_DEF = re.compile(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;{}]+)")


def _dark_blocks(css: str):
    out = []
    for m in re.finditer(r"@media[^{]*prefers-color-scheme\s*:\s*dark[^{]*\{", css, re.I):
        depth, i = 1, m.end()
        while i < len(css) and depth:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        out.append(css[m.end():i - 1])
    return out


def read_vars(css: str, dark: bool = False) -> dict:
    """Custom properties from CSS. First definition wins; --dark applies the
    prefers-color-scheme: dark overrides (and [data-theme=dark] blocks) on top."""
    css = _COMMENT.sub("", css)
    found = {}
    for name, value in _VAR_DEF.findall(css):
        found.setdefault(name, value.strip())
    if dark:
        overrides = _dark_blocks(css)
        for m in re.finditer(r"\[data-theme=[\"']?dark[\"']?\][^{]*\{([^}]*)\}", css, re.I):
            overrides.append(m.group(1))
        for block in overrides:
            for name, value in _VAR_DEF.findall(block):
                found[name] = value.strip()
    return found


def resolve_token(token: str, variables: dict, depth: int = 0) -> str:
    t = token.strip()
    if depth > 10:
        raise ColorError("var() loop at %s" % token)
    m = re.fullmatch(r"var\(\s*(--[A-Za-z0-9_-]+)\s*(?:,\s*(.+))?\)", t)
    if m:
        name, fallback = m.group(1), m.group(2)
        if name in variables:
            return resolve_token(variables[name], variables, depth + 1)
        if fallback:
            return resolve_token(fallback, variables, depth + 1)
        raise ColorError("undefined variable %s" % name)
    if variables and (t.startswith("--") or ("--" + t) in variables):
        name = t if t.startswith("--") else "--" + t
        if name not in variables:
            raise ColorError("undefined variable %s" % name)
        return resolve_token(variables[name], variables, depth + 1)
    return t


def split_pair(text: str):
    for sep in (" on ", ":", "/"):
        if sep in text and not text.strip().startswith(("rgb", "hsl", "oklch")):
            left, right = text.split(sep, 1)
            return left.strip(), right.strip()
    raise ColorError("pair must look like fg:bg, fg/bg or 'fg on bg': %s" % text)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def check(pairs, minimum: str):
    target = THRESHOLDS[minimum]
    rows = []
    for label_fg, fg_text, label_bg, bg_text in pairs:
        fg, bg = parse_color(fg_text), parse_color(bg_text)
        r = ratio(fg, bg)
        row = {"fg": label_fg, "bg": label_bg, "fg_color": fg_text, "bg_color": bg_text,
               "ratio": round(r, 2), "aa_text": r >= 4.5, "aa_large": r >= 3.0,
               "aaa_text": r >= 7.0, "pass": r >= target, "required": target}
        if not row["pass"]:
            s = suggest(fg, bg, target)
            if s:
                row["suggest"] = {"color": s[0], "ratio": round(s[1], 2)}
        rows.append(row)
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="contrast.py",
        description="Check WCAG contrast for color pairs, from literal colors or your CSS tokens.",
        epilog='Examples: contrast.py "#777" white | contrast.py --css styles.css --pair ink:paper')
    ap.add_argument("colors", nargs="*", help="pairs of colors: FG BG [FG BG ...]")
    ap.add_argument("--css", metavar="FILE", help="read --custom-properties from this CSS file")
    ap.add_argument("--pair", action="append", default=[], metavar="FG:BG",
                    help="pair of token names or colors, e.g. ink:paper or '--muted on --bg' (repeatable)")
    ap.add_argument("--dark", action="store_true", help="use the dark theme overrides from --css")
    ap.add_argument("--min", choices=sorted(THRESHOLDS), default="text",
                    help="required level: text 4.5 (default), large 3, ui 3, aaa 7")
    ap.add_argument("--json", action="store_true", help="print JSON")
    ap.add_argument("--version", action="version", version="contrast.py " + VERSION)
    args = ap.parse_args(argv)

    if len(args.colors) % 2:
        print("contrast.py: colors must come in FG BG pairs", file=sys.stderr)
        return 2
    variables = {}
    if args.css:
        try:
            with open(args.css, encoding="utf-8") as fh:
                variables = read_vars(fh.read(), dark=args.dark)
        except OSError as exc:
            print("contrast.py: %s" % exc, file=sys.stderr)
            return 2
    pairs = []
    try:
        for i in range(0, len(args.colors), 2):
            fg, bg = args.colors[i], args.colors[i + 1]
            pairs.append((fg, resolve_token(fg, variables), bg, resolve_token(bg, variables)))
        for item in args.pair:
            fg, bg = split_pair(item)
            pairs.append((fg, resolve_token(fg, variables), bg, resolve_token(bg, variables)))
        if not pairs:
            ap.print_usage(sys.stderr)
            print("contrast.py: give FG BG colors or --pair (with --css for token names)", file=sys.stderr)
            return 2
        rows = check(pairs, args.min)
    except ColorError as exc:
        print("contrast.py: %s" % exc, file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"tool": "contrast", "version": VERSION, "min": args.min, "pairs": rows}, indent=2))
    else:
        need = THRESHOLDS[args.min]
        for row in rows:
            fg = row["fg"] if row["fg"] == row["fg_color"] else "%s (%s)" % (row["fg"], row["fg_color"])
            bg = row["bg"] if row["bg"] == row["bg_color"] else "%s (%s)" % (row["bg"], row["bg_color"])
            verdict = "PASS" if row["pass"] else "FAIL"
            levels = "AA text %s, AA large %s, AAA %s" % tuple(
                "yes" if row[k] else "no" for k in ("aa_text", "aa_large", "aaa_text"))
            print("%s  %5.2f:1  %s on %s  [%s]" % (verdict, row["ratio"], fg, bg, levels))
            if "suggest" in row:
                print("        try %s for the foreground (%.2f:1, same hue)"
                      % (row["suggest"]["color"], row["suggest"]["ratio"]))
        failed = sum(1 for r in rows if not r["pass"])
        print("%d of %d pairs meet %.1f:1 (%s)." % (len(rows) - failed, len(rows), need, args.min))
    return 1 if any(not r["pass"] for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
