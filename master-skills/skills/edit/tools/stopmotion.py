#!/usr/bin/env python3
"""Stop motion with ffmpeg filters only (no Pillow).

  python3 stopmotion.py frames/ -o clay.mp4                   # 12 drawings/s on twos = 24 fps
  python3 stopmotion.py frames/ -o loop.mp4 --fps 8 --hold 3 --loop 3 --pingpong
  python3 stopmotion.py --from-video clip.mp4 -o clip.stop.mp4 # live action -> stop-motion look

Frames mode: images (png/jpg/webp/...) in natural order are fitted to a canvas
(default 1080x1920, cover), each held `--hold` frames, with deterministic per-drawing
jitter and rotation (same --seed = same output), optional loop / ping-pong / end hold.
From-video mode: drops the frame rate to --fps, adds the same jitter, holds each frame,
keeps the original audio in sync.

Part of github.com/Jakeschincariol/master-skills (MIT).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mediakit as mk  # noqa: E402


def natural_key(name: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", name)]


def list_frames(folder: str) -> list:
    if not os.path.isdir(folder):
        raise mk.EditError(f"not a folder: {folder}", mk.EXIT_USAGE)
    files = sorted((f for f in os.listdir(folder) if mk.is_image_file(f) and not f.startswith(".")),
                   key=natural_key)
    if not files:
        raise mk.EditError(f"no images in {folder} (png, jpg, webp, bmp, tif)", mk.EXIT_USAGE)
    return [os.path.join(folder, f) for f in files]


def hash_expr(var: str, a: float, b: float) -> str:
    """Deterministic pseudo-random 0..1 per drawing: fract(sin(i*a + b) * 43758.5453)."""
    inner = f"sin({var}*{a:.4f}+{b:.4f})*43758.5453"
    return f"({inner}-floor({inner}))"


def jitter_chain(width: int, height: int, jitter: float, rotate_deg: float, flicker: float,
                 seed: int, index_var: str) -> str:
    """rotate + crop + scale: each drawing sits a few px off and a fraction of a degree
    askew, like a hand-placed frame. The crop margin hides rotation corners."""
    rng = random.Random(seed)
    offsets = [rng.uniform(0.0, 100.0) for _ in range(4)]
    h_rot = hash_expr(index_var, 12.9898, offsets[0])
    h_x = hash_expr(index_var, 78.2330, offsets[1])
    h_y = hash_expr(index_var, 39.3468, offsets[2])
    margin = int(math.ceil(jitter + max(width, height) / 2 * math.sin(math.radians(rotate_deg)) + 2))
    margin += margin % 2
    parts = []
    if rotate_deg > 0:
        parts.append(f"rotate=a='{rotate_deg * math.pi / 180:.6f}*(2*{h_rot}-1)':c=black:ow=iw:oh=ih")
    if jitter > 0 or rotate_deg > 0:
        parts.append(f"crop=w=iw-{2 * margin}:h=ih-{2 * margin}:"
                     f"x='{margin}+{jitter:.3f}*(2*{h_x}-1)':y='{margin}+{jitter:.3f}*(2*{h_y}-1)'")
        parts.append(f"scale={width}:{height}:flags=bicubic")
    if flicker > 0:
        h_b = hash_expr(index_var, 93.9898, offsets[3])
        parts.append(f"eq=brightness='{flicker:.4f}*(2*{h_b}-1)':eval=frame")
    parts.append("setsar=1")
    return ",".join(parts)


def normalize(src: str, dst: str, width: int, height: int, fit: str, bg: str) -> None:
    scale = "increase" if fit == "cover" else "decrease"
    graph = (f"color=c={bg}:s={width}x{height}:d=1[bg];"
             f"[0:v]scale={width}:{height}:force_original_aspect_ratio={scale},format=rgba[fg];"
             f"[bg][fg]overlay=(W-w)/2:(H-h)/2:format=auto,format=rgb24")
    mk.run([mk.ffmpeg_bin(), "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", src,
            "-filter_complex", graph, "-frames:v", "1", dst])


def encode_args(crf: int) -> list:
    return ["-c:v", "libx264", "-crf", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart"]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=mk.EXIT_CODES_HELP,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("frames", nargs="?", help="folder of frame images")
    p.add_argument("--from-video", metavar="CLIP", help="turn a live clip into a stop-motion look")
    p.add_argument("-o", "--output", required=True, help="output .mp4/.mov")
    p.add_argument("--fps", type=float, default=12, help="drawings per second: 8, 10 or 12 (default 12)")
    p.add_argument("--hold", type=int, default=2, help="frames each drawing is held (2 = on twos)")
    p.add_argument("--size", help="canvas WxH (frames default 1080x1920; video keeps its size)")
    p.add_argument("--fit", choices=["cover", "contain"], default="cover", help="fit images to the canvas")
    p.add_argument("--bg", default="#F4EFE6", help="background colour for contain / transparent PNGs")
    p.add_argument("--jitter", type=float, help="max position wobble in px (default 0.5%% of the short side)")
    p.add_argument("--rotate", type=float, default=0.5, help="max rotation wobble in degrees")
    p.add_argument("--flicker", type=float, default=0.0, help="exposure flicker, e.g. 0.01 (off by default)")
    p.add_argument("--seed", type=int, default=1, help="same seed, same wobble")
    p.add_argument("--loop", type=int, default=1, help="play the frames N times (wobble differs per pass)")
    p.add_argument("--pingpong", action="store_true", help="forward then backward (seamless loop)")
    p.add_argument("--end-hold", type=float, default=0.0, help="hold the last frame this many seconds")
    p.add_argument("--crf", type=int, default=18, help="H.264 quality (0 = lossless)")
    p.add_argument("--json", action="store_true", help="print a JSON summary")
    args = p.parse_args()

    if bool(args.frames) == bool(args.from_video):
        p.error("give a frames folder or --from-video CLIP (one of them)")
    if not 1 <= args.fps <= 30 or not 1 <= args.hold <= 8:
        p.error("--fps must be 1-30 and --hold 1-8")
    out_fps = args.fps * args.hold
    if out_fps > 60:
        p.error("fps x hold must be <= 60")
    rate = f"{out_fps:g}"
    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    summary = {"output": os.path.abspath(args.output), "drawing_fps": args.fps, "hold": args.hold,
               "output_fps": out_fps, "seed": args.seed}

    if args.from_video:
        info = mk.probe(args.from_video)
        if not info.get("video"):
            raise mk.EditError("that file has no video", mk.EXIT_USAGE)
        width, height = (mk.parse_size(args.size) if args.size else
                         (info["video"]["display_width"], info["video"]["display_height"]))
        width -= width % 2
        height -= height % 2
        jitter = args.jitter if args.jitter is not None else min(width, height) * 0.005
        pre = (f"scale={width}:{height}:force_original_aspect_ratio="
               f"{'increase' if args.fit == 'cover' else 'decrease'},"
               f"{'crop' if args.fit == 'cover' else 'pad'}={width}:{height}"
               + ("" if args.fit == "cover" else f":(ow-iw)/2:(oh-ih)/2:color={args.bg}") + ",")
        vf = (f"{pre}fps={args.fps:g}," + jitter_chain(width, height, jitter, args.rotate, args.flicker,
                                                          args.seed, "n") + f",fps={rate},format=yuv420p")
        cmd = [mk.ffmpeg_bin(), "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", args.from_video,
               "-map", "0:v:0", "-map", "0:a?", "-vf", vf] + encode_args(args.crf)
        audio = info.get("audio")
        cmd += ["-c:a", "copy"] if audio and audio["codec"] == "aac" else ["-c:a", "aac", "-b:a", "256k"]
        mk.run(cmd + [args.output])
        summary.update({"mode": "from-video", "size": f"{width}x{height}"})
    else:
        width, height = mk.parse_size(args.size or "1080x1920")
        jitter = args.jitter if args.jitter is not None else min(width, height) * 0.005
        frames = list_frames(args.frames)
        order = list(range(len(frames)))
        if args.pingpong and len(frames) > 2:
            order += list(range(len(frames) - 2, 0, -1))
        order *= max(1, args.loop)
        with tempfile.TemporaryDirectory() as tmp:
            norm_dir, seq_dir = os.path.join(tmp, "norm"), os.path.join(tmp, "seq")
            os.makedirs(norm_dir)
            os.makedirs(seq_dir)
            normed = [os.path.join(norm_dir, f"{i:05d}.png") for i in range(len(frames))]
            with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) as pool:
                list(pool.map(lambda pair: normalize(pair[0], pair[1], width, height, args.fit, args.bg),
                              zip(frames, normed)))
            n = 0
            for idx in order:  # each drawing repeated `hold` times: exact frame counts, no fps filter
                for _ in range(args.hold):
                    link = os.path.join(seq_dir, f"{n:06d}.png")
                    try:
                        os.symlink(normed[idx], link)
                    except OSError:
                        shutil.copy(normed[idx], link)
                    n += 1
            vf = jitter_chain(width, height, jitter, args.rotate, args.flicker, args.seed,
                              f"floor(n/{args.hold})")
            if args.end_hold > 0:
                vf += f",tpad=stop_mode=clone:stop_duration={args.end_hold:g}"
            vf += ",format=yuv420p"
            mk.run([mk.ffmpeg_bin(), "-nostdin", "-hide_banner", "-v", "error", "-y",
                    "-framerate", rate, "-i", os.path.join(seq_dir, "%06d.png"), "-vf", vf, "-r", rate]
                   + encode_args(args.crf) + [args.output])
        summary.update({"mode": "frames", "images": len(frames), "drawings": len(order),
                        "frames": n, "size": f"{width}x{height}",
                        "duration_s": round(n / out_fps + args.end_hold, 3)})
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"stopmotion: {summary['mode']}, {args.fps:g} drawings/s held {args.hold} "
              f"-> {out_fps:g} fps, {summary['size']}\n  wrote: {summary['output']}")
    return mk.EXIT_OK


if __name__ == "__main__":
    sys.exit(mk.run_main(main))
