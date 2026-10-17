---
name: youtube-transcript
description: 提取 YouTube 字幕或转写视频，支持频道最新视频及 Gemini 视频摘要；用于总结、翻译和转写。
---

# YouTube Transcript Extractor

## Goal

Extract transcripts from any YouTube video using the most reliable method available. Supports automatic fallback across 4 methods. Also supports Gemini direct YouTube URL digestion for fast summaries and chart/table extraction. Fetches latest videos from channels.

## Health Check

Run to verify all dependencies are working:
```bash
python3 scripts/doctor.py
```

## Quick Start — Any Video

### Gemini fast digest

Use Gemini first when the user wants a quick summary, translation, chart/table read, or ticker/number extraction and exact transcript grounding is not yet required:

```bash
GEMINI_API_KEY="$GEMINI_API_KEY" \
  python3 scripts/gemini_video_digest.py "VIDEO_URL" \
  -o /tmp/youtube_VIDEO_ID_gemini_digest.md
```

When no video source is provided, pass `--channel` with the channel URL or ID:

```bash
GEMINI_API_KEY="$GEMINI_API_KEY" \
  python3 scripts/gemini_video_digest.py \
  --channel "https://www.youtube.com/@SomeChannel"
```

Local video/audio upload is supported:

```bash
GEMINI_API_KEY="$GEMINI_API_KEY" \
  python3 scripts/gemini_video_digest.py /path/to/video.mp4
```

- Read keys only from `GEMINI_API_KEY` or `GOOGLE_API_KEY`; never write keys to output files.
- Gemini can misread numbers, tickers, timestamps, or chart context. For trade-critical levels, validate with transcript/captions/key frames.
- If Gemini fails or output is thin, use the transcript pipeline below.

### Transcript path

```bash
# 1. Get transcript (auto-detect best method)
python3 scripts/transcript.py "VIDEO_URL" -o /tmp/transcript.txt

# 2. Get video metadata + transcript together
python3 scripts/transcript.py "VIDEO_URL" --metadata -o /tmp/transcript.txt

# 3. Read and summarize
cat /tmp/transcript.txt
```

## Quick Start — Latest from Channel

```bash
# List the latest videos from a channel
python3 scripts/latest_video.py --channel "https://www.youtube.com/@SomeChannel" --count 1

# List more videos and return JSON
python3 scripts/latest_video.py --channel "https://www.youtube.com/@SomeChannel" --count 3 --json
```

## Transcript Pipeline (3-Method Fallback)

Learned from Agent-Reach architecture: each method has a provider, fallback chain is automatic.

| # | Method | Speed | Requires | When to use |
|---|--------|-------|----------|-------------|
| 1 | `api` | ⚡ fastest | youtube-transcript-api | Subtitles exist (manual or auto) |
| 2 | `captions` | 🚀 fast | yt-dlp + deno/node | API fails, yt-dlp can extract auto-subs |
| 3 | `whisper` | 🐌 slower | faster-whisper + ffmpeg | No subs at all, local audio transcription |

### Auto mode (default — try all in order):
```bash
python3 scripts/transcript.py "VIDEO_URL"
```

### Force specific method:
```bash
python3 scripts/transcript.py "VIDEO_URL" --method api
python3 scripts/transcript.py "VIDEO_URL" --method captions
python3 scripts/transcript.py "VIDEO_URL" --method whisper
```

### Language preference:
```bash
python3 scripts/transcript.py "VIDEO_URL" --lang zh-Hans   # Chinese (default)
python3 scripts/transcript.py "VIDEO_URL" --lang en         # English
python3 scripts/transcript.py "VIDEO_URL" --lang ja         # Japanese
```

## Manual Fallback (when all scripts fail)

### Method A: yt-dlp subtitle dump (direct)
```bash
yt-dlp --skip-download --write-auto-sub --sub-lang zh-Hans --sub-format vtt \
  -o "/tmp/subs" "VIDEO_URL"
cat /tmp/subs.zh-Hans.vtt
```

