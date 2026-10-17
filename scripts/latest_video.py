#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch latest video(s) from a YouTube channel.

Usage:
  python3 latest_video.py --channel "https://www.youtube.com/@SomeChannel"
  python3 latest_video.py --channel UCxxxxxx --count 3
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from typing import List, Optional


DEFAULT_CHANNEL = None


def get_latest_videos(channel_url: str, count: int = 1) -> List[dict]:
    """Get latest videos from a YouTube channel using yt-dlp.

    Args:
        channel_url: Channel URL or ID
        count: Number of videos to return

    Returns:
        List of dicts with keys: id, title, url, upload_date, duration_string, webpage_url
    """
    # Determine the playlist URL
    if "/@" in channel_url or "channel/" in channel_url:
        # Channel URL → videos tab
        if channel_url.endswith("/videos"):
            playlist_url = channel_url
        elif "/@" in channel_url:
            playlist_url = channel_url.rstrip("/") + "/videos"
        else:
            playlist_url = channel_url.rstrip("/") + "/videos"
    else:
        # Assume it's a channel ID
        playlist_url = f"https://www.youtube.com/channel/{channel_url}/videos"

    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        "--no-warnings",
        "--playlist-end", str(count),
        playlist_url,
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            print(f"yt-dlp error: {proc.stderr[:300]}", file=sys.stderr)
            return []

        videos = []
        for line in proc.stdout.strip().split('\n'):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                video_id = data.get('id', '')
                videos.append({
                    'id': video_id,
                    'title': data.get('title', 'N/A'),
                    'url': data.get('url', video_id),
                    'webpage_url': f"https://www.youtube.com/watch?v={video_id}",
                    'upload_date': data.get('upload_date', 'N/A'),
                    'duration_string': data.get('duration_string', 'N/A'),
                    'view_count': data.get('view_count', 0),
                })
            except json.JSONDecodeError:
                continue
        return videos

    except subprocess.TimeoutExpired:
        print("yt-dlp timed out", file=sys.stderr)
        return []


def get_video_details(video_url: str) -> Optional[dict]:
    """Get full metadata for a single video."""
    cmd = ["yt-dlp", "--skip-download", "--dump-json", "--no-warnings", video_url]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode == 0:
            return json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return None


def extract_frames(video_url: str, timestamps: List[int], output_dir: str = "/tmp") -> List[str]:
    """Extract key frames from a video at given timestamps (seconds).

    Uses ffmpeg seek against the video's stream URL — no full download.
    Returns a list of saved frame paths.
    """
    cmd = ["yt-dlp", "-f", "best[height<=480]/best", "--get-url", video_url]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to get stream URL: {proc.stderr.strip()}")
    stream_url = proc.stdout.strip().split("\n")[0]

    procs = []
    for t in timestamps:
        out_path = os.path.join(output_dir, f"frame_{t}.jpg")
        ffmpeg_cmd = [
            "ffmpeg", "-ss", str(t),
            "-i", stream_url,
            "-vframes", "1", "-update", "1",
            "-q:v", "2", out_path, "-y",
        ]
        procs.append((out_path, subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)))

    paths = []
    for out_path, p in procs:
        p.wait()
        if p.returncode == 0 and os.path.exists(out_path):
            paths.append(out_path)

    return paths


def main():
    parser = argparse.ArgumentParser(description="Fetch latest YouTube video(s) from a channel")
    parser.add_argument(
        "--channel", "-c", default=DEFAULT_CHANNEL,
        help="Channel URL or ID (required when listing recent videos)",
    )
    parser.add_argument("--count", "-n", type=int, default=1, help="Number of videos")
    parser.add_argument("--details", "-d", action="store_true", help="Include full metadata")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--video-url",
        help="Extract key frames from this video URL instead of listing videos (use with --timestamps)",
    )
    parser.add_argument(
        "--timestamps",
        help="Comma-separated timestamps in seconds for frame extraction (e.g. 3100,3130,3175)",
    )
    parser.add_argument(
        "--output-dir",
        default="/tmp",
        help="Directory to save extracted frames (default: /tmp)",
    )
    args = parser.parse_args()

    if args.video_url and args.timestamps:
        if not shutil.which("ffmpeg"):
            print("error: ffmpeg not found; install with: brew install ffmpeg", file=sys.stderr)
            sys.exit(1)
        timestamps = [int(t.strip()) for t in args.timestamps.split(",")]
        try:
            paths = extract_frames(args.video_url, timestamps, args.output_dir)
            print(json.dumps({"frames": paths}, ensure_ascii=False, indent=2))
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    if not args.channel:
        parser.error("--channel is required when listing recent videos")
    videos = get_latest_videos(args.channel, args.count)
    if not videos:
        print("No videos found.", file=sys.stderr)
        sys.exit(1)

    if args.details:
        detailed = []
        for v in videos:
            meta = get_video_details(v['webpage_url'])
            if meta:
                detailed.append(meta)
            else:
                detailed.append(v)
        videos = detailed

    if args.json:
        print(json.dumps(videos, ensure_ascii=False, indent=2))
    else:
        for i, v in enumerate(videos, 1):
            print(f"--- Video {i} ---")
            print(f"ID:       {v.get('id', 'N/A')}")
            print(f"标题:     {v.get('title', 'N/A')}")
            print(f"日期:     {v.get('upload_date', 'N/A')}")
            print(f"时长:     {v.get('duration_string', 'N/A')}")
            print(f"链接:     {v.get('webpage_url', 'N/A')}")
            if v.get('view_count'):
                print(f"播放量:   {v['view_count']:,}")
            print()


if __name__ == "__main__":
    main()
