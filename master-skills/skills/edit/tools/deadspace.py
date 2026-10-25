#!/usr/bin/env python3
"""Cut dead space (silences, plus ums and retakes when word timings are given).

  python3 deadspace.py take.mp4                           # analyze + render take.cut.mp4
  python3 deadspace.py take.mp4 --dry-run                 # only write take.cut.edl.json to review
  python3 deadspace.py take.mp4 --transcript take.words.json   # also cut fillers + retakes
  python3 deadspace.py take.mp4 --from-edl take.cut.edl.json   # render an EDL you edited

How it works: a 10 ms speech envelope with an adaptive gate (noise floor + speech level,
tuned for phone talking-head takes) finds pauses; each cut keeps a breath pad on both
sides so words are never clipped; keep ranges snap to the video frame grid; audio joins
get short equal-power crossfades (no clicks) while video stays frame-accurate, so A/V
stays in sync. Writes an edit decision list (JSON). With a transcript it also writes
the words re-timed to the cut (<output>.words.json) for captions.

Part of github.com/Jakeschincariol/master-skills (MIT).
"""
from __future__ import annotations

import argparse
import difflib
import json
import math
import os
import re
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mediakit as mk  # noqa: E402

PACES = {  # min_silence, pad_before, pad_after, min_cut (seconds)
    "tight": (0.25, 0.06, 0.10, 0.10),
    "normal": (0.35, 0.08, 0.14, 0.12),
    "loose": (0.60, 0.12, 0.22, 0.20),
}
DEFAULT_FILLERS = "um,umm,ummm,uh,uhh,uhm,er,erm,ah,ahh,hmm,hm,mm,mmm"
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".mkv")
AUDIO_CODECS = {".wav": ["-c:a", "pcm_s24le"], ".flac": ["-c:a", "flac"],
                ".m4a": ["-c:a", "aac", "-b:a", "256k"], ".aac": ["-c:a", "aac", "-b:a", "256k"],
                ".mp3": ["-c:a", "libmp3lame", "-q:a", "2"], ".opus": ["-c:a", "libopus", "-b:a", "160k"]}


# ---------------------------------------------------------------- interval helpers

def merge_cuts(cuts: list) -> list:
    """Union of cut dicts {start, end, reason, text}; overlapping cuts merge their reasons."""
    out = []
    for cut in sorted(cuts, key=lambda c: c["start"]):
        if out and cut["start"] <= out[-1]["end"] + 1e-6:
            last = out[-1]
            last["end"] = max(last["end"], cut["end"])
            reasons = last["reason"].split("+")
            if cut["reason"] not in reasons:
                last["reason"] = "+".join(reasons + [cut["reason"]])
            if cut.get("text"):
                last["text"] = ((last.get("text") or "") + " " + cut["text"]).strip()
        else:
            out.append(dict(cut))
    return out


def keeps_from_cuts(cuts: list, start: float, end: float) -> list:
    keeps, cursor = [], start
    for cut in merge_cuts([c for c in cuts if c.get("apply", True)]):
        cs, ce = max(start, cut["start"]), min(end, cut["end"])
        if ce <= cs:
            continue
        if cs > cursor:
            keeps.append([cursor, cs])
        cursor = max(cursor, ce)
    if end > cursor:
        keeps.append([cursor, end])
    return keeps


def find_silences(levels: list, hop: float, threshold: float, min_sound: float = 0.06) -> tuple:
    """Return (silent runs as (start, end) seconds from the first sample, first sound, last sound)."""
    loud = [v >= threshold for v in levels]
    runs, i = [], 0
    while i < len(loud):
        j = i
        while j < len(loud) and loud[j] == loud[i]:
            j += 1
        runs.append([loud[i], i, j])
        i = j
    for k, run in enumerate(runs):  # a click shorter than min_sound inside silence is still silence
        if run[0] and 0 < k < len(runs) - 1 and (run[2] - run[1]) * hop < min_sound:
            run[0] = False
    merged = []
    for run in runs:
        if merged and merged[-1][0] == run[0]:
            merged[-1][2] = run[2]
        else:
            merged.append(run)
    sound = [r for r in merged if r[0]]
    if not sound:
        return [], None, None
    silences = [(r[1] * hop, r[2] * hop) for r in merged if not r[0]]
    return silences, sound[0][1] * hop, sound[-1][2] * hop


