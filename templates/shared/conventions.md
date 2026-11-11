# Conventions

## Signatures

Every write to a shared file carries who wrote it. Use a fixed identity per platform, and add a role when one platform hosts several agents.

| Identity | Writes to |
|---|---|
| `Claude session` | own memory, own return cards |
| `Claude nightly` | `kb/`, `_shared/` (promoter runs only) |
| `Codex` | `agents/Codex/` |
| `<Agent> / <role>` | `agents/<Agent>/`, with `role:` in the frontmatter |

New agents join only with the human's approval. Add a row here first, then create `agents/<Agent>/memory/` and `return/`.

## Shared memory entry

One fact per file in `agents/<agent>/memory/`.

```
---
agent: <identity>
type: feedback | user | project | reference
project: <project name or "general">
date: YYYY-MM-DD
---

<the fact or rule, one sentence>

**Why:** the reason, usually the human's own words or an incident
**How to apply:** when it matters and what to do
```

1. Corrected by the human? Write a feedback entry in the same session. "I'll remember next time" does not survive a new session.
2. Read `conventions.md` and other agents' memory first. Do not duplicate. If you disagree with an existing entry, say "conflicts with <path>" in yours.
3. Out of date? Mark the top "expired YYYY-MM-DD, replaced by X" and keep the file.

## Return card

Write one in `agents/<agent>/return/YYYY-MM-DD-HHMM-topic.md` before a session ends whenever it produced a business conclusion, a decision, a changed definition, a status change, a contradiction with `kb/`, or a deliverable.

```
---
source: <identity>
date: YYYY-MM-DD
status: pending
---

# <topic>

## Discussed
Two or three sentences.

## Conclusions
| Conclusion | Certainty | Suggested KB location |
|---|---|---|
| one sentence with date and scope | decided by the human / leaning / my inference | path, or "unsure" |

## Contradicts
Which KB statement this overturns, with path and quote. Otherwise "none".

## Open items
| Item | Owner agent | Next step | Due |
|---|---|---|---|

## Outputs
Files or links. Otherwise "none".
```

Open items need all four columns, or the promoter cannot track them.

## Facts that flip

Ownership, prices, people, accounts and definitions change. When one does, do not overwrite the old text. Mark it in place as "expired YYYY-MM-DD, replaced by X", put the current answer at the top of the file, and update any index line that points to it. An index line names a topic and where to look. It never carries the fact itself, because index lines are the part nobody re-checks.
