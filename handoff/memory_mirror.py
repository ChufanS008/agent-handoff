#!/usr/bin/env python3
"""One-way mirror of an agent's native memory into the shared layer, so other agents can read it.

Claude Code keeps memory as one Markdown file per fact with a `type:` field in the frontmatter.
This copies the types listed in `mirror_types` from every dir in `memory_dirs` to
<root>/agents/<mirror_agent>/memory/, redacts obvious secrets, writes an index, and deletes mirror
files whose source is gone. If `focus_file` is set (for example current-focus.md), it is also copied
to <root>/agents/_shared/focus.md so every agent starts from the same priorities.

The mirror directory belongs to this script. Nobody edits it by hand.

  python3 memory_mirror.py            # uses $AGENT_HANDOFF_CONFIG
"""
import os, re, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent_handoff import C, ROOT, READ_ONLY  # noqa: E402

AGENT = C.get('mirror_agent', 'Claude')
DST = f'{ROOT}/agents/{AGENT}/memory'
SHARED_FOCUS = f'{ROOT}/agents/_shared/focus.md'
FOCUS_FILE = C.get('focus_file', '')
KEEP_TYPES = set(C.get('mirror_types', ['user', 'feedback', 'reference', 'project']))
SECRET = [
    (re.compile(r'(discord(?:app)?\.com/api/webhooks/\d+/)[\w-]{20,}'), r'\1***'),
    (re.compile(r'(hooks\.slack\.com/services/)[\w/]{20,}'), r'\1***'),
    (re.compile(r'(api_?key=)[^&\s`"]+', re.I), r'\1***'),
    (re.compile(r'\b(sk-|ghp_|gho_|xox[bp]-)[A-Za-z0-9_-]{16,}'), r'\1***'),
]


def redact(text):
    for pat, rep in SECRET:
        text = pat.sub(rep, text)
    return text


def mtype(text):
    m = re.search(r'^\s*type:\s*(\w+)', text, re.M)
    return m.group(1) if m else None


def write_if_changed(path, head, body):
    """The first line carries a date, so compare from line two and keep mtime when nothing changed."""
    new = head + body
    if os.path.exists(path):
        old = open(path, encoding='utf-8').read()
        if old.split('\n', 1)[1:] == new.split('\n', 1)[1:]:
            return False
    open(path, 'w', encoding='utf-8').write(new)
    return True


def main():
    if os.path.exists(READ_ONLY):
        return
    os.makedirs(DST, exist_ok=True)
    wanted, index_parts, focus_text, seen = {}, [], None, set()
    dirs = [d for d in C['memory_dirs'] if os.path.isdir(d)]
    for d in dirs:
        real = os.path.realpath(d)
        if real in seen:
            continue
        seen.add(real)
        tag = os.path.basename(os.path.dirname(real)) if len(dirs) > 1 else ''
        for f in sorted(os.listdir(d)):
            if not f.endswith('.md'):
                continue
            text = open(os.path.join(d, f), encoding='utf-8').read()
            if f == 'MEMORY.md':
                index_parts.append(redact(text).strip())
                continue
            if mtype(text) in KEEP_TYPES or f == FOCUS_FILE:
                name = f'{tag}-{f}' if tag else f
                wanted[name] = redact(text)
                if f == FOCUS_FILE and focus_text is None:
                    focus_text = wanted[name]
    today = f'{datetime.now():%Y-%m-%d}'
    head = f'<!-- mirrored by memory_mirror.py on {today}, do not edit -->\n'
    for name, text in wanted.items():
        write_if_changed(os.path.join(DST, name), head, text)
    removed = 0
    for f in os.listdir(DST):
        if f.endswith('.md') and f not in wanted and f != '_index.md':
            os.remove(os.path.join(DST, f))
            removed += 1
    open(os.path.join(DST, '_index.md'), 'w', encoding='utf-8').write(
        f'# {AGENT} memory (read-only mirror)\n\nRefreshed by memory_mirror.py.\n\n' + '\n\n'.join(index_parts) + '\n')
    if focus_text is not None:
        os.makedirs(os.path.dirname(SHARED_FOCUS), exist_ok=True)
        write_if_changed(SHARED_FOCUS, f'<!-- copied from {AGENT} memory {FOCUS_FILE} on {today}, do not edit -->\n', focus_text)
    print(f'mirrored {len(wanted)} files, removed {removed}')


if __name__ == '__main__':
    main()