# ---------------------------------------------------------------- transcript cuts

def norm_token(text: str) -> str:
    return re.sub(r"[^\w']+", "", text.lower()).strip("'")


def _edges(words: list, k: int, pad_before: float, pad_after: float, t0: float, t1: float) -> tuple:
    """Cut boundaries in the gap before word k: (left edge keeping word k-1's pad,
    right edge keeping word k's pad). Pads shrink to half the gap when words are close."""
    if k <= 0:
        return t0, max(t0, words[0]["start"] - pad_before)
    if k >= len(words):
        return min(t1, words[-1]["end"] + pad_after), t1
    prev_end, start = words[k - 1]["end"], words[k]["start"]
    gap = max(0.0, start - prev_end)
    return prev_end + min(pad_after, gap / 2), start - min(pad_before, gap / 2)


def transcript_cuts(words: list, fillers: set, retakes: str, pad_before: float, pad_after: float,
                    t0: float, t1: float) -> list:
    cuts = []
    for k, word in enumerate(words):
        if norm_token(word["text"]) in fillers:
            left, _ = _edges(words, k, pad_before, pad_after, t0, t1)
            _, right = _edges(words, k + 1, pad_before, pad_after, t0, t1)
            if right > left:
                cuts.append({"start": left, "end": right, "reason": "filler", "text": word["text"]})
    if retakes == "off":
        return cuts
    idx = [k for k, w in enumerate(words) if norm_token(w["text"]) not in fillers and norm_token(w["text"])]
    tokens = [norm_token(words[k]["text"]) for k in idx]
    j = 1
    while j < len(tokens):
        found = None
        for length in range(min(25, j), 1, -1):  # longest abandoned attempt first
            a, b = tokens[j - length:j], tokens[j:j + length]
            first, restart = words[idx[j - length]], words[idx[j]]
            if restart["start"] - first["start"] > 15.0:
                continue
            if a == b:
                found = (length, "exact")
                break
            if (retakes == "fuzzy" and length >= 4 and len(b) == length and a[:2] == b[:2]
                    and restart["start"] - words[idx[j - 1]]["end"] >= 0.25
                    and difflib.SequenceMatcher(None, a, b).ratio() >= 0.8):
                found = (length, "fuzzy")
                break
        if found:
            length = found[0]
            left, _ = _edges(words, idx[j - length], pad_before, pad_after, t0, t1)
            _, right = _edges(words, idx[j], pad_before, pad_after, t0, t1)
            text = " ".join(words[idx[m]]["text"] for m in range(j - length, j))
            if right > left:
                cuts.append({"start": left, "end": right, "reason": "retake", "text": text})
        j += 1
    return cuts


def remap_words(words: list, keeps: list) -> list:
    """Move word times from the source onto the cut timeline; words inside cuts are dropped."""
    out, offset, segments = [], 0.0, []
    for start, end in keeps:
        segments.append((start, end, offset))
        offset += end - start
    for word in words:
        mid = (word["start"] + word["end"]) / 2
        for start, end, out_start in segments:
            if start <= mid < end:
                ws = out_start + max(word["start"], start) - start
                we = out_start + min(word["end"], end) - start
                item = dict(word, start=round(ws, 3), end=round(max(we, ws + 0.01), 3))
                out.append(item)
                break
    return out


# ---------------------------------------------------------------- analysis

