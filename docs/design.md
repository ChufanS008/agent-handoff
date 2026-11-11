# Why it is built this way

## The problem

One person, four agents. Claude Code in the terminal, Codex in another window, a hosted agent that can only read and write documents, a bot on a server. Each one is good at a slice of the work, and each one forgets everything between sessions.

The first version gave them all write access to one knowledge base. Within two weeks it had three spellings of the same metric, two contradicting answers to "who owns this account", and a dozen files with no author. Nobody could tell which statement was current. Every agent wrote in its own style, and each new agent copied whatever it read first.

The second failure was handoff. "Continue what Codex did yesterday" meant either pasting the context again or letting the agent read whole transcripts and folders, which is slow and still misses the one sentence that mattered.

## Decisions

**One promoter.** Every agent may write its own folder. Only one agent, on a nightly schedule, moves things into the formal knowledge base. It reads return cards, checks the certainty field, promotes what the human decided, and queues the rest. Drift stops because there is one editor, and the others become sources instead of authors.

**Return cards with a certainty field.** A card says what was concluded and how sure: decided by the human, leaning, or the agent's own inference. Inference without evidence does not get promoted. This keeps an agent's guess from becoming a fact because it was written down confidently.

**Handoff by index.** At the end of every session a Stop hook pulls three things out of the transcript with no model call: every message the human sent, the last conclusion, and the files written. That is almost always enough to continue. `recent <keyword>` finds the session in under a second, `show <id>` prints the summary. Agents without a transcript log a line through the CLI or write a return card.

**Mechanical extraction only.** The index never summarizes with a model. The human's own words are kept verbatim, because a paraphrase is where intent gets lost. It also keeps the hook at a few milliseconds, since transcripts are read from a stored byte offset.

**Expired, not deleted.** Facts about people, prices, ownership and accounts flip. The old text stays, marked expired with a date and what replaced it, and the current answer moves to the top of the file. Index lines never carry the fact itself. An index that says "account X belongs to team Y" will be read long after it stops being true.

**Corrections written in the same session.** A correction that lives only in the conversation comes back. In the setup this came from, corrections written to memory in the session did not recur, and corrections left as "noted, will do next time" came back nearly every time. So the rule is to write it down before the session ends, and to escalate a repeated correction into a hook that enforces it.

**Authorization tiers per tool.** Read, low-risk write, high-risk. Each row says what is allowed, what always needs a yes, and what evidence would earn an upgrade. Agents propose upgrades. They never grant themselves one.

## What is left out

Sync to a team chat or document tool, so a hosted agent can read the board, is a few lines with that tool's CLI. It is left out because every team uses a different one. Add it after `save()` in `agent_handoff.py`.
