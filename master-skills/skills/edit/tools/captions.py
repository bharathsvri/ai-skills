#!/usr/bin/env python3
"""Word-timed captions: 1-3 word phrases as SRT, styled ASS and a JSON cue list.

  python3 captions.py take.cut.mp4 --words take.cut.words.json     # from word timings
  python3 captions.py take.mp4 --words-only                         # transcribe once (faster-whisper)
  python3 captions.py take.cut.mp4 --words w.json --burn final.mp4  # burn in if ffmpeg has libass

Writes <stem>.srt, <stem>.ass (bold, active word highlighted, inside the 9:16 safe zone),
<stem>.cues.json (phrases + per-word times for HyperFrames/Remotion), and when it
transcribes, <stem>.words.json + <stem>.phrases.txt. Burning in needs ffmpeg's ass or
subtitles filter (libass); without it the tool says so and you use the HyperFrames route.

Part of github.com/Jakeschincariol/master-skills (MIT).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mediakit as mk  # noqa: E402

FILLERS = {"um", "umm", "ummm", "uh", "uhh", "uhm", "er", "erm", "ah", "ahh", "hmm", "hm", "mm", "mmm"}
# words that open a phrase: a chunk should not end on them when the sentence continues
WEAK_ENDINGS = {"a", "an", "the", "to", "of", "and", "or", "but", "for", "in", "on", "at", "with",
                "from", "by", "into", "my", "your", "our", "their", "his", "her", "its", "if", "as",
                "is", "are", "was", "were", "will", "can"}
VERBATIM_PROMPT = "Um, so, uh, I mean, like, you know, uh, okay. Hmm, um, let me, uh, think."
INSTALL_HINT = (
    "faster-whisper is not installed, so I cannot transcribe. Either install it "
    "(python3 -m venv ~/.venvs/edit && ~/.venvs/edit/bin/pip install faster-whisper, then run this "
    "tool with ~/.venvs/edit/bin/python; the model downloads on first use), or pass --words with "
    "word timings from any transcriber: ElevenLabs Scribe, Whisper/faster-whisper JSON with word "
    "timestamps, whisper.cpp JSON, Deepgram, AssemblyAI, HyperFrames transcript.json, or an SRT/VTT "
    "(word times approximated inside each cue)."
)


def norm(text: str) -> str:
    return re.sub(r"[^\w']+", "", text.lower()).strip("'")


def display_text(text: str, case: str, keep_punct: bool) -> str:
    if not keep_punct:
        text = re.sub(r"[,;:]+$", "", text)
        if text.endswith(".") and text.count(".") == 1:
            text = text[:-1]
    return text.upper() if case == "upper" else text.lower() if case == "lower" else text


def chunk_words(words: list, max_words: int = 3, max_chars: int = 18, pause: float = 0.3,
                min_dur: float = 0.3) -> list:
    """Group words into caption phrases. Break after . ! ? (and after commas once a phrase
    has 2 words), on pauses >= `pause`, at max_words / max_chars, never end a full phrase
    on a weak opener ('the', 'to', ...), and grow a phrase rather than flash it < min_dur."""
    chunks, cur = [], []
    for i, word in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else None
        cur.append(word)
        text_len = len(" ".join(w["text"] for w in cur))
        hard = word["text"][-1:] in ".!?" or nxt is None or nxt["start"] - word["end"] >= pause
        soft = word["text"][-1:] in ",;:" and len(cur) >= 2
        nxt_len = text_len + 1 + len(nxt["text"]) if nxt else 0
        full = len(cur) >= max_words or (nxt is not None and nxt_len > max_chars)
        if not (hard or soft or full):
            continue
        if (not hard and len(cur) < max_words and nxt is not None and nxt_len <= max_chars + 4
                and nxt["end"] - cur[0]["start"] < 1.2 and word["end"] - cur[0]["start"] < min_dur):
            continue  # too quick to read: let it grow by one word
        if full and not hard and len(cur) >= 2 and norm(word["text"]) in WEAK_ENDINGS:
            carry = cur.pop()
            chunks.append(cur)
            cur = [carry]
            continue
        chunks.append(cur)
        cur = []
    if cur:
        chunks.append(cur)
    cues = []
    for i, group in enumerate(chunks):
        start = group[0]["start"]
        end = group[-1]["end"]
        if i + 1 < len(chunks):
            next_start = chunks[i + 1][0]["start"]
            end = next_start if next_start - end <= 0.5 else end + 0.25
            end = min(max(end, start + min_dur), next_start)
        else:
            end = max(end + 0.25, start + min_dur)
        cues.append({"start": round(start, 3), "end": round(end, 3), "words": group})
    return cues


def srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def ass_color(hex_color: str, alpha: int = 0) -> str:
    h = hex_color.lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        raise mk.EditError(f"bad colour {hex_color!r}, use #RRGGBB", mk.EXIT_USAGE)
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def layout(width: int, height: int, position: str, y: int | None) -> dict:
    """Caption anchor. 9:16: lower = text bottom at 75% height (y 1440 of 1920, chest or collar,
    under the IG caption block line of 1470); seam = centred on a split-screen seam; top = just
    under the 240 px header. Side margins keep text clear of the right-hand button rail."""
    vertical = height > width
    margin_x = int(round(width * (0.13 if vertical else 0.08)))
    if position == "lower":
        bottom = y if y is not None else int(round(height * (0.75 if vertical else 0.92)))
        return {"align": 2, "margin_v": height - bottom, "anchor_y": bottom, "margin_x": margin_x}
    if position == "top":
        top = y if y is not None else int(round(height * (0.135 if vertical else 0.06)))
        return {"align": 8, "margin_v": top, "anchor_y": top, "margin_x": margin_x}
    centre = y if y is not None else height // 2
    return {"align": 5, "margin_v": 0, "anchor_y": centre, "margin_x": margin_x, "pos": True}


def build_ass(cues: list, width: int, height: int, args) -> str:
    lay = layout(width, height, args.position, args.y)
    size = args.font_size or int(round(height * (0.044 if height > width else 0.06)))
    outline = max(2, int(round(size * 0.075)))
    head = [
        "[Script Info]", "; made by master-skills edit/captions.py", "ScriptType: v4.00+",
        f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0", "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Caption,{args.font},{size},{ass_color(args.color)},{ass_color(args.color)},"
        f"&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{outline},2,{lay['align']},"
        f"{lay['margin_x']},{lay['margin_x']},{lay['margin_v']},1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    pos = f"{{\\an5\\pos({width // 2},{lay['anchor_y']})}}" if lay.get("pos") else ""
    accent = ass_color(args.accent)
    events = []
    for cue in cues:
        texts = [w["display"] for w in cue["words"]]
        if args.no_highlight:
            events.append((cue["start"], cue["end"], pos + " ".join(texts)))
            continue
        for k, word in enumerate(cue["words"]):
            start = cue["start"] if k == 0 else word["start"]
            end = cue["end"] if k == len(cue["words"]) - 1 else cue["words"][k + 1]["start"]
            if end <= start:
                continue
            parts = [f"{{\\c{accent}&}}{t}{{\\r}}" if j == k else t for j, t in enumerate(texts)]
            events.append((start, end, pos + " ".join(parts)))
    lines = [f"Dialogue: 0,{ass_time(s)},{ass_time(e)},Caption,,0,0,0,,{text}" for s, e, text in events]
    return "\n".join(head + lines) + "\n"


def transcribe(media: str, args) -> tuple:
    try:
        from faster_whisper import WhisperModel  # optional extra
    except ImportError:
        raise mk.EditError(INSTALL_HINT, mk.EXIT_MISSING)
    prompt = " ".join(p for p in (VERBATIM_PROMPT if args.verbatim else "", args.prompt or "") if p) or None
    print(f"transcribing with faster-whisper {args.model} (first run downloads the model)...", file=sys.stderr)
    model = WhisperModel(args.model, device=args.device, compute_type="auto")
    segments, info = model.transcribe(media, word_timestamps=True, vad_filter=True, beam_size=5,
                                      language=args.language, initial_prompt=prompt,
                                      condition_on_previous_text=False)
    words = []
    for seg in segments:
        for w in seg.words or []:
            words.append({"text": w.word.strip(), "start": w.start, "end": w.end, "prob": w.probability})
    return mk._clean_words(words), getattr(info, "language", None) or args.language or "en"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=mk.EXIT_CODES_HELP,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", help="video/audio file (or a words JSON/SRT/VTT when there is no media)")
    p.add_argument("--words", help="word timings (JSON/SRT/VTT); skips transcription")
    p.add_argument("-o", "--outdir", help="output folder (default: next to the input)")
    p.add_argument("--name", help="output file stem (default: input stem)")
    p.add_argument("--words-only", action="store_true", help="just transcribe: write words.json + phrases.txt")
    p.add_argument("--model", default="small", help="faster-whisper model (small; medium/large-v3 for finals)")
    p.add_argument("--language", help="language code, e.g. en (default: auto)")
    p.add_argument("--prompt", help="vocabulary hint: names, brands, jargon")
    p.add_argument("--verbatim", action="store_true", help="nudge Whisper to keep ums/uhs (for deadspace)")
    p.add_argument("--device", default="auto", help="faster-whisper device: auto, cpu, cuda")
    p.add_argument("--retranscribe", action="store_true", help="ignore a cached words.json")
    p.add_argument("--max-words", type=int, default=3, help="words per caption (1-3 recommended)")
    p.add_argument("--max-chars", type=int, default=18, help="characters per caption line")
    p.add_argument("--pause", type=float, default=0.3, help="a pause this long starts a new caption (s)")
    p.add_argument("--case", choices=["upper", "lower", "keep"], default="upper")
    p.add_argument("--keep-fillers", action="store_true", help="show um/uh in captions")
    p.add_argument("--keep-punctuation", action="store_true", help="keep trailing commas and periods")
    p.add_argument("--size", help="canvas WxH (default: the video's display size, else 1080x1920)")
    p.add_argument("--position", choices=["lower", "seam", "top"], default="lower")
    p.add_argument("--y", type=int, help="anchor y in px (lower: text bottom, seam: centre, top: text top)")
    p.add_argument("--font", default="Arial", help="font family (must be installed for libass)")
    p.add_argument("--font-size", type=int, help="px (default 4.4%% of height, 84 on 1920)")
    p.add_argument("--color", default="#FFFFFF", help="text colour")
    p.add_argument("--accent", default="#FFD400", help="active-word colour")
    p.add_argument("--no-highlight", action="store_true", help="no active-word highlight")
    p.add_argument("--burn", metavar="OUT", help="burn the ASS into a copy of the video (needs libass)")
    p.add_argument("--json", action="store_true", help="print a JSON summary")
    args = p.parse_args()
    if not 1 <= args.max_words <= 8:
        p.error("--max-words must be 1-8")

    is_text_input = os.path.splitext(args.input)[1].lower() in (".json", ".srt", ".vtt")
    info = None if is_text_input else mk.probe(args.input)
    outdir = args.outdir or os.path.dirname(os.path.abspath(args.input))
    os.makedirs(outdir, exist_ok=True)
    stem = args.name or mk.stem_of(args.input)
    base = os.path.join(outdir, stem)
    summary = {"files": {}}

    if args.words or is_text_input:
        words = mk.load_words(args.words or args.input, info["duration"] if info else None)
        language = None
    else:
        if not info.get("audio"):
            raise mk.EditError("no audio stream to transcribe; pass --words", mk.EXIT_USAGE)
        cache = base + ".words.json"
        words, language = None, None
        if os.path.isfile(cache) and not args.retranscribe:
            with open(cache, encoding="utf-8") as handle:
                doc = json.load(handle)
            src = doc.get("source") or {}
            stat = os.stat(args.input)
            if src.get("size") == stat.st_size and abs((src.get("mtime") or 0) - stat.st_mtime) < 1:
                words, language = mk.load_words(cache), doc.get("language_code")
                print(f"using cached transcript {cache}", file=sys.stderr)
        if words is None:
            words, language = transcribe(args.input, args)
            mk.save_words(cache, words, source=args.input, language=language,
                          engine=f"faster-whisper {args.model}")
        summary["files"]["words"] = cache
        with open(base + ".phrases.txt", "w", encoding="utf-8") as handle:
            handle.write("\n".join(mk.phrase_lines(words)) + "\n")
        summary["files"]["phrases"] = base + ".phrases.txt"
    if not words:
        raise mk.EditError("no words to caption", mk.EXIT_USAGE)
    summary["words"] = len(words)
    if args.words_only:
        print(json.dumps(summary, indent=2) if args.json else
              f"transcript: {len(words)} words -> {summary['files'].get('words')}")
        return mk.EXIT_OK

    shown = [w for w in words if args.keep_fillers or norm(w["text"]) not in FILLERS]
    for w in shown:
        w["display"] = display_text(w["text"], args.case, args.keep_punctuation)
    shown = [w for w in shown if w["display"]]
    cues = chunk_words(shown, args.max_words, args.max_chars, args.pause)
    if args.size:
        width, height = mk.parse_size(args.size)
    elif info and info.get("video"):
        width, height = info["video"]["display_width"], info["video"]["display_height"]
    else:
        width, height = 1080, 1920

    with open(base + ".srt", "w", encoding="utf-8") as handle:
        for i, cue in enumerate(cues, 1):
            text = " ".join(w["display"] for w in cue["words"])
            handle.write(f"{i}\n{srt_time(cue['start'])} --> {srt_time(cue['end'])}\n{text}\n\n")
    with open(base + ".ass", "w", encoding="utf-8") as handle:
        handle.write(build_ass(cues, width, height, args))
    lay = layout(width, height, args.position, args.y)
    safe = mk.SAFE_AREA_9x16 if (width, height) == (1080, 1920) else None
    mk.write_json(base + ".cues.json", {
        "version": 1, "kind": "caption-cues", "source": info["path"] if info else None,
        "width": width, "height": height, "safe_area": safe,
        "style": {"case": args.case, "font": args.font, "color": args.color, "accent": args.accent,
                  "position": args.position, "anchor_y": lay["anchor_y"],
                  "align": {2: "bottom", 8: "top", 5: "middle"}[lay["align"]]},
        "cues": [{"i": i, "start": c["start"], "end": c["end"],
                  "text": " ".join(w["display"] for w in c["words"]),
                  "words": [{"text": w["display"], "start": w["start"], "end": w["end"]} for w in c["words"]]}
                 for i, c in enumerate(cues)],
    })
    summary["files"].update({"srt": base + ".srt", "ass": base + ".ass", "cues": base + ".cues.json"})
    summary["cues"] = len(cues)

    code = mk.EXIT_OK
    if args.burn:
        if not info or not info.get("video"):
            raise mk.EditError("--burn needs a video input", mk.EXIT_USAGE)
        flt = "ass" if mk.has_filter("ass") else "subtitles" if mk.has_filter("subtitles") else None
        if not flt:
            print("cannot burn in: this ffmpeg has no libass (no 'ass' or 'subtitles' filter). The SRT, "
                  "ASS and cues files are written. Route: render the captions with HyperFrames "
                  "(/embedded-captions, reusing the words.json as transcript.json), or install an ffmpeg "
                  "with libass (macOS: brew uninstall ffmpeg, then brew trust homebrew-ffmpeg/ffmpeg, "
                  "brew tap homebrew-ffmpeg/ffmpeg, brew install homebrew-ffmpeg/ffmpeg/ffmpeg; most "
                  "Linux distro ffmpeg builds include libass).", file=sys.stderr)
            summary["burned"] = False
            code = mk.EXIT_MISSING
        else:
            with tempfile.TemporaryDirectory() as tmp:  # relative name avoids filter path escaping
                shutil.copy(base + ".ass", os.path.join(tmp, "captions.ass"))
                vargs, _ = mk.video_codec_args(info["video"], crf=17)
                mk.run([mk.ffmpeg_bin(), "-nostdin", "-hide_banner", "-v", "error", "-y",
                        "-i", os.path.abspath(args.input), "-vf", f"{flt}=captions.ass",
                        "-map", "0:v:0", "-map", "0:a?"] + vargs +
                       ["-c:a", "copy", "-movflags", "+faststart", os.path.abspath(args.burn)], cwd=tmp)
            summary["burned"] = True
            summary["files"]["burned"] = os.path.abspath(args.burn)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"captions: {len(cues)} phrases from {len(words)} words")
        for key, path in summary["files"].items():
            print(f"  {key}: {path}")
    return code


if __name__ == "__main__":
    sys.exit(mk.run_main(main))