def analyze(path: str, info: dict, args, words: list | None) -> dict:
    audio = info["audio_streams"][args.audio_stream]
    a_off = audio["offset"]
    t0 = 0.0
    t1 = info["end"] or info["duration"]
    levels = mk.audio_envelope(path, info, stream=args.audio_stream, hop=0.01)
    stats = mk.speech_levels(levels)
    threshold = args.threshold if args.threshold is not None else stats["threshold_db"]
    if not stats["reliable"] and args.threshold is None:
        mk.warn(f"speech is only {stats['spread_db']} dB above the noise floor; detection is "
                "unreliable here, pass --transcript or --threshold")
    silences, first, last = find_silences(levels, 0.01, threshold)
    cuts = []
    if not stats["reliable"] and args.threshold is None:
        first = None  # no trustworthy gate: cut nothing by level rather than guess
    elif first is None:
        mk.warn("no speech found above the gate; nothing to cut")
    else:
        first, last = first + a_off, last + a_off
        head_end = first - args.pad_before
        if head_end - t0 >= args.min_cut:
            cuts.append({"start": t0, "end": head_end, "reason": "silence", "text": None})
        tail_start = last + args.pad_after
        if t1 - tail_start >= args.min_cut:
            cuts.append({"start": tail_start, "end": t1, "reason": "silence", "text": None})
        for s, e in silences:
            s, e = s + a_off, e + a_off
            if s <= first or e >= last or e - s < args.min_silence:
                continue
            cs, ce = s + args.pad_after, e - args.pad_before
            if ce - cs >= args.min_cut:
                cuts.append({"start": cs, "end": ce, "reason": "silence", "text": None})
    if words:
        shifted = [dict(w, start=w["start"] + a_off, end=w["end"] + a_off) for w in words]
        guarded = []
        for cut in cuts:  # never cut through a transcribed word that has real energy
            pieces = [[cut["start"], cut["end"]]]
            for w in shifted:
                core_s, core_e = w["start"] + 0.06, w["end"] - 0.06
                if core_e <= core_s or norm_token(w["text"]) in args.filler_set:
                    continue
                lo = int((core_s - a_off) / 0.01)
                hi = int((core_e - a_off) / 0.01) + 1
                if not levels[max(0, lo):hi] or max(levels[max(0, lo):hi]) < stats["noise_db"] + 6:
                    continue
                nxt = []
                for ps, pe in pieces:
                    if core_e <= ps or core_s >= pe:
                        nxt.append([ps, pe])
                        continue
                    if core_s - ps >= args.min_cut:
                        nxt.append([ps, core_s])
                    if pe - core_e >= args.min_cut:
                        nxt.append([core_e, pe])
                pieces = nxt
            guarded += [dict(cut, start=ps, end=pe) for ps, pe in pieces]
        cuts = guarded + transcript_cuts(shifted, args.filler_set, args.retakes,
                                         args.pad_before, args.pad_after, t0, t1)
    return {"levels": stats, "threshold_db": round(threshold, 1), "cuts": cuts, "start": t0, "end": t1}


def snap(keeps: list, info: dict, min_keep: float) -> tuple:
    """Snap keep ranges outward to the CFR frame grid; drop cuts that leave slivers."""
    video = info.get("video")
    if not video:
        return [[round(s, 6), round(e, 6)] for s, e in keeps if e - s > 1e-3], None
    rate = mk.cfr_rate(video)
    g0 = Fraction(round(video["offset"] * float(rate))) / rate
    total = int(math.floor((info["end"] - float(g0)) * float(rate) + 1e-6))
    frames = []
    for s, e in keeps:
        k = max(0, int(math.floor((s - float(g0)) * float(rate) + 1e-6)))
        m = min(total, int(math.ceil((e - float(g0)) * float(rate) - 1e-6)))
        if m <= k:
            continue
        if frames and k <= frames[-1][1]:
            frames[-1][1] = max(frames[-1][1], m)
        else:
            frames.append([k, m])
    min_frames = max(2, int(math.ceil(min_keep * float(rate))))
    changed = True
    while changed and len(frames) > 1:  # merge slivers into a neighbour by removing the smaller cut
        changed = False
        for i, (k, m) in enumerate(frames):
            if m - k >= min_frames:
                continue
            gap_l = k - frames[i - 1][1] if i > 0 else None
            gap_r = frames[i + 1][0] - m if i + 1 < len(frames) else None
            if gap_r is None or (gap_l is not None and gap_l <= gap_r):
                frames[i - 1][1] = m
            else:
                frames[i + 1][0] = k
            del frames[i]
            changed = True
            break
    secs = [[float(g0 + Fraction(k) / rate), float(g0 + Fraction(m) / rate)] for k, m in frames]
    return secs, {"rate": str(rate), "frames": frames}


