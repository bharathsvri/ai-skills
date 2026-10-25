"""Shared helpers for the edit skill's tools. Python 3.8+ standard library only.

Not a command line tool. probe.py, deadspace.py, captions.py, stopmotion.py and
finish.py import it for: finding ffmpeg/ffprobe, running them with readable
errors, probing media (rotation, VFR, HDR, audio layout), detecting which
filters this ffmpeg build has, a fast speech envelope, loudness measurement,
and loading word timings from any common transcript format.

Part of github.com/Jakeschincariol/master-skills (MIT).
"""
from __future__ import annotations

import array
import json
import math
import operator
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_MISSING = 3

EXIT_CODES_HELP = """exit codes:
  0  success
  1  ffmpeg or runtime failure
  2  bad input or arguments (missing file, no audio stream, ...)
  3  a required program or feature is missing (ffmpeg, faster-whisper, libass)"""

FFMPEG_INSTALL_HINT = (
    "Install ffmpeg first (macOS: brew install ffmpeg, Debian/Ubuntu: sudo apt install ffmpeg), "
    "or point EDIT_FFMPEG / EDIT_FFPROBE at the binaries."
)

# Instagram Reels / TikTok / Shorts safe area on a 1080x1920 canvas (house rule):
# the header covers y < 240, the caption/username block covers y > 1470,
# the like/comment/share rail covers x > 950 from y 1000 down, and tall phones
# crop about 8% off each side (x < 90 and x > 990 can disappear).
SAFE_AREA_9x16 = {"x0": 90, "y0": 240, "x1": 950, "y1": 1470}

STANDARD_RATES = [
    Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001), Fraction(30),
    Fraction(48), Fraction(50), Fraction(60000, 1001), Fraction(60), Fraction(120),
]


class EditError(Exception):
    """An error with a message for the user and the exit code to return."""

    def __init__(self, message: str, code: int = EXIT_FAIL):
        super().__init__(message)
        self.code = code


def run_main(main_fn) -> int:
    """Run a tool's main(), turning EditError into a clean message + exit code."""
    try:
        return int(main_fn() or 0)
    except EditError as err:
        print(f"error: {err}", file=sys.stderr)
        return err.code
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


# ---------------------------------------------------------------------------
# ffmpeg / ffprobe
# ---------------------------------------------------------------------------

def _find_binary(name: str, env_var: str) -> str:
    override = os.environ.get(env_var)
    if override:
        return override
    found = shutil.which(name)
    if not found:
        raise EditError(f"{name} not found on PATH. {FFMPEG_INSTALL_HINT}", EXIT_MISSING)
    return found


def ffmpeg_bin() -> str:
    return _find_binary("ffmpeg", "EDIT_FFMPEG")


def ffprobe_bin() -> str:
    return _find_binary("ffprobe", "EDIT_FFPROBE")


def _short_cmd(cmd) -> str:
    text = shlex.join(str(c) for c in cmd)
    return text if len(text) < 1500 else text[:1500] + " ..."


def run(cmd, *, cwd=None, check=True, timeout=None) -> subprocess.CompletedProcess:
    """Run a command, capture text output, raise EditError with the stderr tail on failure."""
    try:
        proc = subprocess.run(
            [str(c) for c in cmd], cwd=cwd, capture_output=True, text=True,
            errors="replace", timeout=timeout,
        )
    except FileNotFoundError as err:
        raise EditError(f"cannot run {cmd[0]}: {err}", EXIT_MISSING)
    if check and proc.returncode != 0:
        tail = (proc.stderr or "").strip()[-2500:]
        raise EditError(
            f"{os.path.basename(str(cmd[0]))} failed (exit {proc.returncode}):\n{tail}\n"
            f"command: {_short_cmd(cmd)}",
            EXIT_FAIL,
        )
    return proc


_CACHE: dict = {}


def ffmpeg_version() -> tuple | None:
    """(major, minor) of ffmpeg, or None for git builds without a release number."""
    if "version" not in _CACHE:
        first = run([ffmpeg_bin(), "-hide_banner", "-version"]).stdout.splitlines()[:1]
        match = re.search(r"version\s+n?(\d+)\.(\d+)", first[0] if first else "")
        _CACHE["version"] = (int(match.group(1)), int(match.group(2))) if match else None
        _CACHE["version_line"] = first[0] if first else ""
    return _CACHE["version"]


