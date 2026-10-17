#!/usr/bin/env python3
"""Use Gemini REST APIs to summarize a finance YouTube video.

The API key is read from GEMINI_API_KEY or GOOGLE_API_KEY. It is never written
to output files.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


API_ROOT = "https://generativelanguage.googleapis.com"
DEFAULT_CHANNEL = None
SCRIPTS_DIR = Path(__file__).resolve().parent


FINANCE_PROMPT = """你是一个交易研究助理。请分析这个金融/交易类 YouTube 视频。

输出中文 Markdown，必须包含：

1. 标题 / 频道 / 发布日期 / 时长 / 链接（能识别多少写多少）。
2. 一句话结论：视频最核心的市场判断或交易主题。
3. 核心观点：市场方向、节奏、催化剂、时间窗口。
4. 宏观/消息：Fed、数据、财报、政策、地缘、美元、利率、流动性。
5. 板块与主题：AI、半导体、软件、能源、金融、crypto、中国资产等。
6. 个股/ETF 表格：标的、方向/观点、关键位/条件、风险。
7. 交易含义：什么支持延续，什么触发失效，接下来观察什么。
8. 风险提醒：追高、事件、流动性、仓位、广告/利益披露。
9. 提取所有听到或画面出现的重要数字：价格、strike、百分比、日期、估值、营收、EPS、目标价、支撑/阻力。

