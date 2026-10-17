#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unified YouTube transcript extraction with multi-method fallback.

Fallback chain (learned from Agent-Reach architecture):
  1. youtube-transcript-api  — fastest, works when manual/auto subs exist
  2. yt-dlp subtitle export  — uses deno/node for JS challenges, broader coverage
  3. Local faster-whisper     — last resort, downloads model on first use

Usage:
  python3 transcript.py "VIDEO_URL"                     # auto mode (try all)
  python3 transcript.py "VIDEO_URL" --method api        # force youtube-transcript-api
  python3 transcript.py "VIDEO_URL" --method captions   # force yt-dlp captions
  python3 transcript.py "VIDEO_URL" --method whisper    # force audio transcription
  python3 transcript.py "VIDEO_URL" -o /tmp/output.txt  # save to file
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple


def extract_video_id(url: str) -> str:
    """Extract video ID from various YouTube URL formats."""
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:embed/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$',
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return url  # fallback: assume it's already an ID


def method_api(video_id: str, languages: Optional[List[str]] = None) -> Optional[str]:
    """Method 1: youtube-transcript-api (fastest)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("[api] youtube-transcript-api not installed, skipping", file=sys.stderr)
        return None

    langs = languages or ['zh-Hans', 'zh-Hant', 'yue', 'zh', 'en']
    try:
        api = YouTubeTranscriptApi()
        transcript = api.fetch(video_id, languages=langs)
        lines = []
        for item in transcript:
            ts = int(item.start)
            mm, ss = divmod(ts, 60)
            hh, mm = divmod(mm, 60)
            if hh:
                lines.append(f"[{hh:02d}:{mm:02d}:{ss:02d}] {item.text}")
            else:
                lines.append(f"[{mm:02d}:{ss:02d}] {item.text}")
        result = '\n'.join(lines)
        if result.strip():
            print(f"[api] Success: {len(lines)} lines", file=sys.stderr)
            return result
        return None
    except Exception as e:
        print(f"[api] Failed: {e}", file=sys.stderr)
        return None


def method_captions(url: str, lang: str = "zh-Hans") -> Optional[str]:
    """Method 2: yt-dlp subtitle extraction (uses deno/node for JS challenges)."""
    if not shutil.which("yt-dlp"):
        print("[captions] yt-dlp not found, skipping", file=sys.stderr)
        return None

    with tempfile.TemporaryDirectory(prefix="yt-captions-") as tmpdir:
        out_template = os.path.join(tmpdir, "sub")
        # Try requested language first, then English as fallback
        for sub_lang in [lang, "en"]:
            cmd = [
                "yt-dlp",
                "--skip-download",
                "--write-auto-sub",
                "--sub-lang", sub_lang,
                "--sub-format", "vtt",
                "-o", out_template,
                url,
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired:
                print(f"[captions] Timeout for lang={sub_lang}", file=sys.stderr)
                continue

            # Find the subtitle file
            sub_files = list(Path(tmpdir).glob("*.vtt"))
            if not sub_files:
                continue

            vtt_content = sub_files[0].read_text(encoding='utf-8')
            result = parse_vtt(vtt_content)
            if result.strip():
                print(f"[captions] Success ({sub_lang}): {len(result.splitlines())} lines", file=sys.stderr)
                return result

        # Also try json3 format for better timestamp extraction
        for sub_lang in [lang, "en"]:
            cmd = [
                "yt-dlp",
                "--skip-download",
                "--write-auto-sub",
                "--sub-lang", sub_lang,
                "--sub-format", "json3",
                "-o", out_template,
                url,
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired:
                continue

            json_files = list(Path(tmpdir).glob("*.json3"))
            if not json_files:
                continue

            result = parse_json3(json_files[0])
            if result.strip():
                print(f"[captions] Success ({sub_lang} json3): {len(result.splitlines())} lines", file=sys.stderr)
                return result

    print("[captions] No subtitles found", file=sys.stderr)
    return None


def parse_vtt(vtt_text: str) -> str:
    """Parse VTT subtitle format into timestamped text."""
    lines = []
    seen = set()
    for line in vtt_text.split('\n'):
        line = line.strip()
        # Skip headers, metadata, positioning
        if not line or line.startswith('WEBVTT') or line.startswith('Kind:') or line.startswith('Language:'):
            continue
        # Skip timestamp lines
        if '-->' in line:
            # Extract start timestamp
            ts_match = re.match(r'(\d{2}):(\d{2}):(\d{2})', line)
            if ts_match:
                hh, mm, ss = int(ts_match.group(1)), int(ts_match.group(2)), int(ts_match.group(3))
                total_sec = hh * 3600 + mm * 60 + ss
                current_ts = f"[{mm:02d}:{ss:02d}]" if hh == 0 else f"[{hh:02d}:{mm:02d}:{ss:02d}]"
            continue
        # Skip numeric-only lines (cue identifiers)
        if line.isdigit():
            continue
        # Remove HTML tags
        clean = re.sub(r'<[^>]+>', '', line)
        # Remove duplicate lines (common in auto-captions)
        if clean not in seen:
            seen.add(clean)
            lines.append(f"{current_ts} {clean}" if 'current_ts' in dir() else clean)
    return '\n'.join(lines)


def parse_json3(json_path: Path) -> str:
    """Parse json3 subtitle format (yt-dlp output) into timestamped text."""
    try:
        data = json.loads(json_path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return ""

    lines = []
    for event in data.get('events', []):
        if 'segs' not in event:
            continue
        text = ''.join(seg.get('utf8', '') for seg in event['segs']).strip()
        if not text or text == '\n':
            continue
        # Timestamp in milliseconds
        start_ms = event.get('tStartMs', 0)
        total_sec = start_ms // 1000
        hh, remainder = divmod(total_sec, 3600)
        mm, ss = divmod(remainder, 60)
        ts = f"[{hh:02d}:{mm:02d}:{ss:02d}]" if hh else f"[{mm:02d}:{ss:02d}]"
        text = re.sub(r'\n+', ' ', text)
        lines.append(f"{ts} {text}")

    return '\n'.join(lines)


def method_local_whisper(url: str, model: str = "small", lang: str = "zh") -> Optional[str]:
    """Method 3: Local faster-whisper (last resort, downloads model on first use).

    `lang` is normalized to faster-whisper's 2-letter codes:
      zh-Hans / zh-Hant / yue → zh
      en, ja, ko etc. pass through
      None / "auto" → let whisper detect
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("[whisper] faster-whisper not installed (pip install faster-whisper)", file=sys.stderr)
        return None
    if not shutil.which("yt-dlp") or not shutil.which("ffmpeg"):
        print("[whisper] yt-dlp or ffmpeg not found", file=sys.stderr)
        return None

    with tempfile.TemporaryDirectory(prefix="yt-whisper-") as tmpdir:
        audio_path = os.path.join(tmpdir, "audio.mp3")
        cmd = [
            "yt-dlp", "-f", "ba", "--extract-audio", "--audio-format", "mp3",
            "--audio-quality", "5", "-o", audio_path, url,
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=True)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
            print(f"[whisper] Audio download failed: {e}", file=sys.stderr)
            return None

        audio_files = list(Path(tmpdir).glob("audio.*"))
        if not audio_files:
            print("[whisper] No audio file", file=sys.stderr)
            return None

        try:
            wm = WhisperModel(model, device="cpu", compute_type="int8")
            # Normalize lang to faster-whisper 2-letter codes.
            # "auto" or None lets whisper detect; everything else maps to its prefix.
            normalized = None
            if lang and lang.lower() != "auto":
                normalized = lang.split("-")[0].lower()
                if normalized == "yue":
                    normalized = "zh"
            segments, info = wm.transcribe(
                str(audio_files[0]),
                language=normalized,
                beam_size=5,
            )
            lines = []
            for seg in segments:
                ts = int(seg.start)
                mm, ss = divmod(ts, 60)
                lines.append(f"[{mm:02d}:{ss:02d}] {seg.text}")
            result = '\n'.join(lines)
            if result.strip():
                print(f"[whisper] Success ({model}): {len(lines)} segments", file=sys.stderr)
                return result
            return None
        except Exception as e:
            print(f"[whisper] Transcription failed: {e}", file=sys.stderr)
            return None