# ---------------------------------------------------------------- render

def render(path: str, info: dict, keeps: list, grid: dict | None, out: str, args) -> None:
    ext = os.path.splitext(out)[1].lower()
    has_video = bool(info.get("video")) and ext in VIDEO_EXTS
    if info.get("video") and not has_video and ext not in AUDIO_CODECS:
        raise mk.EditError(f"unsupported output extension {ext}; use .mp4/.mov/.mkv or an audio type",
                           mk.EXIT_USAGE)
    xf = args.crossfade_ms / 1000.0
    n = len(keeps)
    a = f"0:a:{args.audio_stream}"
    parts = []
    if has_video:
        rate = grid["rate"]
        if n == 1:
            k, m = grid["frames"][0]
            parts.append(f"[0:v:0]fps={rate},trim=start_frame={k}:end_frame={m},setpts=PTS-STARTPTS[v]")
        else:
            parts.append(f"[0:v:0]fps={rate},split={n}" + "".join(f"[s{i}]" for i in range(n)))
            for i, (k, m) in enumerate(grid["frames"]):
                parts.append(f"[s{i}]trim=start_frame={k}:end_frame={m},setpts=PTS-STARTPTS[v{i}]")
            parts.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]")
    for i, (s, e) in enumerate(keeps):
        s2 = s - (xf / 2 if i > 0 else 0)
        e2 = e + (xf / 2 if i < n - 1 else 0)
        parts.append(f"[{a}]atrim=start={s2:.6f}:end={e2:.6f},asetpts=PTS-STARTPTS[a{i}]")
    cur = "a0"
    for i in range(1, n):
        parts.append(f"[{cur}][a{i}]acrossfade=d={xf:.4f}:c1=qsin:c2=qsin[x{i}]")
        cur = f"x{i}"
    total = sum(e - s for s, e in keeps)
    fades = []
    if keeps[0][0] > 0.001:
        fades.append("afade=t=in:d=0.005")
    if keeps[-1][1] < info["end"] - 0.001:
        fades.append(f"afade=t=out:st={max(0.0, total - 0.005):.6f}:d=0.005")
    parts.append(f"[{cur}]" + (",".join(fades) if fades else "anull") + "[a]")
    graph = ";".join(parts)
    cmd = [mk.ffmpeg_bin(), "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", path]
    if len(graph) > 100000:
        script = out + ".graph.txt"
        with open(script, "w") as handle:
            handle.write(graph)
        ver = mk.ffmpeg_version()
        cmd += (["-/filter_complex", script] if (ver is None or ver[0] >= 7)
                else ["-filter_complex_script", script])
    else:
        cmd += ["-filter_complex", graph]
    if has_video:
        vargs, _ = mk.video_codec_args(info["video"], crf=args.crf)
        cmd += ["-map", "[v]", "-map", "[a]"] + vargs + ["-c:a", "aac", "-b:a", "256k"]
        if ext in (".mp4", ".mov", ".m4v"):
            cmd += ["-movflags", "+faststart"]
    else:
        codec = AUDIO_CODECS.get(ext)
        if not codec:
            raise mk.EditError(f"unsupported audio output {ext}", mk.EXIT_USAGE)
        cmd += ["-map", "[a]"] + codec
    cmd.append(out)
    mk.run(cmd)