def ffmpeg_filters() -> set:
    """Names of every filter this ffmpeg build has (ass, subtitles, drawtext vary by build)."""
    if "filters" not in _CACHE:
        out = run([ffmpeg_bin(), "-hide_banner", "-filters"]).stdout
        names = set()
        for line in out.splitlines():
            match = re.match(r"^\s*[A-Z.|]{2,3}\s+(\S+)\s+\S*->\S*", line)
            if match:
                names.add(match.group(1))
        _CACHE["filters"] = names
    return _CACHE["filters"]


def has_filter(name: str) -> bool:
    return name in ffmpeg_filters()


def filter_options(name: str) -> set:
    """Option names a filter accepts on this build (e.g. alimiter 'latency' is newer)."""
    key = f"opts:{name}"
    if key not in _CACHE:
        out = run([ffmpeg_bin(), "-hide_banner", "-h", f"filter={name}"], check=False).stdout
        _CACHE[key] = set(re.findall(r"^\s{2,}([a-z_0-9]+)\s+<", out, flags=re.M))
    return _CACHE[key]


def ffmpeg_encoders() -> set:
    if "encoders" not in _CACHE:
        out = run([ffmpeg_bin(), "-hide_banner", "-encoders"]).stdout
        _CACHE["encoders"] = set(re.findall(r"^\s*[VAS][A-Z.]{5}\s+(\S+)", out, flags=re.M))
    return _CACHE["encoders"]


def has_encoder(name: str) -> bool:
    return name in ffmpeg_encoders()


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------

def _num(value, default=None):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _frac(value):
    try:
        out = Fraction(str(value))
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return out if out > 0 else None


def _video_info(s: dict, fmt_start: float) -> dict:
    width, height = int(s.get("width") or 0), int(s.get("height") or 0)
    rotation = 0
    for side in s.get("side_data_list") or []:
        if "rotation" in side:
            rotation = int(round(_num(side["rotation"], 0)))
    tags = s.get("tags") or {}
    if not rotation and "rotate" in tags:
        rotation = int(_num(tags["rotate"], 0))
    rotation %= 360
    disp_w, disp_h = (height, width) if rotation in (90, 270) else (width, height)
    r_rate, avg_rate = _frac(s.get("r_frame_rate")), _frac(s.get("avg_frame_rate"))
    fps = avg_rate or r_rate
    vfr = bool(r_rate and avg_rate and abs(float(r_rate) - float(avg_rate)) > 0.01 * float(r_rate))
    pix_fmt = s.get("pix_fmt") or ""
    depth = int(_num(s.get("bits_per_raw_sample"), 0) or 0)
    if not depth:
        depth = 12 if "12" in pix_fmt else 10 if "10" in pix_fmt else 8
    transfer = s.get("color_transfer")
    start = _num(s.get("start_time"), fmt_start)
    nb_frames = s.get("nb_frames")
    return {
        "index": s.get("index"),
        "codec": s.get("codec_name"),
        "profile": s.get("profile"),
        "width": width,
        "height": height,
        "rotation": rotation,
        "display_width": disp_w,
        "display_height": disp_h,
        "pix_fmt": pix_fmt,
        "bit_depth": depth,
        "fps": float(fps) if fps else None,
        "r_frame_rate": str(r_rate) if r_rate else None,
        "avg_frame_rate": str(avg_rate) if avg_rate else None,
        "vfr": vfr,
        "color_primaries": s.get("color_primaries"),
        "color_transfer": transfer,
        "color_space": s.get("color_space"),
        "color_range": s.get("color_range"),
        "hdr": transfer in ("arib-std-b67", "smpte2084"),
        "start": start,
        "offset": max(0.0, start - fmt_start),
        "duration": _num(s.get("duration")),
        "nb_frames": int(nb_frames) if str(nb_frames or "").isdigit() else None,
    }


def _audio_info(s: dict, fmt_start: float, order: int) -> dict:
    start = _num(s.get("start_time"), fmt_start)
    return {
        "index": s.get("index"),
        "order": order,
        "codec": s.get("codec_name"),
        "sample_rate": int(_num(s.get("sample_rate"), 0) or 0),
        "channels": int(s.get("channels") or 0),
        "channel_layout": s.get("channel_layout"),
        "start": start,
        "offset": max(0.0, start - fmt_start),
        "duration": _num(s.get("duration")),
        "bit_rate": int(_num(s.get("bit_rate"), 0) or 0) or None,
    }


