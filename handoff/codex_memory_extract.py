#!/usr/bin/env python3
"""Pull Codex's private lessons into the shared layer.

Codex writes its own memory to ~/.codex/memories/MEMORY.md, grouped by task, with sections such as
"User preferences" and "Failures and how to do differently". It never writes the shared layer itself,
so corrections it learned stay invisible to other agents. This script lists entries that have not
been synced yet, and writes the ones you (or a nightly agent run) decide to keep as one shared memory
file each under <root>/agents/Codex/memory/. Dedup is by content hash.

  codex_memory_extract.py pending           JSON list of unsynced entries
  codex_memory_extract.py write plan.json   write files from a plan, a list of
                                            {hash, filename, project, fact, how_to_apply[, why, date]}
  codex_memory_extract.py mark <hash>...    record hashes as handled without writing a file
"""
import hashlib, json, os, re, sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent_handoff import C, ROOT, DIR  # noqa: E402

SRC = os.path.expanduser(C.get('codex_memory', '~/.codex/memories/MEMORY.md'))
DST = f'{ROOT}/agents/Codex/memory'
STATE = f'{DIR}/codex_synced.json'
SECTIONS = {'User preferences': 'preference', 'Failures and how to do differently': 'failure'}


def parse(path=SRC):
    groups, cur, sec = [], None, None
    for line in open(path, encoding='utf-8').read().splitlines():
        line = line.rstrip()
        if line.startswith('# Task Group: '):
            cur = {'group': line[14:].strip(), 'entries': []}
            groups.append(cur)
            sec = None
            continue
        if cur is None:
            continue
        if line.startswith('## '):
            sec = SECTIONS.get(line[3:].strip())
            continue
        if sec and line.startswith('- '):
            cur['entries'].append({'section': sec, 'text': line[2:].strip()})
        elif sec and line.strip() and cur['entries'] and not line.startswith('#'):
            cur['entries'][-1]['text'] += ' ' + line.strip()
    out = []
    for g in groups:
        for e in g['entries']:
            text = re.sub(r'\s+', ' ', e['text']).strip()
            h = hashlib.sha256(f"{g['group']}\n{e['section']}\n{text}".encode('utf-8')).hexdigest()
            out.append({'hash': h, 'group': g['group'], 'section': e['section'], 'text': text})
    return out


def load_state():
    return set(json.load(open(STATE, encoding='utf-8'))) if os.path.exists(STATE) else set()


def save_state(done):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(sorted(done), open(STATE, 'w', encoding='utf-8'), indent=1)


def cmd_pending():
    done = load_state()
    pend = [e for e in parse() if e['hash'] not in done]
    print(json.dumps(pend, ensure_ascii=False, indent=1))


def cmd_write(plan_path):
    plan = json.load(open(plan_path, encoding='utf-8'))
    entries = {e['hash']: e for e in parse()}
    done = load_state()
    os.makedirs(DST, exist_ok=True)
    today = f'{datetime.now():%Y-%m-%d}'
    written = 0
    for it in plan:
        h, e = it['hash'], entries.get(it['hash'])
        why = (e['text'] if e else it.get('why', '')).strip()
        if not why or (h in done and not it.get('force')):
            continue
        fn = it['filename'] if it['filename'].endswith('.md') else it['filename'] + '.md'
        path = os.path.join(DST, fn)
        if os.path.exists(path) and f'hash: {h[:16]}' not in open(path, encoding='utf-8').read():
            print('skip, filename taken:', fn)
            continue
        open(path, 'w', encoding='utf-8').write(
            f"---\nagent: Codex\ntype: feedback\nproject: {it['project']}\ndate: {it.get('date', today)}\n"
            f"source: codex memory / {e['group'] if e else ''}\nhash: {h[:16]}\n---\n\n{it['fact'].strip()}\n\n"
            f"**Why:** {why}\n**How to apply:** {it['how_to_apply'].strip()}\n")
        done.add(h)
        written += 1
    save_state(done)
    print(f'written {written}', datetime.now(timezone.utc).isoformat())


def cmd_mark(hashes):
    save_state(load_state() | set(hashes))
    print(f'marked {len(hashes)}')


if __name__ == '__main__':
    a = sys.argv[1:]
    if not a or a[0] == 'pending':
        cmd_pending()
    elif a[0] == 'write' and len(a) == 2:
        cmd_write(a[1])
    elif a[0] == 'mark' and len(a) > 1:
        cmd_mark(a[1:])
    else:
        print(__doc__)
        sys.exit(1)
