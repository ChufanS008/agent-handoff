# agent-handoff

Shared memory and handoff for people who run several coding agents at once (Claude Code, Codex, and anything that can call a CLI).

It gives you three things.

1. **A progress index.** A Stop hook records every session: what you asked, the last conclusion, the files written. Any agent runs `recent <keyword>` and `show <id>` to pick up where another one stopped, without you repeating yourself.
2. **A three-layer memory layout.** Native memory per agent, a shared layer where each agent writes only its own folder, and a formal knowledge base that exactly one agent promotes into.
3. **Conventions that keep it clean.** Signatures on every write, return cards with a certainty field, an authorization table, and rules for facts that expire.

No dependencies beyond Python 3.9. No model calls.

```
$ agent_handoff.py recent pricing
11-10 09:12  Claude  aaaaaaaa  [Website]  asked: Also keep the monthly toggle  ->  last: Annual is now the default and the monthly toggle stays…
11-09 17:40  Codex   bbbbbbbb  [Website]  asked: Make the pricing table responsive  ->  last: Table collapses to cards below 640px…

$ agent_handoff.py show aaaaaaaa
# Claude session aaaaaaaa-…  [Website]
## What the human said, in order
1. Make the pricing page show annual prices by default
2. Also keep the monthly toggle
## Last conclusion
Annual is now the default and the monthly toggle stays. Notes in ~/code/website/docs/pricing.md
## Files written or produced
- ~/code/website/src/pricing.tsx
- ~/code/website/docs/pricing.md
```

## Install

```bash
git clone https://github.com/ChufanS008/agent-handoff && cd agent-handoff
./install.sh
```

The installer copies the scripts to `~/.local/share/agent-handoff`, writes `~/.config/agent-handoff/config.json` if missing, and creates the shared layout at `~/agent-kb`. It prints the hook snippets instead of editing your settings.

Then:

1. Merge `hooks/claude-settings.json` into `~/.claude/settings.json`.
2. Merge `hooks/codex-hooks.json` into `~/.codex/hooks.json`.
3. Add `templates/agent/CLAUDE.md.snippet` to `~/.claude/CLAUDE.md` and `templates/agent/AGENTS.md.snippet` to `~/.codex/AGENTS.md`, so each agent knows to look before asking.
4. For agents without a local transcript, use `templates/agent/other-agent-onboarding.md`.

## Commands

| Command | What it does |
|---|---|
| `init` | create `agents/_shared`, per-agent `memory/` and `return/`, and `kb/` |
| `recent [kw] [--days N] [--agent A]` | one line per session, newest first, all keywords must match |
| `show <id prefix or keyword>` | every human message in order, last conclusion, files |
| `log --agent A --project P --status S [--files ...] [--next N]` | manual row for an agent with no transcript |
| `scan` | incremental pass over recent transcripts and return cards |
| `hook-claude`, `hook-codex` | Stop hook entry, returns immediately and indexes in the background |

`memory_mirror.py` copies Claude's native memory into the shared layer so other agents can read it. `codex_memory_extract.py` lists lessons from Codex's private memory and writes the ones you keep into the shared layer.

## Configuration

`~/.config/agent-handoff/config.json`, or the path in `AGENT_HANDOFF_CONFIG`. See `config.example.json`. The useful keys:

| Key | Meaning |
|---|---|
| `root` | where the shared layout lives. A synced folder (iCloud, Dropbox, an Obsidian vault) works |
| `projects` | name, path prefixes and keywords, used to label sessions |
| `card_agents` | agents whose return cards should appear in the index |
| `memory_dirs`, `mirror_cmd` | run the mirror after a session when memory changed |
| `utc_offset_hours` | display timezone |

On a second machine that syncs the same folder, `touch <root>/.read-only` so it reads the index but never writes it.

## Layout

```
agents/_shared/   README, conventions, authorization, focus, progress board (promoter only)
agents/<agent>/   memory/ and return/, written only by that agent
kb/               formal knowledge base, written only by the promoter
```

Why it is shaped like this: [docs/design.md](docs/design.md).

## Tests

```bash
python3 -m unittest discover tests
```

## License

MIT