def probe(path: str) -> dict:
    """Summarize a media file. Times use ffmpeg's filter timeline (format start = 0)."""
    if not os.path.isfile(path):
        raise EditError(f"file not found: {path}", EXIT_USAGE)
    proc = run([ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format",
                "-show_streams", path], check=False)
    if proc.returncode != 0:
        raise EditError(f"ffprobe cannot read {path}: {(proc.stderr or '').strip()[-400:]}", EXIT_USAGE)
    data = json.loads(proc.stdout or "{}")
    fmt = data.get("format") or {}
    fmt_start = _num(fmt.get("start_time"), 0.0)
    video, audio_streams = None, []
    for stream in data.get("streams") or []:
        kind = stream.get("codec_type")
        if kind == "video":
            if (stream.get("disposition") or {}).get("attached_pic"):
                continue  # cover art inside an audio file, not a picture track
            if video is None:
                video = _video_info(stream, fmt_start)
        elif kind == "audio":
            audio_streams.append(_audio_info(stream, fmt_start, len(audio_streams)))
    duration = _num(fmt.get("duration"))
    ends = []
    if video and video["duration"]:
        ends.append(video["offset"] + video["duration"])
    if audio_streams and audio_streams[0]["duration"]:
        ends.append(audio_streams[0]["offset"] + audio_streams[0]["duration"])
    if not ends and duration:
        ends.append(duration)
    return {
        "path": os.path.abspath(path),
        "format": fmt.get("format_name"),
        "duration": duration,
        "end": min(ends) if ends else duration,
        "size": int(_num(fmt.get("size"), 0) or 0),
        "bit_rate": int(_num(fmt.get("bit_rate"), 0) or 0) or None,
        "video": video,
        "audio": audio_streams[0] if audio_streams else None,
        "audio_streams": audio_streams,
    }


def cfr_rate(video: dict) -> Fraction:
    """The constant frame rate to edit at: the source rate, snapped to a standard rate if close."""
    r_rate, avg_rate = _frac(video.get("r_frame_rate")), _frac(video.get("avg_frame_rate"))
    base = r_rate if (r_rate and r_rate <= 121) else (avg_rate or r_rate or Fraction(30))
    best = min(STANDARD_RATES, key=lambda c: abs(float(c - base)) / float(c))
    if abs(float(best - base)) / float(best) <= 0.02:
        return best
    return Fraction(base).limit_denominator(1001)


def is_image_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_EXTS


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")


def parse_size(text: str) -> tuple:
    match = re.fullmatch(r"\s*(\d+)\s*[xX:]\s*(\d+)\s*", text or "")
    if not match:
        raise EditError(f"bad size {text!r}, expected WIDTHxHEIGHT like 1080x1920", EXIT_USAGE)
    width, height = int(match.group(1)), int(match.group(2))
    if width < 16 or height < 16 or width % 2 or height % 2:
        raise EditError(f"size {width}x{height} must be even and at least 16 px", EXIT_USAGE)
    return width, height


def video_codec_args(video: dict, crf: int = 18, preset: str = "medium") -> tuple:
    """Encoder arguments that keep the picture honest: HDR stays 10-bit HEVC with its
    colour tags, everything else becomes H.264 yuv420p with the source's colour tags."""
    tags = []
    for key, flag in (("color_primaries", "-color_primaries"), ("color_transfer", "-color_trc"),
                      ("color_space", "-colorspace")):
        value = video.get(key)
        if value and value not in ("unknown", "reserved", "unspecified"):
            tags += [flag, value]
    if video.get("hdr") and has_encoder("libx265"):
        return (["-c:v", "libx265", "-crf", str(crf), "-preset", preset, "-pix_fmt", "yuv420p10le",
                 "-tag:v", "hvc1", "-x265-params", "log-level=error"] + tags,
                "HEVC 10-bit (HDR kept)")
    if has_encoder("libx264"):
        note = "H.264 8-bit"
        if video.get("hdr"):
            note += " (HDR source without libx265: colours are not tone mapped)"
        return (["-c:v", "libx264", "-crf", str(crf), "-preset", preset, "-pix_fmt", "yuv420p"] + tags,
                note)
    raise EditError("this ffmpeg has no libx264 encoder; install a full ffmpeg build", EXIT_MISSING)