### Method B: yt-dlp JSON3 subtitle (structured)
```bash
yt-dlp --skip-download --write-auto-sub --sub-lang en --sub-format json3 \
  -o "/tmp/subs" "VIDEO_URL"
# Parse with jq or python3
```

### Method C: Audio download + local Whisper
```bash
yt-dlp -f ba --extract-audio --audio-format mp3 --audio-quality 5 \
  -o "/tmp/yt_%(id)s.%(ext)s" "VIDEO_URL"
python3 -c "
from faster_whisper import WhisperModel
model = WhisperModel('small', device='cpu', compute_type='int8')
segments, _ = model.transcribe('/tmp/yt_VIDEO_ID.mp3', language='zh', beam_size=5)
for seg in segments:
    mm, ss = divmod(int(seg.start), 60)
    print(f'[{mm:02d}:{ss:02d}] {seg.text}')
"
```

## Key Frames

Extract frames when the transcript references on-screen data (charts, tables)
that matters for the summary:

```bash
python3 scripts/latest_video.py --video-url "VIDEO_URL" --timestamps 3100,3130,3175 --output-dir /tmp
```

Seeks the video's stream URL directly with ffmpeg — no full download. Returns
JSON with the saved frame paths. Requires `ffmpeg`.

## Channel-specific workflow

Pass the channel URL or ID explicitly when listing recent videos. If a separate workflow exists for a channel, follow that workflow; otherwise, use the transcript and summary steps above.

## Summary Format (Finance Videos)

Start with: `标题 | 频道 | 发布日期 | 时长 | 链接`

Then structure:

- **一句话结论**: Core call in one sentence.
- **核心观点**: Market regime, direction, thesis, timing.
- **宏观/消息**: Fed, data, earnings, policy, geopolitics.
- **板块与主题**: Sector rotation, themes.
- **个股/ETF**: Tickers with table (标的 / 方向/观点 / 关键位/条件 / 风险).
- **交易含义**: What supports continuation, what invalidates it, what to watch next.
- **风险提醒**: Chasing, event, liquidity, concentration risks, promo disclosures.

Use tables when there are multiple tickers or price levels.

When using Gemini output as the first pass, keep uncertain numbers marked as `待确认` until confirmed by transcript, captions, or screenshot/frame evidence.

引用实际视频链接及相关时间戳；转写项目仓库只可标为工具来源，不能替代内容来源。

### Manual frame fallback

Only when the Key Frames script above is unavailable:

```bash
VIDEO_URL=$(yt-dlp -f "best[height<=480]/best" --get-url "URL" | head -1)
ffmpeg -ss TIMESTAMP -i "$VIDEO_URL" -vframes 1 -q:v 2 /tmp/frame.jpg -y
```

## Dependencies

Core (always needed):
- Python 3.9+
- yt-dlp (`pip install yt-dlp`)
- youtube-transcript-api (`pip install youtube-transcript-api`)
- ffmpeg (`brew install ffmpeg`)
- deno or node (for yt-dlp JS challenges — `brew install deno`)

Optional (for audio transcription):
- faster-whisper (`pip install faster-whisper`) — local Whisper model

Optional (for Gemini fast digest):
- `GEMINI_API_KEY` or `GOOGLE_API_KEY`

## Failure Handling

- `youtube_transcript_api` 429 → wait 60s retry, then auto-fallback to captions.
- yt-dlp no captions → **automatically** proceed to local faster-whisper (no user prompt).
- Gemini URL digest fails or misses obvious numbers → try local video upload, then transcript/captions/Whisper.
- All transcription fails → report failure, do NOT invent content.
- Network blocks → report error, suggest retry or VPN.
- Always save transcript to file before summarizing (never dump full transcript to stdout).

## Scripts Reference

| Script | Purpose |
|--------|---------|
| `scripts/transcript.py` | Multi-method transcript extraction (main tool) |
| `scripts/gemini_video_digest.py` | Gemini direct URL/local video digest |
| `scripts/latest_video.py` | Fetch latest video(s) from a channel |
| `scripts/doctor.py` | Health check for all dependencies |