def get_transcript(
    url: str,
    method: str = "auto",
    lang: str = "zh-Hans",
    whisper_model: str = "small",
) -> Optional[str]:
    """Main entry: extract transcript using specified or auto-selected method.

    Args:
        url: YouTube video URL or ID
        method: 'auto', 'api', 'captions', 'whisper'
        lang: Preferred subtitle language for api/captions methods
        whisper_model: faster-whisper model size

    Returns:
        Transcript text or None if all methods fail.
    """
    video_id = extract_video_id(url)
    methods = {
        'api': lambda: method_api(video_id),
        'captions': lambda: method_captions(url, lang),
        'whisper': lambda: method_local_whisper(url, whisper_model, lang),
    }

    if method != 'auto':
        if method in methods:
            return methods[method]()
        print(f"Unknown method: {method}", file=sys.stderr)
        return None

    # Auto: try in order of speed/cost
    order = ['api', 'captions', 'whisper']
    for m in order:
        print(f"[auto] Trying {m}...", file=sys.stderr)
        result = methods[m]()
        if result:
            return result
        print(f"[auto] {m} returned nothing, trying next", file=sys.stderr)

    return None


def get_video_metadata(url: str) -> dict:
    """Get video metadata via yt-dlp."""
    if not shutil.which("yt-dlp"):
        return {}
    cmd = ["yt-dlp", "--skip-download", "--dump-json", "--no-warnings", url]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode == 0:
            return json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return {}


def main():
    parser = argparse.ArgumentParser(description="Extract YouTube video transcript")
    parser.add_argument("url", help="YouTube video URL or ID")
    parser.add_argument("-o", "--output", help="Save transcript to file")
    parser.add_argument(
        "--method", choices=["auto", "api", "captions", "whisper"],
        default="auto", help="Extraction method (default: auto)"
    )
    parser.add_argument("--lang", default="zh-Hans", help="Preferred subtitle language")
    parser.add_argument("--whisper-model", default="small", help="faster-whisper model size")
    parser.add_argument("--metadata", action="store_true", help="Also print video metadata")
    args = parser.parse_args()

    if args.metadata:
        meta = get_video_metadata(args.url)
        if meta:
            print(f"标题: {meta.get('title', 'N/A')}")
            print(f"频道: {meta.get('channel', 'N/A')}")
            print(f"日期: {meta.get('upload_date', 'N/A')}")
            print(f"时长: {meta.get('duration_string', 'N/A')}")
            print(f"链接: {meta.get('webpage_url', args.url)}")
            print()

    transcript = get_transcript(args.url, method=args.method, lang=args.lang, whisper_model=args.whisper_model)

    if transcript:
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(transcript, encoding='utf-8')
            print(f"Saved to {args.output}", file=sys.stderr)
        else:
            print(transcript)
    else:
        print("All methods failed. Video may be private, deleted, or region-restricted.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