# ---------------------------------------------------------------------------
# Audio envelope and loudness
# ---------------------------------------------------------------------------

def audio_envelope(path: str, info: dict, stream: int = 0, hop: float = 0.01,
                   rate: int = 16000, highpass: float = 70.0) -> list:
    """Short-term level in dBFS every `hop` seconds (power averaged over channels, so
    stereo phase never cancels). Frame i covers [offset + i*hop, offset + (i+1)*hop)."""
    streams = info.get("audio_streams") or []
    if stream >= len(streams):
        raise EditError(f"{os.path.basename(path)} has no audio stream #{stream}", EXIT_USAGE)
    channels = max(1, streams[stream]["channels"] or 1)
    filters = ([f"highpass=f={highpass:g}"] if highpass else []) + [f"aresample={rate}"]
    cmd = [ffmpeg_bin(), "-nostdin", "-hide_banner", "-v", "error", "-i", path,
           "-map", f"0:a:{stream}", "-vn", "-sn", "-dn", "-af", ",".join(filters),
           "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1"]
    hop_samples = max(1, int(round(rate * hop))) * channels
    frame_bytes = hop_samples * 2
    full_scale = 32768.0 * 32768.0
    swap = sys.byteorder == "big"
    mul = operator.mul
    levels = []
    with tempfile.TemporaryFile() as errfile:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errfile)
        pending = b""
        while True:
            chunk = proc.stdout.read(frame_bytes * 1024)
            if not chunk:
                break
            pending += chunk
            whole = len(pending) // frame_bytes
            if not whole:
                continue
            samples = array.array("h")
            samples.frombytes(pending[: whole * frame_bytes])
            pending = pending[whole * frame_bytes:]
            if swap:
                samples.byteswap()
            for i in range(whole):
                window = samples[i * hop_samples:(i + 1) * hop_samples]
                power = sum(map(mul, window, window))
                levels.append(10 * math.log10(power / hop_samples / full_scale) if power else -120.0)
        tail = len(pending) - len(pending) % 2
        if tail >= 2:
            samples = array.array("h")
            samples.frombytes(pending[:tail])
            if swap:
                samples.byteswap()
            power = sum(map(mul, samples, samples))
            levels.append(10 * math.log10(power / len(samples) / full_scale) if power else -120.0)
        proc.stdout.close()
        code = proc.wait()
        errfile.seek(0)
        err = errfile.read().decode("utf-8", "replace").strip()
    if code != 0:
        raise EditError(f"ffmpeg could not decode the audio of {path}:\n{err[-1500:]}", EXIT_FAIL)
    return levels


def percentile(sorted_values: list, fraction: float) -> float:
    if not sorted_values:
        return float("nan")
    pos = min(len(sorted_values) - 1, max(0, int(round(fraction * (len(sorted_values) - 1)))))
    return sorted_values[pos]


def speech_levels(levels: list) -> dict:
    """Adaptive gate for phone talking-head takes: noise floor = 10th percentile of
    10 ms frames, speech = loud frames. The gate sits 30 dB under speech but never
    closer than 8 dB to the noise floor, so quiet takes and noisy rooms both work."""
    values = sorted(levels)
    if not values:
        raise EditError("the audio stream is empty", EXIT_USAGE)
    noise = percentile(values, 0.10)
    speech = max(percentile(values, 0.95), percentile(values, 0.99) - 6.0, values[-1] - 12.0)
    spread = speech - noise
    if spread >= 18.0:
        threshold = max(noise + 8.0, speech - 30.0)
    else:
        threshold = noise + spread * 0.5
    return {
        "noise_db": round(noise, 1),
        "speech_db": round(speech, 1),
        "threshold_db": round(threshold, 1),
        "spread_db": round(spread, 1),
        "reliable": spread >= 12.0,
    }


def measure_loudness(path: str, *, stream: int = 0, pre_filter: str = "") -> dict:
    """EBU R128 integrated loudness (LUFS), loudness range (LU) and true peak (dBTP)."""
    chain = (pre_filter + "," if pre_filter else "") + "ebur128=peak=true:framelog=verbose"
    proc = run([ffmpeg_bin(), "-nostdin", "-hide_banner", "-nostats", "-i", path,
                "-map", f"0:a:{stream}", "-af", chain, "-f", "null", "-"])
    return parse_ebur128(proc.stderr)