严格要求：
- 不确定的数字用 [?] 标注。
- 不要省略 ticker、价格、百分比、日期。
- 画面里出现但口播没有读出来的信息，标注“屏幕数据/需复核”。
- 不要编造视频没有覆盖的标的或观点；没有讲就写“未覆盖”。
- 不要给投资建议或下单指令，只做决策辅助。
- 不要输出长篇逐字稿；优先输出结构化交易摘要。
"""


def ytdlp_bin() -> str:
    return shutil.which("yt-dlp") or "yt-dlp"


def is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def yyyymmdd_to_iso(value: str) -> str:
    if re.fullmatch(r"\d{8}", value):
        return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
    return value


def request_json(url: str, api_key: str, payload: dict | None = None, headers: dict | None = None) -> dict:
    sep = "&" if "?" in url else "?"
    full_url = f"{url}{sep}key={urllib.parse.quote(api_key)}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(full_url, data=data, headers=headers or {})
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:1000]}") from exc


def run_json(cmd: list[str], timeout: int = 90) -> dict | list:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"command failed: {' '.join(cmd)}")
    return json.loads(proc.stdout)


def resolve_latest_video(channel: str) -> tuple[str, dict]:
    latest_script = SCRIPTS_DIR / "latest_video.py"
    if latest_script.exists():
        items = run_json([sys.executable, str(latest_script), "--channel", channel, "--count", "1", "--json"])
        if items:
            item = items[0]
            return item.get("webpage_url") or f"https://www.youtube.com/watch?v={item['id']}", item

    playlist_url = channel.rstrip("/") + "/videos" if "/@" in channel and not channel.endswith("/videos") else channel
    meta = run_json(
        [
            ytdlp_bin(),
            "--flat-playlist",
            "--dump-json",
            "--no-warnings",
            "--playlist-end",
            "1",
            playlist_url,
        ]
    )
    item = meta[0] if isinstance(meta, list) else meta
    video_id = item.get("id")
    if not video_id:
        raise RuntimeError("Could not resolve latest video id")
    item["webpage_url"] = f"https://www.youtube.com/watch?v={video_id}"
    return item["webpage_url"], item


def video_metadata(source: str) -> dict:
    if not is_url(source):
        return {}
    proc = subprocess.run(
        [
            ytdlp_bin(),
            "--skip-download",
            "--dump-json",
            "--no-warnings",
            source,
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if proc.returncode != 0:
        return {}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}


def start_resumable_upload(path: Path, api_key: str, mime_type: str) -> str:
    size = path.stat().st_size
    url = f"{API_ROOT}/upload/v1beta/files?key={urllib.parse.quote(api_key)}"
    payload = json.dumps({"file": {"display_name": path.name}}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(size),
            "X-Goog-Upload-Header-Content-Type": mime_type,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            upload_url = resp.headers.get("X-Goog-Upload-URL")
            if not upload_url:
                raise RuntimeError("Gemini did not return X-Goog-Upload-URL")
            return upload_url
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Upload start failed HTTP {exc.code}: {body[:1000]}") from exc


def finish_upload(path: Path, upload_url: str, mime_type: str) -> dict:
    data = path.read_bytes()
    req = urllib.request.Request(
        upload_url,
        data=data,
        headers={
            "Content-Length": str(len(data)),
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
            "Content-Type": mime_type,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Upload finalize failed HTTP {exc.code}: {body[:1000]}") from exc


def wait_active(file_name: str, api_key: str, max_wait_s: int = 300) -> dict:
    deadline = time.time() + max_wait_s
    url = f"{API_ROOT}/v1beta/{file_name}"
    last = {}
    while time.time() < deadline:
        last = request_json(url, api_key)
        state = last.get("state")
        if state in (None, "ACTIVE"):
            return last
        if state == "FAILED":
            raise RuntimeError(f"Gemini file processing failed: {last}")
        time.sleep(5)
    raise TimeoutError(f"File did not become ACTIVE in {max_wait_s}s: {last}")


def generate_digest(file_uri: str, mime_type: str, api_key: str, model: str, prompt: str) -> str:
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"fileData": {"mimeType": mime_type, "fileUri": file_uri}},
                    {"text": prompt},
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "topP": 0.8,
        },
    }
    data = request_json(f"{API_ROOT}/v1beta/models/{model}:generateContent", api_key, payload=payload)
    pieces = []
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            if "text" in part:
                pieces.append(part["text"])
    if not pieces:
        raise RuntimeError(f"Gemini returned no text: {json.dumps(data)[:1000]}")
    return "\n".join(pieces).strip()


def default_output_path(meta: dict, source: str) -> Path:
    date = yyyymmdd_to_iso(str(meta.get("upload_date") or meta.get("release_date") or time.strftime("%Y%m%d")))
    video_id = meta.get("id")
    if not video_id and is_url(source):
        match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", source)
        video_id = match.group(1) if match else "video"
    stem = f"youtube_{date}_{video_id or 'video'}_gemini_digest.md"
    return Path.cwd() / "youtube_digests" / stem


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a Gemini digest from a finance YouTube video file or URL.")
    parser.add_argument("source", nargs="?", help="Local video/audio path or YouTube URL. Omit to use latest channel upload.")
    parser.add_argument("--channel", default=DEFAULT_CHANNEL, help="Channel URL or ID when source is omitted")
    parser.add_argument("-o", "--output", help="Markdown output path")
    parser.add_argument("--model", default="gemini-flash-latest", help="Gemini model name")
    parser.add_argument("--prompt-file", help="Optional custom prompt file")
    parser.add_argument("--max-wait-s", type=int, default=300, help="Max wait for file processing")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERR: set GEMINI_API_KEY or GOOGLE_API_KEY", file=sys.stderr)
        return 2

    source = args.source
    latest_meta = {}
    if not source:
        if not args.channel:
            parser.error("--channel is required when SOURCE is omitted")
        source, latest_meta = resolve_latest_video(args.channel)
        print(f"[gemini] latest video: {latest_meta.get('id', '')}|{latest_meta.get('title', '')}|{source}", file=sys.stderr)

    prompt = Path(args.prompt_file).read_text(encoding="utf-8") if args.prompt_file else FINANCE_PROMPT
    meta = latest_meta or video_metadata(source)
    out = Path(args.output).expanduser() if args.output else default_output_path(meta, source)

    if is_url(source):
        mime_type = "video/mp4"
        file_uri = source
        print(f"[gemini] using URL directly: {source}", file=sys.stderr)
    else:
        video = Path(source).expanduser().resolve()
        if not video.exists():
            print(f"ERR: missing video file: {video}", file=sys.stderr)
            return 2
        mime_type = mimetypes.guess_type(video.name)[0] or "video/mp4"
        print(f"[gemini] upload start: {video.name} ({mime_type}, {video.stat().st_size} bytes)", file=sys.stderr)
        upload_url = start_resumable_upload(video, api_key, mime_type)
        uploaded = finish_upload(video, upload_url, mime_type)
        file_obj = uploaded.get("file", uploaded)
        file_name = file_obj.get("name")
        file_uri = file_obj.get("uri")
        if not file_name or not file_uri:
            raise RuntimeError(f"Unexpected upload response: {uploaded}")
        print(f"[gemini] processing: {file_name}", file=sys.stderr)
        active = wait_active(file_name, api_key, args.max_wait_s)
        file_uri = active.get("uri", file_uri)

    print(f"[gemini] generating digest with {args.model}", file=sys.stderr)
    text = generate_digest(file_uri, mime_type, api_key, args.model, prompt)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    print(f"[gemini] saved: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
