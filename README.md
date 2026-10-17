# YouTube Transcript & Video Digest

提取 YouTube 字幕或本地转写视频，并可使用 Gemini 快速摘要或抽取画面帧。此仓库同时包含 agent skill 和可从命令行调用的 Python 脚本。详细工作流见 [SKILL.md](SKILL.md)。

## 功能

- 按优先级尝试 YouTube 字幕 API、yt-dlp 字幕和本地 faster-whisper 转写。
- 读取指定频道最近发布的视频。
- 用 Gemini 根据 YouTube 链接或本地音视频生成摘要。
- 按时间戳提取关键画面帧，以便核对图表、表格或字幕未覆盖的信息。
- 用 doctor 脚本检查外部依赖。

## 安装依赖

将命令中的 OWNER/REPOSITORY 替换成此仓库的地址。需要 Python 3.9+，建议使用独立 Python 环境：

~~~bash
git clone https://github.com/OWNER/REPOSITORY.git
cd youtube
python3 -m venv .venv
source .venv/bin/activate
python -m pip install yt-dlp youtube-transcript-api
~~~

额外依赖按需安装：

~~~bash
# 本地 Whisper 转写；没有字幕时的较慢回退路径
python -m pip install faster-whisper

# 系统工具：关键帧、音频处理和部分 yt-dlp 场景需要
brew install ffmpeg deno
~~~

yt-dlp 遇到 YouTube JavaScript challenge 时需要 Deno 或 Node.js。Whisper 首次运行可能下载模型。Gemini 摘要还需要 GEMINI_API_KEY 或 GOOGLE_API_KEY 环境变量；不要把 Key 写进仓库或命令历史。

检查依赖状态：

~~~bash
python3 scripts/doctor.py
python3 scripts/doctor.py --json
~~~

doctor 会检查 yt-dlp、ffmpeg、JS 运行时、字幕 API 和 faster-whisper。若只打算使用部分能力，可按缺少的功能安装对应依赖。

## 常用命令

### 提取字幕或转写

~~~bash
python3 scripts/transcript.py "https://www.youtube.com/watch?v=VIDEO_ID" --lang zh-Hans --metadata --output transcript.txt
~~~

默认顺序是字幕 API → yt-dlp captions → 本地 Whisper。也可用 --method api、--method captions 或 --method whisper 强制指定路径。常用语言代码包括 zh-Hans、en、ja。

建议保存到文件再整理，保留原视频链接和时间戳；字幕缺失时明确标注转写来源，不要猜测。

### 列出频道最近视频

~~~bash
python3 scripts/latest_video.py --channel "https://www.youtube.com/@SomeChannel" --count 3 --json
~~~

查询最近频道内容时必须明确提供 --channel（频道 URL 或 ID）。脚本不会默认选择特定频道。

### Gemini 快速摘要

~~~bash
# 确保 GEMINI_API_KEY 或 GOOGLE_API_KEY 已在当前 shell 安全配置
python3 scripts/gemini_video_digest.py "https://www.youtube.com/watch?v=VIDEO_ID" --output digest.md
~~~

也可输入本地视频 / 音频文件。未提供 source 时需用 --channel 指定频道，让脚本选择最新视频。

### 提取画面帧

~~~bash
mkdir -p ./frames
python3 scripts/latest_video.py --video-url "https://www.youtube.com/watch?v=VIDEO_ID" --timestamps 310,420,615 --output-dir ./frames
~~~

时间单位为秒，需要 ffmpeg。此流程读取视频流来定位画面，不用先完整下载整个视频。

## 选择哪种路径

| 需求 | 建议 |
|---|---|
| 需要精确引用或逐段核对 | 先提取字幕 / 转写，并保留时间戳 |
| 需要快速了解视频大意 | 可先用 Gemini，但核对关键数字和专有名词 |
| 视频没有可用字幕 | 安装 faster-whisper，使用本地转写回退 |
| 画面含重要图表或表格 | 按对应时间戳提取关键帧并目视核对 |

Gemini 处理会把视频内容发送给 Google 服务。私密或敏感视频优先使用本地 Whisper 路径；只有在获准时才把内容交给云端服务。转写和摘要都可能出错，涉及数字、时间、标的或交易判断时应回到字幕和画面逐项核验。

## 脚本索引

- **scripts/transcript.py**：字幕与转写回退流程。
- **scripts/gemini_video_digest.py**：Gemini 视频 / 音频摘要。
- **scripts/latest_video.py**：频道视频列表、视频元信息和关键帧。
- **scripts/doctor.py**：依赖健康检查。

## 许可证

当前仓库未附 LICENSE 文件。公开可见不等于授予复制、修改或再分发许可。