# ---------------------------------------------------------------- main

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=mk.EXIT_CODES_HELP,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", help="video or audio file")
    p.add_argument("-o", "--output", help="output file (default: <input>.cut.<ext>)")
    p.add_argument("--edl", help="EDL JSON path (default: <output stem>.edl.json)")
    p.add_argument("--transcript", help="word timings JSON/SRT/VTT for filler + retake cuts")
    p.add_argument("--pace", choices=sorted(PACES), default="normal",
                   help="preset: tight (shorts), normal (default), loose (talks)")
    p.add_argument("--threshold", type=float, help="silence gate in dBFS (default: adaptive)")
    p.add_argument("--min-silence", type=float, help="pauses shorter than this are kept (s)")
    p.add_argument("--pad-before", type=float, help="air kept before speech starts (s)")
    p.add_argument("--pad-after", type=float, help="air kept after speech ends (s)")
    p.add_argument("--min-cut", type=float, help="skip cuts shorter than this (s)")
    p.add_argument("--crossfade-ms", type=float, default=30.0, help="audio crossfade at joins (ms)")
    p.add_argument("--fillers", default=DEFAULT_FILLERS, help="comma list of filler words to cut")
    p.add_argument("--no-fillers", action="store_true", help="do not cut filler words")
    p.add_argument("--retakes", choices=["off", "exact", "fuzzy"], default="fuzzy",
                   help="repeated-line detection (needs --transcript); last take wins")
    p.add_argument("--audio-stream", type=int, default=0, help="which audio stream to analyze")
    p.add_argument("--dry-run", action="store_true", help="write the EDL only, do not render")
    p.add_argument("--from-edl", help="render the cuts in this EDL (apply=false vetoes a cut)")
    p.add_argument("--crf", type=int, default=16, help="video quality, lower is better (default 16)")
    p.add_argument("--json", action="store_true", help="print a JSON summary")
    args = p.parse_args()

    min_silence, pad_before, pad_after, min_cut = PACES[args.pace]
    args.min_silence = args.min_silence if args.min_silence is not None else min_silence
    args.pad_before = args.pad_before if args.pad_before is not None else pad_before
    args.pad_after = args.pad_after if args.pad_after is not None else pad_after
    args.min_cut = args.min_cut if args.min_cut is not None else min_cut
    args.filler_set = set() if args.no_fillers else {norm_token(f) for f in args.fillers.split(",") if f.strip()}

    info = mk.probe(args.input)
    if not info["audio_streams"]:
        raise mk.EditError("no audio stream: dead space is found in the audio. Use a transcript-driven "
                           "edit or cut by hand.", mk.EXIT_USAGE)
    if args.audio_stream >= len(info["audio_streams"]):
        raise mk.EditError(f"there is no audio stream #{args.audio_stream}", mk.EXIT_USAGE)
    out = args.output or mk.default_output(args.input, ".cut")
    edl_path = args.edl or mk.default_output(out, "", ".edl.json")
    words = mk.load_words(args.transcript, info["duration"]) if args.transcript else None

    if args.from_edl:
        with open(args.from_edl, encoding="utf-8") as handle:
            edl = json.load(handle)
        cuts = edl.get("cuts") or []
        analysis = {"start": 0.0, "end": info["end"], "cuts": cuts,
                    "levels": edl.get("analysis", {}).get("levels"),
                    "threshold_db": edl.get("analysis", {}).get("threshold_db")}
    else:
        analysis = analyze(args.input, info, args, words)
        cuts = merge_cuts(analysis["cuts"])
        for cut in cuts:
            cut["start"], cut["end"] = round(cut["start"], 4), round(cut["end"], 4)
            cut["apply"] = True
    raw_keeps = keeps_from_cuts(cuts, analysis["start"], analysis["end"])
    if not raw_keeps:
        raise mk.EditError("every second would be cut; check --threshold", mk.EXIT_USAGE)
    min_keep = max(0.07, args.crossfade_ms / 1000.0 + 0.04)
    keeps, grid = snap(raw_keeps, info, min_keep)
    src_len = analysis["end"] - analysis["start"]
    out_len = sum(e - s for s, e in keeps)
    applied = [c for c in cuts if c.get("apply", True)]
    counts = {}
    for cut in applied:
        for reason in cut["reason"].split("+"):
            counts[reason] = counts.get(reason, 0) + 1
    edl = {
        "version": 1,
        "tool": "master-skills edit/deadspace.py",
        "source": info["path"],
        "duration": round(src_len, 4),
        "fps": grid["rate"] if grid else None,
        "settings": {k: getattr(args, k) for k in ("pace", "min_silence", "pad_before", "pad_after",
                                                     "min_cut", "crossfade_ms", "retakes")},
        "analysis": {"levels": analysis.get("levels"), "threshold_db": analysis.get("threshold_db")},
        "note": "cuts[] is the source of truth: set apply=false to veto a cut, append "
                "{start, end, reason: 'manual'} to add one, then run --from-edl.",
        "cuts": cuts,
        "keep": [{"start": round(s, 4), "end": round(e, 4)} for s, e in keeps],
        "output": {"path": os.path.abspath(out), "duration": round(out_len, 4),
                   "saved": round(src_len - out_len, 4)},
    }
    mk.write_json(edl_path, edl)
    summary = {"input": info["path"], "edl": os.path.abspath(edl_path), "cuts": len(applied),
               "by_reason": counts, "source_s": round(src_len, 2), "output_s": round(out_len, 2),
               "saved_s": round(src_len - out_len, 2),
               "saved_pct": round(100 * (src_len - out_len) / src_len, 1) if src_len else 0.0,
               "threshold_db": analysis.get("threshold_db"), "rendered": False}
    if not args.dry_run:
        render(args.input, info, keeps, grid, out, args)
        result = mk.probe(out)
        summary["rendered"] = True
        summary["output"] = result["path"]
        durations = [s["duration"] for s in ([result["video"]] if result["video"] else []) +
                     result["audio_streams"] if s and s.get("duration")]
        if len(durations) == 2:
            summary["av_drift_ms"] = round(abs(durations[0] - durations[1]) * 1000, 1)
        if words:
            words_out = mk.default_output(out, "", ".words.json")
            a_off = info["audio_streams"][args.audio_stream]["offset"]
            shifted = [dict(w, start=w["start"] + a_off, end=w["end"] + a_off) for w in words]
            mk.save_words(words_out, remap_words(shifted, keeps), source=out,
                          engine="remapped by deadspace.py")
            summary["words"] = os.path.abspath(words_out)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        reasons = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "none"
        print(f"deadspace: {len(applied)} cuts ({reasons}), threshold {summary['threshold_db']} dBFS")
        print(f"  {src_len:.2f} s -> {out_len:.2f} s, saved {summary['saved_s']:.2f} s "
              f"({summary['saved_pct']}%)")
        print(f"  edl: {edl_path}")
        if summary["rendered"]:
            print(f"  wrote: {out}" + (f"  (A/V drift {summary.get('av_drift_ms')} ms)"
                                        if "av_drift_ms" in summary else ""))
        if summary.get("words"):
            print(f"  words on the cut timeline: {summary['words']}")
        for cut in applied:
            if cut["reason"] != "silence":
                print(f"  {cut['reason']:>15} {mk.fmt_time(cut['start'])}-{mk.fmt_time(cut['end'])}  "
                      f"{cut.get('text') or ''}")
    return mk.EXIT_OK


if __name__ == "__main__":
    sys.exit(mk.run_main(main))
