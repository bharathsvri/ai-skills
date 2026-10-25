"""Tests for the edit skill tools. Fixtures are generated with ffmpeg lavfi (tone, silence,
testsrc). Run: cd skills/edit && python3 -m unittest discover -s tools -p "test_*.py"
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import captions  # noqa: E402
import deadspace  # noqa: E402
import mediakit as mk  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
# tone bursts stand in for speech: 0.5-2.0, 3.2-4.5, 4.8-6.0 s; a faint 7.9 kHz floor stands in for room noise
SPEECH = "between(t,0.5,2.0)+between(t,3.2,4.5)+between(t,4.8,6.0)"
TONE = f"aevalsrc='0.3*sin(2*PI*220*t)*({SPEECH})+0.0005*sin(2*PI*7919*t)':s=48000:d=7"


def ff(*args):
    subprocess.run([FFMPEG, "-nostdin", "-hide_banner", "-v", "error", "-y", *args], check=True)


def tool(name, *args):
    return subprocess.run([sys.executable, os.path.join(HERE, name), *map(str, args)],
                          capture_output=True, text=True)


def frame_md5s(path):
    out = subprocess.run([FFMPEG, "-v", "error", "-i", path, "-map", "0:v", "-f", "framemd5", "-"],
                         capture_output=True, text=True, check=True).stdout
    return [line.split(",")[-1].strip() for line in out.splitlines() if line and not line.startswith("#")]


@unittest.skipUnless(FFMPEG and shutil.which("ffprobe"), "ffmpeg/ffprobe not on PATH")
class EditToolsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="edit-test-")
        cls.talk = os.path.join(cls.tmp, "talk.mp4")
        ff("-f", "lavfi", "-i", "testsrc2=s=180x320:r=30:d=7", "-f", "lavfi", "-i", TONE,
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", cls.talk)
        cls.wav = os.path.join(cls.tmp, "talk.wav")
        ff("-f", "lavfi", "-i", TONE, "-c:a", "pcm_s16le", cls.wav)
        cls.silent_video = os.path.join(cls.tmp, "noaudio.mp4")
        ff("-f", "lavfi", "-i", "testsrc2=s=180x320:r=30:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           cls.silent_video)
        # words aligned to the bursts: burst 2 is "um", burst 1 is an abandoned attempt that burst 3 repeats
        cls.words = os.path.join(cls.tmp, "talk.words.json")
        words = [
            {"word": " So", "start": 0.5, "end": 0.8}, {"word": " the", "start": 0.85, "end": 1.1},
            {"word": " first", "start": 1.15, "end": 1.5}, {"word": " thing", "start": 1.55, "end": 1.95},
            {"word": " um", "start": 3.25, "end": 4.45},
            {"word": " So", "start": 4.8, "end": 5.0}, {"word": " the", "start": 5.05, "end": 5.2},
            {"word": " first", "start": 5.25, "end": 5.5}, {"word": " thing", "start": 5.55, "end": 5.75},
            {"word": " works.", "start": 5.8, "end": 5.98},
        ]
        with open(cls.words, "w") as handle:
            json.dump({"segments": [{"words": words}]}, handle)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ------------------------------------------------------------ probe
    def test_probe_reports_streams(self):
        info = mk.probe(self.talk)
        self.assertEqual(info["video"]["display_width"], 180)
        self.assertAlmostEqual(info["video"]["fps"], 30.0)
        self.assertFalse(info["video"]["vfr"])
        self.assertEqual(info["audio"]["channels"], 1)
        self.assertIsNone(mk.probe(self.wav)["video"])

    # ------------------------------------------------------------ deadspace
    def test_deadspace_dry_run_cuts_long_pause_only(self):
        res = tool("deadspace.py", self.talk, "--dry-run", "--json", "-o", os.path.join(self.tmp, "dry.mp4"))
        self.assertEqual(res.returncode, 0, res.stderr)
        summary = json.loads(res.stdout)
        with open(summary["edl"]) as handle:
            edl = json.load(handle)
        cuts = [(c["start"], c["end"]) for c in edl["cuts"]]
        self.assertEqual(len(cuts), 3, cuts)  # head, the 1.2 s gap, tail; the 0.3 s gap stays
        self.assertTrue(any(2.0 < s < 2.3 and 3.0 < e < 3.2 for s, e in cuts), cuts)
        self.assertFalse(any(s < 4.6 and e > 4.6 for s, e in cuts), cuts)
        self.assertGreater(summary["saved_s"], 1.8)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "dry.mp4")))

    def test_deadspace_render_keeps_speech_and_sync(self):
        out = os.path.join(self.tmp, "cut.mp4")
        res = tool("deadspace.py", self.talk, "-o", out, "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        summary = json.loads(res.stdout)
        info = mk.probe(out)
        self.assertLess(abs(info["video"]["duration"] - info["audio"]["duration"]), 0.04)
        self.assertAlmostEqual(info["video"]["duration"], summary["output_s"], delta=0.05)
        levels = mk.audio_envelope(out, info)
        speech = sum(1 for v in levels if v > -25) * 0.01
        self.assertAlmostEqual(speech, 4.0, delta=0.12)  # all 4.0 s of "speech" survived

    def test_deadspace_audio_only_and_no_clicks(self):
        out = os.path.join(self.tmp, "cut.wav")
        res = tool("deadspace.py", self.wav, "-o", out)
        self.assertEqual(res.returncode, 0, res.stderr)
        import array
        self.assertEqual(mk.probe(out)["audio"]["codec"], "pcm_s24le")
        raw = subprocess.run([FFMPEG, "-v", "error", "-i", out, "-f", "f32le", "-acodec", "pcm_f32le", "-"],
                             capture_output=True, check=True).stdout
        samples = array.array("f")
        samples.frombytes(raw)
        if sys.byteorder == "big":
            samples.byteswap()
        max_step = max(abs(b - a) for a, b in zip(samples, samples[1:]))
        self.assertLess(max_step, 0.3 * 2 * 3.1416 * 220 / 48000 * 1.5)  # no step beyond the tone's own slope
        self.assertLess(len(samples) / 48000, 5.2)

    def test_deadspace_no_audio_is_usage_error(self):
        res = tool("deadspace.py", self.silent_video, "--dry-run")
        self.assertEqual(res.returncode, 2)
        self.assertIn("no audio", res.stderr)

    def test_deadspace_transcript_fillers_retakes_and_edl_veto(self):
        out = os.path.join(self.tmp, "tx.mp4")
        res = tool("deadspace.py", self.talk, "-o", out, "--transcript", self.words, "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        summary = json.loads(res.stdout)
        self.assertIn("filler", summary["by_reason"])
        self.assertIn("retake", summary["by_reason"])
        self.assertLess(summary["output_s"], 1.6)  # only the last take "so the first thing works" remains
        with open(summary["words"]) as handle:
            kept = [w["text"] for w in json.load(handle)["words"]]
        self.assertEqual(kept, ["So", "the", "first", "thing", "works."])
        with open(summary["edl"]) as handle:
            edl = json.load(handle)
        for cut in edl["cuts"]:
            if "retake" in cut["reason"]:
                cut["apply"] = False
        edited = os.path.join(self.tmp, "edited.edl.json")
        with open(edited, "w") as handle:
            json.dump(edl, handle)
        res2 = tool("deadspace.py", self.talk, "-o", os.path.join(self.tmp, "veto.mp4"),
                    "--from-edl", edited, "--json")
        self.assertEqual(res2.returncode, 0, res2.stderr)
        self.assertGreater(json.loads(res2.stdout)["output_s"], summary["output_s"] + 1.2)

    def test_retake_detection_unit(self):
        def w(texts):
            return [{"text": t, "start": i * 0.5, "end": i * 0.5 + 0.3} for i, t in enumerate(texts)]
        cuts = deadspace.transcript_cuts(w("so the first so the first thing".split()), set(), "exact",
                                         0.08, 0.14, 0.0, 10.0)
        self.assertEqual([c["text"] for c in cuts], ["so the first"])
        none = deadspace.transcript_cuts(w("we build tools and we ship them".split()), set(), "fuzzy",
                                         0.08, 0.14, 0.0, 10.0)
        self.assertEqual(none, [])
        merged = deadspace.merge_cuts([{"start": 0, "end": 1, "reason": "silence"},
                                       {"start": 0.5, "end": 2, "reason": "filler", "text": "um"}])
        self.assertEqual(merged, [{"start": 0, "end": 2, "reason": "silence+filler", "text": "um"}])

    # ------------------------------------------------------------ captions
    def test_chunking_rules(self):
        words = [{"text": t, "start": i * 0.4, "end": i * 0.4 + 0.35} for i, t in
                 enumerate("Stop editing videos by hand. I built a tool for the job".split())]
        cues = captions.chunk_words(words, 3, 18, 0.3)
        texts = [" ".join(w["text"] for w in c["words"]) for c in cues]
        self.assertTrue(all(len(c["words"]) <= 3 for c in cues), texts)
        self.assertTrue(any(t.endswith("hand.") for t in texts), texts)  # breaks after the sentence end
        self.assertTrue(texts[texts.index(next(t for t in texts if t.endswith("hand."))) + 1].startswith("I"))
        self.assertFalse(any(t.split()[-1] in ("a", "the", "for") for t in texts[:-1]), texts)
        for a, b in zip(cues, cues[1:]):
            self.assertLessEqual(a["end"], b["start"] + 1e-9)

    def test_captions_files_and_safe_zone(self):
        outdir = os.path.join(self.tmp, "caps")
        res = tool("captions.py", self.talk, "--words", self.words, "-o", outdir, "--size", "1080x1920",
                   "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        with open(os.path.join(outdir, "talk.cues.json")) as handle:
            cues = json.load(handle)
        self.assertEqual(cues["height"], 1920)
        self.assertTrue(all(1 <= len(c["words"]) <= 3 for c in cues["cues"]))
        self.assertNotIn("UM", " ".join(c["text"] for c in cues["cues"]))
        with open(os.path.join(outdir, "talk.ass")) as handle:
            ass = handle.read()
        self.assertIn("PlayResY: 1920", ass)
        self.assertIn(",2,140,140,480,1", ass)  # bottom-centre, text bottom at y 1440, clear of the rail
        self.assertIn("\\c&H0000D4FF&", ass)  # active word in the accent colour
        with open(os.path.join(outdir, "talk.srt")) as handle:
            self.assertTrue(handle.read().startswith("1\n00:00:00,500 --> "))

    def test_captions_burn_needs_libass(self):
        out = os.path.join(self.tmp, "burned.mp4")
        res = tool("captions.py", self.talk, "--words", self.words, "-o", os.path.join(self.tmp, "b"),
                   "--burn", out)
        if mk.has_filter("ass") or mk.has_filter("subtitles"):
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertTrue(os.path.isfile(out))
        else:
            self.assertEqual(res.returncode, 3)
            self.assertIn("HyperFrames", res.stderr)
            self.assertTrue(os.path.isfile(os.path.join(self.tmp, "b", "talk.srt")))

    def test_srt_input_gives_words(self):
        srt = os.path.join(self.tmp, "in.srt")
        with open(srt, "w") as handle:
            handle.write("1\n00:00:01,000 --> 00:00:02,000\nhello there world\n\n")
        words = mk.load_words(srt)
        self.assertEqual([w["text"] for w in words], ["hello", "there", "world"])
        self.assertAlmostEqual(words[0]["start"], 1.0)
        self.assertLessEqual(words[-1]["end"], 2.0)

    # ------------------------------------------------------------ stop motion
    def test_stopmotion_frames_holds_and_determinism(self):
        frames = os.path.join(self.tmp, "frames")
        os.makedirs(frames, exist_ok=True)
        for i in range(4):  # mixed sizes and formats on purpose
            ext = "png" if i % 2 else "jpg"
            size = "320x240" if i % 2 else "240x320"
            ff("-f", "lavfi", "-i", f"testsrc2=s={size}:d=1", "-ss", str(i * 0.2), "-frames:v", "1",
               os.path.join(frames, f"frame{i + 1}.{ext}"))
        a, b, c = (os.path.join(self.tmp, n) for n in ("sm_a.mp4", "sm_b.mp4", "sm_c.mp4"))
        for out, seed in ((a, 3), (b, 3), (c, 4)):
            res = tool("stopmotion.py", frames, "-o", out, "--size", "180x320", "--crf", "0",
                       "--seed", seed, "--loop", 2)
            self.assertEqual(res.returncode, 0, res.stderr)
        md5 = frame_md5s(a)
        self.assertEqual(len(md5), 4 * 2 * 2)  # 4 images x 2 loops x held on twos
        self.assertEqual(md5[0], md5[1])
        self.assertNotEqual(md5[1], md5[2])
        self.assertNotEqual(md5[0], md5[8])  # second loop wobbles differently
        self.assertEqual(md5, frame_md5s(b))
        self.assertNotEqual(md5, frame_md5s(c))
        self.assertEqual(mk.probe(a)["video"]["fps"], 24.0)

    def test_stopmotion_from_video_and_bad_folder(self):
        out = os.path.join(self.tmp, "live.mp4")
        res = tool("stopmotion.py", "--from-video", self.talk, "-o", out, "--crf", "0", "--fps", "8",
                   "--hold", "3")
        self.assertEqual(res.returncode, 0, res.stderr)
        info = mk.probe(out)
        self.assertEqual(info["video"]["fps"], 24.0)
        self.assertIsNotNone(info["audio"])
        md5 = frame_md5s(out)
        self.assertEqual(md5[0], md5[2])
        self.assertNotEqual(md5[2], md5[3])
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty, exist_ok=True)
        self.assertEqual(tool("stopmotion.py", empty, "-o", out).returncode, 2)


if __name__ == "__main__":
    unittest.main()
