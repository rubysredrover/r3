"""
Ruby's Red Rover - voice cloning prep script.

1. Ensures whisper is installed.
2. Transcribes 11 MP3 clips (Whisper "tiny", word_timestamps=True).
3. Saves per-file JSON transcripts.
4. Heuristically picks Ruby-only segments (~60s total).
5. Writes TRANSCRIPTS.md.
6. Uses ffmpeg to cut+concat selected segments into ruby_training.mp3.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

AUDIO_DIR = Path(r"C:/Users/trico/Downloads/Mars and Ruby/audio")
TRANSCRIPT_DIR = AUDIO_DIR / "transcripts"
OUT_DIR = Path(r"C:/Users/trico/OneDrive/GitHub/rubysredrover/agent/clips")
FFMPEG_BIN = Path(
    r"C:/Users/trico/OneDrive/GitHub/rubysredrover/.venv/Lib/site-packages/"
    r"imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe"
)

TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)


def ensure_ffmpeg_on_path() -> None:
    """Whisper shells out to `ffmpeg` -- make sure it can be found."""
    ffmpeg_dir = FFMPEG_BIN.parent
    # Drop a copy/symlink named ffmpeg.exe alongside the versioned binary
    target = ffmpeg_dir / "ffmpeg.exe"
    if not target.exists():
        try:
            shutil.copy2(FFMPEG_BIN, target)
        except Exception as e:
            print(f"[warn] could not copy ffmpeg.exe: {e}")
    os.environ["PATH"] = str(ffmpeg_dir) + os.pathsep + os.environ.get("PATH", "")


def ensure_whisper() -> None:
    try:
        import whisper  # noqa: F401
        return
    except ImportError:
        pass
    print("[info] installing openai-whisper...")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--quiet", "openai-whisper"]
    )


def transcribe_all() -> dict[str, dict]:
    import whisper

    print("[info] loading whisper tiny...")
    model = whisper.load_model("tiny")

    results: dict[str, dict] = {}
    mp3s = sorted(AUDIO_DIR.glob("*.mp3"))
    for i, mp3 in enumerate(mp3s, 1):
        print(f"[info] ({i}/{len(mp3s)}) transcribing {mp3.name} ...")
        out_json = TRANSCRIPT_DIR / f"{mp3.stem}.json"
        if out_json.exists():
            try:
                with out_json.open("r", encoding="utf-8") as f:
                    results[mp3.name] = json.load(f)
                print("        (cached)")
                continue
            except Exception:
                pass
        try:
            result = model.transcribe(
                str(mp3),
                word_timestamps=True,
                verbose=False,
                fp16=False,
                language="en",
            )
        except Exception as e:
            print(f"[warn] failed on {mp3.name}: {e}")
            continue
        # Trim the giant tensor refs out for the JSON dump
        slim = {
            "text": result.get("text", ""),
            "language": result.get("language"),
            "segments": [
                {
                    "id": s.get("id"),
                    "start": s.get("start"),
                    "end": s.get("end"),
                    "text": s.get("text"),
                    "avg_logprob": s.get("avg_logprob"),
                    "no_speech_prob": s.get("no_speech_prob"),
                    "compression_ratio": s.get("compression_ratio"),
                    "words": s.get("words", []),
                }
                for s in result.get("segments", [])
            ],
        }
        with out_json.open("w", encoding="utf-8") as f:
            json.dump(slim, f, ensure_ascii=False, indent=2)
        results[mp3.name] = slim
    return results


def get_duration(mp3: Path) -> float:
    """Use ffmpeg to read duration (ffprobe not bundled)."""
    try:
        out = subprocess.run(
            [str(FFMPEG_BIN), "-i", str(mp3)],
            capture_output=True,
            text=True,
        )
        # ffmpeg writes "Duration: HH:MM:SS.xx" to stderr
        for line in out.stderr.splitlines():
            line = line.strip()
            if line.startswith("Duration:"):
                ts = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = ts.split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        pass
    return 0.0


def fmt(t: float) -> str:
    m = int(t // 60)
    s = t - m * 60
    return f"{m:02d}:{s:05.2f}"


def score_segment(seg: dict) -> float:
    """
    Heuristic for "this is probably Ruby alone."
    Higher score = better candidate.
    """
    dur = (seg.get("end") or 0) - (seg.get("start") or 0)
    if dur < 1.5:
        return -1.0  # too short for cloning
    if dur > 12:
        # very long single segments often = monologue (good) but also risk overlap
        pass
    text = (seg.get("text") or "").strip()
    if not text:
        return -1.0
    no_speech = seg.get("no_speech_prob") or 0.0
    if no_speech > 0.5:
        return -1.0
    avg_lp = seg.get("avg_logprob") or -10.0
    comp = seg.get("compression_ratio") or 0.0

    # Ruby (CP) signal: moderate-to-low confidence, but not pure noise.
    # avg_logprob typically ~ -0.4 (clean adult) to -1.5 (Ruby-ish).
    # We *prefer* the lower-confidence ones.
    score = 0.0
    if -1.5 <= avg_lp <= -0.4:
        score += 2.0  # sweet spot
    elif avg_lp < -1.5:
        score += 0.5  # might be too garbled
    else:
        score += 0.2  # too clean -> probably adult

    # Compression ratio: hallucination filter. >2.4 means whisper looped.
    if comp > 2.4:
        return -1.0
    if comp < 1.6:
        score += 0.5

    # Duration bonus 2-8s
    if 2.5 <= dur <= 8.0:
        score += 1.5
    elif 1.5 <= dur < 2.5:
        score += 0.5

    # Penalize obvious adult phrases / TV
    lowered = text.lower()
    bad_phrases = [
        "subscribe",
        "thanks for watching",
        "you're watching",
        "music",
        "applause",
        "(",
        "♪",
    ]
    for bp in bad_phrases:
        if bp in lowered:
            score -= 2.0
    # Very long fully-formed sentences usually = adult
    word_count = len(text.split())
    if word_count > 18:
        score -= 1.0

    return score


def pick_clips(results: dict[str, dict], target_seconds: float = 60.0) -> list[dict]:
    """Pick best segments greedily until we hit target_seconds."""
    candidates = []
    for fname, data in results.items():
        for seg in data.get("segments", []):
            s = score_segment(seg)
            if s <= 0:
                continue
            candidates.append(
                {
                    "file": fname,
                    "start": seg["start"],
                    "end": seg["end"],
                    "duration": seg["end"] - seg["start"],
                    "text": seg.get("text", "").strip(),
                    "avg_logprob": seg.get("avg_logprob"),
                    "no_speech_prob": seg.get("no_speech_prob"),
                    "score": s,
                }
            )
    candidates.sort(key=lambda c: c["score"], reverse=True)
    picked: list[dict] = []
    total = 0.0
    used_ranges: dict[str, list[tuple[float, float]]] = {}
    for c in candidates:
        if total >= target_seconds and len(picked) >= 4:
            break
        # avoid overlap inside same file
        ranges = used_ranges.setdefault(c["file"], [])
        if any(not (c["end"] <= a or c["start"] >= b) for a, b in ranges):
            continue
        picked.append(c)
        ranges.append((c["start"], c["end"]))
        total += c["duration"]
        if len(picked) >= 8 and total >= target_seconds:
            break
    return picked


def write_transcripts_md(
    results: dict[str, dict],
    durations: dict[str, float],
    picks: list[dict],
) -> Path:
    md_path = OUT_DIR / "TRANSCRIPTS.md"
    lines: list[str] = []
    lines.append("# Ruby Audio Transcripts (Whisper tiny)")
    lines.append("")
    lines.append(
        "Generated for ElevenLabs Instant Voice Cloning prep "
        "(Ruby's Red Rover v2 hackathon, 2026-04-29)."
    )
    lines.append("")
    lines.append(
        "Whisper `tiny` was used; low confidence segments are *expected* "
        "for Ruby (CP) and treated as a positive signal."
    )
    lines.append("")
    for fname in sorted(results.keys()):
        data = results[fname]
        dur = durations.get(fname, 0.0)
        lines.append(f"## {fname}")
        lines.append("")
        lines.append(f"- Duration: {fmt(dur)} ({dur:.2f}s)")
        lines.append(f"- Segments: {len(data.get('segments', []))}")
        lines.append("")
        lines.append("| start | end | avg_logprob | no_speech | text |")
        lines.append("|-------|-----|-------------|-----------|------|")
        for seg in data.get("segments", []):
            txt = (seg.get("text") or "").strip().replace("|", "\\|")
            if len(txt) > 110:
                txt = txt[:107] + "..."
            lines.append(
                f"| {fmt(seg['start'])} | {fmt(seg['end'])} | "
                f"{(seg.get('avg_logprob') or 0):.2f} | "
                f"{(seg.get('no_speech_prob') or 0):.2f} | {txt} |"
            )
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## RECOMMENDED RUBY-ONLY TRAINING CLIPS")
    lines.append("")
    total = sum(p["duration"] for p in picks)
    lines.append(f"Target ~60s. Selected {len(picks)} segments totaling {total:.1f}s.")
    lines.append("")
    for p in picks:
        lines.append(
            f"- `{p['file']} [{fmt(p['start'])} - {fmt(p['end'])}]` "
            f"({p['duration']:.1f}s) -- "
            f"avg_logprob={p['avg_logprob']:.2f}, "
            f"no_speech={p['no_speech_prob']:.2f}"
        )
        reason = []
        if p["avg_logprob"] and -1.5 <= p["avg_logprob"] <= -0.7:
            reason.append("low-but-not-broken confidence (Ruby signal)")
        if 2.5 <= p["duration"] <= 8.0:
            reason.append("clean cloning length")
        if (p["no_speech_prob"] or 0) < 0.2:
            reason.append("clear speech")
        if not reason:
            reason.append("decent overall score")
        lines.append(f"  - reason: {', '.join(reason)}")
        lines.append(f"  - text: \"{p['text'][:140]}\"")
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def cut_and_concat(picks: list[dict]) -> Path | None:
    if not picks:
        return None
    tmp_dir = OUT_DIR / "_tmp_segments"
    tmp_dir.mkdir(exist_ok=True)
    seg_paths: list[Path] = []
    for i, p in enumerate(picks):
        src = AUDIO_DIR / p["file"]
        out = tmp_dir / f"seg_{i:02d}.mp3"
        cmd = [
            str(FFMPEG_BIN),
            "-y",
            "-ss",
            f"{p['start']:.3f}",
            "-to",
            f"{p['end']:.3f}",
            "-i",
            str(src),
            "-acodec",
            "libmp3lame",
            "-ar",
            "44100",
            "-ac",
            "1",
            "-b:a",
            "192k",
            str(out),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"[warn] ffmpeg cut failed for {p['file']}: {r.stderr[-300:]}")
            continue
        seg_paths.append(out)
    if not seg_paths:
        return None
    list_file = tmp_dir / "concat_list.txt"
    list_file.write_text(
        "\n".join(f"file '{sp.as_posix()}'" for sp in seg_paths),
        encoding="utf-8",
    )
    final = OUT_DIR / "ruby_training.mp3"
    cmd = [
        str(FFMPEG_BIN),
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        str(final),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        # fallback: re-encode concat
        cmd2 = [
            str(FFMPEG_BIN),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-acodec",
            "libmp3lame",
            "-ar",
            "44100",
            "-ac",
            "1",
            "-b:a",
            "192k",
            str(final),
        ]
        r2 = subprocess.run(cmd2, capture_output=True, text=True)
        if r2.returncode != 0:
            print(f"[err] concat failed: {r2.stderr[-300:]}")
            return None
    return final


def main() -> int:
    ensure_ffmpeg_on_path()
    ensure_whisper()
    results = transcribe_all()
    durations = {f: get_duration(AUDIO_DIR / f) for f in results.keys()}
    picks = pick_clips(results, target_seconds=60.0)
    md = write_transcripts_md(results, durations, picks)
    print(f"[ok] wrote {md}")
    final = cut_and_concat(picks)
    if final and final.exists():
        size = final.stat().st_size
        print(f"[ok] wrote {final} ({size/1024:.1f} KB)")
    else:
        print("[warn] ruby_training.mp3 was not created")
    print("---")
    print("PICKS:")
    for p in picks:
        print(
            f"  {p['file']} [{fmt(p['start'])} - {fmt(p['end'])}] "
            f"({p['duration']:.1f}s) score={p['score']:.2f}"
        )
    print(f"  total: {sum(p['duration'] for p in picks):.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
