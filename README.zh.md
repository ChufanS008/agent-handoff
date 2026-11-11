# agent-handoff

给同时用好几个 AI agent（Claude Code、Codex，以及任何能跑命令行的 agent）干活的人用的共享记忆和接手工具。

1. **进展索引**：每次会话结束，Stop hook 从对话记录里抽出你说过的每句话、最后的结论和改过的文件。换一个 agent 接手时跑 `recent <关键词>` 找到那次会话，再 `show <ID>` 看摘要，不用你重新交代。
2. **三层记忆**：各 agent 自己的原生记忆，大家共读、各写各的共享层，加一个只有一个 agent 能写入的正式知识库。
3. **让库不写乱的规矩**：每次写入署名，回流卡标明确定程度，授权分档表，会过期的事实就地标失效不删除。

只依赖 Python 3.9，不调模型。

安装和用法见 [README.md](README.md)，设计取舍见 [docs/design.md](docs/design.md)。