def parse_ebur128(stderr: str) -> dict:
    summary = stderr[stderr.rfind("Summary:"):] if "Summary:" in stderr else stderr

    def grab(label):
        match = re.search(rf"{label}:\s+(-?inf|-?\d+(?:\.\d+)?)", summary)
        if not match:
            return None
        return None if "inf" in match.group(1) else float(match.group(1))

    return {"integrated_lufs": grab("I"), "lra_lu": grab("LRA"), "true_peak_dbtp": grab("Peak")}


# ---------------------------------------------------------------------------
# Word timings (transcripts)
# ---------------------------------------------------------------------------

_START_KEYS = ("start", "start_time", "startTime", "t0", "begin")
_END_KEYS = ("end", "end_time", "endTime", "t1", "stop")
_TEXT_KEYS = ("punctuated_word", "text", "word", "token")


def _first(item: dict, keys):
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None


def _wordish(item) -> bool:
    if not isinstance(item, dict):
        return False
    has_time = _first(item, _START_KEYS) is not None or isinstance(item.get("offsets"), dict)
    return has_time and _first(item, _TEXT_KEYS) is not None


def _find_word_list(data):
    """Locate the word list in Scribe, Whisper, faster-whisper, whisper.cpp, Deepgram,
    AssemblyAI, HyperFrames or this skill's own JSON. Returns (items, kind)."""
    if isinstance(data, list):
        if data and all(_wordish(x) for x in data[:50]):
            return data, "list"
    if isinstance(data, dict):
        if isinstance(data.get("words"), list) and data["words"] and _wordish(data["words"][0]):
            return data["words"], "words"
        segments = data.get("segments")
        if isinstance(segments, list) and any(isinstance(s, dict) and s.get("words") for s in segments):
            return [w for s in segments if isinstance(s, dict) for w in (s.get("words") or [])], "segments"
        try:
            words = data["results"]["channels"][0]["alternatives"][0]["words"]
            if isinstance(words, list):
                return words, "deepgram"
        except (KeyError, IndexError, TypeError):
            pass
        if isinstance(data.get("transcription"), list):
            return data["transcription"], "whisper.cpp"
    best = []

    def walk(node):
        nonlocal best
        if isinstance(node, list):
            if len(node) > len(best) and node and all(_wordish(x) for x in node[:20]):
                best = node
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            for child in node.values():
                walk(child)

    walk(data)
    if best:
        return best, "search"
    raise EditError("no word timings found in that JSON (expected a list of {text, start, end})",
                    EXIT_USAGE)


def _clean_words(words: list) -> list:
    out = []
    for word in sorted(words, key=lambda w: (w["start"], w["end"])):
        text = re.sub(r"\s+", " ", str(word["text"])).strip()
        if not text:
            continue
        start = max(0.0, float(word["start"]))
        end = max(start + 0.01, float(word["end"]))
        item = {"text": text, "start": round(start, 3), "end": round(end, 3)}
        if word.get("prob") is not None:
            item["prob"] = round(float(word["prob"]), 3)
        out.append(item)
    return out


def load_words(path: str, media_duration: float | None = None) -> list:
    """Load word timings as [{text, start, end, prob?}] in seconds, sorted.
    Accepts JSON transcripts, or .srt/.vtt (word times spread inside each cue)."""
    if not os.path.isfile(path):
        raise EditError(f"transcript not found: {path}", EXIT_USAGE)
    ext = os.path.splitext(path)[1].lower()
    with open(path, encoding="utf-8-sig") as handle:
        raw = handle.read()
    if ext in (".srt", ".vtt"):
        return words_from_subtitles(raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as err:
        raise EditError(f"{path} is not valid JSON: {err}", EXIT_USAGE)
    items, kind = _find_word_list(data)
    words, all_int, max_end = [], True, 0.0
    for item in items:
        if not isinstance(item, dict) or item.get("type") in ("spacing", "audio_event"):
            continue
        text = _first(item, _TEXT_KEYS)
        if isinstance(item.get("offsets"), dict):
            start, end = item["offsets"].get("from"), item["offsets"].get("to")
            start, end = _num(start), _num(end)
            if start is not None:
                start, end = start / 1000.0, (end if end is not None else start) / 1000.0
        else:
            start, end = _num(_first(item, _START_KEYS)), _num(_first(item, _END_KEYS))
        if text is None or start is None:
            continue
        if end is None:
            end = start
        if isinstance(item.get("offsets"), dict):
            all_int = False
        elif not (float(start).is_integer() and float(end).is_integer()):
            all_int = False
        max_end = max(max_end, end)
        prob = _num(_first(item, ("probability", "confidence", "prob", "logprob")))
        words.append({"text": text, "start": start, "end": end,
                      "prob": prob if prob is not None and 0 <= prob <= 1 else None})
    if not words:
        raise EditError(f"{path} has no usable word timings", EXIT_USAGE)
    in_ms = max_end > 36000 or (all_int and max_end > 1000)
    if media_duration and max_end > media_duration * 2 and max_end / 1000.0 <= media_duration * 1.5:
        in_ms = True
    if in_ms:
        for word in words:
            word["start"] /= 1000.0
            word["end"] /= 1000.0
    return _clean_words(words)


_TS = r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})"


