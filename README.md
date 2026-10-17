# youtube-transcript

提取 YouTube 字幕或转写视频，支持频道最新视频及 Gemini 视频摘要；用于总结、翻译和转写。

## 用途与使用方式

这是一个 Agent skill（Claude Code / Codex 通用格式），入口是 `SKILL.md`：
agent 按其中的 `description` 判断何时触发，按正文流程执行。脚本、参数和数据口径以 `SKILL.md` 为准。
人工使用时直接阅读 `SKILL.md`；带脚本的按其中给出的命令运行。

## 目录

- `SKILL.md`
- `agents/`
- `scripts/`
