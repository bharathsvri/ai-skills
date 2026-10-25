#!/usr/bin/env python3
"""Probe media before editing, or check what this machine can do (--doctor).

  python3 probe.py clip.mov                 # dims after rotation, fps + VFR, HDR, audio layout
  python3 probe.py clip.mov --loudness      # + integrated loudness and true peak
  python3 probe.py --doctor                 # ffmpeg filters, faster-whisper, Node for HyperFrames
  python3 probe.py clip.mov --json          # machine-readable

Part of github.com/Jakeschincariol/master-skills (MIT).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mediakit as mk  # noqa: E402

KEY_FILTERS = ["ass", "subtitles", "drawtext", "silencedetect", "acrossfade", "alimiter", "loudnorm",
               "ebur128", "rotate", "crop", "zscale", "tonemap"]
KEY_ENCODERS = ["libx264", "libx265", "aac", "libmp3lame", "libopus"]


def notes_for(info: dict) -> list:
    """Plain-English warnings an editor should know before cutting."""
    notes = []
    video, audio = info.get("video"), info.get("audio")
    if not audio:
        notes.append("no audio stream: dead-space cutting and transcription need audio")
    if audio and audio["channels"] == 1:
        notes.append("mono audio: fine for voice; finish.py keeps it mono unless a music bed is added")
    if audio and len(info.get("audio_streams") or []) > 1:
        notes.append(f"{len(info['audio_streams'])} audio streams: tools use the first (--audio-stream to change)")
    if video:
        if video["rotation"]:
            notes.append(f"rotation {video['rotation']} deg: displays as "
                         f"{video['display_width']}x{video['display_height']} (ffmpeg rotates automatically)")
        if video["vfr"]:
            notes.append(f"variable frame rate (avg {video['avg_frame_rate']} vs {video['r_frame_rate']}): "
                         f"deadspace.py renders constant {mk.cfr_rate(video)} fps")
        if video["hdr"]:
            notes.append("HDR (HLG/PQ) footage: tools keep it 10-bit HEVC; motion engines that render SDR "
                         "need one SDR conversion first, done once, not per step")
        if video["display_height"] and video["display_width"]:
            ratio = video["display_width"] / video["display_height"]
            if abs(ratio - 9 / 16) > 0.01:
                notes.append(f"aspect {video['display_width']}x{video['display_height']} is not 9:16: "
                             "reframe for Reels/TikTok/Shorts (finish.py --fit cover|contain)")
    return notes


def describe(info: dict) -> str:
    lines = [f"{info['path']}",
             f"  container {info['format']}, {info['duration'] or 0:.2f} s, {info['size'] / 1e6:.1f} MB"]
    video, audio = info.get("video"), info.get("audio")
    if video:
        rate = f"{video['fps']:.3f}".rstrip("0").rstrip(".") if video["fps"] else "?"
        lines.append(f"  video  {video['codec']} {video['display_width']}x{video['display_height']} "
                     f"@ {rate} fps{' (VFR)' if video['vfr'] else ''}, {video['pix_fmt']}, "
                     f"{video['bit_depth']}-bit{', HDR' if video['hdr'] else ''}")
    if audio:
        lines.append(f"  audio  {audio['codec']} {audio['sample_rate']} Hz, {audio['channels']} ch"
                     f"{' (' + audio['channel_layout'] + ')' if audio['channel_layout'] else ''}")
    loud = info.get("loudness")
    if loud:
        lines.append(f"  loudness {loud['integrated_lufs']} LUFS integrated, true peak "
                     f"{loud['true_peak_dbtp']} dBTP, range {loud['lra_lu']} LU")
    for note in info.get("notes", []):
        lines.append(f"  note: {note}")
    return "\n".join(lines)


def _version_of(cmd) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (out.stdout or out.stderr or "").strip().splitlines()
    return text[0] if text else None


def doctor() -> dict:
    report = {"python": platform.python_version(), "platform": platform.platform(terse=True)}
    try:
        mk.ffmpeg_version()
        report["ffmpeg"] = {"path": mk.ffmpeg_bin(), "version": mk._CACHE.get("version_line"),
                            "ffprobe": mk.ffprobe_bin()}
        filters = mk.ffmpeg_filters()
        report["filters"] = {name: name in filters for name in KEY_FILTERS}
        report["alimiter_latency"] = "latency" in mk.filter_options("alimiter")
        encoders = mk.ffmpeg_encoders()
        report["encoders"] = {name: name in encoders for name in KEY_ENCODERS}
    except mk.EditError as err:
        report["ffmpeg"] = {"error": str(err)}
    report["faster_whisper"] = importlib.util.find_spec("faster_whisper") is not None
    node = _version_of(["node", "--version"]) if shutil.which("node") else None
    report["node"] = node
    major = int(re.sub(r"\D", "", node.split(".")[0]) or 0) if node else 0
    report["hyperframes_ready"] = major >= 22
    report["npx"] = shutil.which("npx") is not None
    return report


def describe_doctor(report: dict) -> str:
    out = [f"python {report['python']} on {report['platform']}"]
    ff = report.get("ffmpeg", {})
    if "error" in ff:
        out.append(f"ffmpeg: MISSING ({ff['error']})")
    else:
        out.append(f"ffmpeg: {ff['version']} ({ff['path']})")
        missing = [k for k, v in report["filters"].items() if not v]
        out.append("  filters missing: " + (", ".join(missing) if missing else "none"))
        if not (report["filters"]["ass"] or report["filters"]["subtitles"]):
            out.append("  captions: no libass, so captions.py --burn cannot burn in here; "
                       "use the HyperFrames route or a libass ffmpeg (see SKILL.md)")
        if not report["alimiter_latency"]:
            out.append("  alimiter has no latency option: finish.py compensates the 5 ms delay itself")
        missing_enc = [k for k, v in report["encoders"].items() if not v]
        out.append("  encoders missing: " + (", ".join(missing_enc) if missing_enc else "none"))
    out.append("faster-whisper: " + ("installed" if report["faster_whisper"] else
                                     "not installed (captions.py needs --words, or pip install faster-whisper)"))
    if report["node"]:
        out.append(f"node {report['node']}: " + ("ok for HyperFrames" if report["hyperframes_ready"]
                                                  else "HyperFrames needs Node 22+"))
    else:
        out.append("node: not found (HyperFrames and Remotion need Node; HyperFrames needs 22+)")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe media for editing, or check this machine's editing toolchain.",
        epilog=mk.EXIT_CODES_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", help="media files to probe")
    parser.add_argument("--doctor", action="store_true", help="report ffmpeg filters, encoders, "
                        "faster-whisper and Node availability")
    parser.add_argument("--loudness", action="store_true",
                        help="also measure integrated loudness and true peak (decodes the audio)")
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args()
    if not args.files and not args.doctor:
        parser.error("give a media file or --doctor")

    results = {}
    if args.doctor:
        results["doctor"] = doctor()
    probes = []
    for path in args.files:
        info = mk.probe(path)
        if args.loudness and info.get("audio"):
            info["loudness"] = mk.measure_loudness(path)
        info["notes"] = notes_for(info)
        probes.append(info)
    if args.json:
        if args.doctor and not probes:
            print(json.dumps(results["doctor"], indent=2))
        elif not args.doctor and len(probes) == 1:
            print(json.dumps(probes[0], indent=2))
        else:
            results["files"] = probes
            print(json.dumps(results, indent=2))
    else:
        if args.doctor:
            print(describe_doctor(results["doctor"]))
        for info in probes:
            print(describe(info))
    if args.doctor and "error" in results["doctor"].get("ffmpeg", {}):
        return mk.EXIT_MISSING
    return mk.EXIT_OK


if __name__ == "__main__":
    sys.exit(mk.run_main(main))