def _ts_seconds(match, offset: int) -> float:
    hours = int(match.group(offset) or 0)
    minutes, seconds = int(match.group(offset + 1)), int(match.group(offset + 2))
    frac = match.group(offset + 3)
    return hours * 3600 + minutes * 60 + seconds + int(frac) / (10 ** len(frac))


def words_from_subtitles(text: str) -> list:
    """SRT/VTT cues to approximate word timings (spread by character length).
    Good enough for caption chunking; cue boundaries stay exact."""
    words = []
    pattern = re.compile(_TS + r"\s*-->\s*" + _TS)
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip()]
        for i, line in enumerate(lines):
            match = pattern.search(line)
            if not match:
                continue
            start, end = _ts_seconds(match, 1), _ts_seconds(match, 5)
            body = " ".join(lines[i + 1:])
            body = re.sub(r"<[^>]+>|\{[^}]*\}", "", body)
            tokens = body.split()
            if not tokens or end <= start:
                break
            weights = [len(t) + 1 for t in tokens]
            total, cursor = float(sum(weights)), start
            for token, weight in zip(tokens, weights):
                span = (end - start) * weight / total
                words.append({"text": token, "start": cursor, "end": cursor + span * 0.92})
                cursor += span
            break
    if not words:
        raise EditError("no cues found in that subtitle file", EXIT_USAGE)
    return _clean_words(words)


def save_words(path: str, words: list, *, source: str | None = None, engine: str | None = None,
               language: str | None = None, extra: dict | None = None) -> dict:
    """Write word timings in a schema HyperFrames' caption workflow can also reuse as
    transcript.json: {text, language_code, words: [{text, start, end, type}]}."""
    doc = {
        "version": 1,
        "kind": "words",
        "text": " ".join(w["text"] for w in words),
        "language_code": language or "en",
        "engine": engine or "unknown",
    }
    if source and os.path.isfile(source):
        stat = os.stat(source)
        doc["source"] = {"path": os.path.abspath(source), "size": stat.st_size,
                         "mtime": round(stat.st_mtime, 3)}
    if extra:
        doc.update(extra)
    doc["words"] = []
    for word in words:
        item = {"text": word["text"], "start": round(word["start"], 3),
                "end": round(word["end"], 3), "type": "word"}
        if word.get("prob") is not None:
            item["prob"] = round(word["prob"], 3)
        doc["words"].append(item)
    write_json(path, doc)
    return doc


def phrase_lines(words: list, gap: float = 0.5, max_words: int = 16) -> list:
    """A packed, phrase-per-line view of a transcript: '[012.34-015.67] text'.
    Phrases break on pauses >= gap seconds, or at sentence ends once a line is long."""
    lines, current = [], []

    def flush():
        if current:
            lines.append(f"[{current[0]['start']:07.2f}-{current[-1]['end']:07.2f}] "
                         + " ".join(w["text"] for w in current))
            current.clear()

    for i, word in enumerate(words):
        if current:
            pause = word["start"] - current[-1]["end"]
            sentence_end = current[-1]["text"][-1:] in ".!?"
            if pause >= gap or len(current) >= max_words or (sentence_end and len(current) >= 8):
                flush()
        current.append(word)
    flush()
    return lines


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def write_json(path: str, obj) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=folder)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(obj, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)


def fmt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}:{rest:05.2f}"


def default_output(path: str, suffix: str, ext: str | None = None) -> str:
    stem, original_ext = os.path.splitext(path)
    return f"{stem}{suffix}{ext if ext is not None else original_ext}"


def stem_of(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]
