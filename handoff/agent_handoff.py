#!/usr/bin/env python3
"""Shared progress index for several coding agents (Claude Code, Codex, and anything that can run a CLI).

Every agent session that ends adds or updates one row. The next agent runs `recent <keyword>` to find
earlier work, then `show <id>` to read what the human asked, what the last turn concluded, and which
files were written. Nothing here calls a model. Fields are pulled mechanically from transcripts, which
are read incrementally by byte offset, so a Stop hook stays cheap even on large sessions.

Commands
  init                                   create the shared layout under $AGENT_HANDOFF_ROOT
  recent [keyword] [--days N] [--agent X] one line per session, newest first
  show <id prefix | keyword>             handoff summary of one session
  log --agent A --project P --status S [--files F ...] [--next N] [--id ID]
                                         manual entry for agents without a transcript
  scan                                   incremental pass over recent transcripts and return cards
  hook-claude / hook-codex               Stop hook entry: reads the hook payload on stdin, forks, returns at once

Configuration lives in $AGENT_HANDOFF_CONFIG (default ~/.config/agent-handoff/config.json).
See config.example.json. Every key is optional.
"""
import argparse, fcntl, glob, json, os, re, subprocess, sys, time
from datetime import datetime, timezone, timedelta

HOME = os.path.expanduser('~')
CONFIG_PATH = os.path.expanduser(os.environ.get('AGENT_HANDOFF_CONFIG', '~/.config/agent-handoff/config.json'))

DEFAULTS = {
    'root': '~/agent-kb',                                   # shared knowledge root
    'human': 'the human',                                   # how summaries refer to the person giving instructions
    'utc_offset_hours': 0,                                  # display timezone
    'claude_glob': '~/.claude/projects/*/*.jsonl',
    'codex_glob': '~/.codex/sessions/*/*/*/*.jsonl',
    'card_agents': [],                                      # agents whose return cards count as sessions, e.g. ["Gemini"]
    'projects': [],                                         # [{"name": "Site", "paths": ["~/code/site"], "keywords": ["landing"]}]
    'board_days': 7,
    'keep_days': 30,
    'mirror_cmd': '',                                       # optional command run after a hook when memory changed
    'memory_dirs': [],                                      # watched by mirror_cmd
}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.load(open(CONFIG_PATH, encoding='utf-8')))
    except FileNotFoundError:
        pass
    for k in ('root', 'claude_glob', 'codex_glob'):
        cfg[k] = os.path.expanduser(os.environ.get('AGENT_HANDOFF_' + k.upper(), cfg[k]))
    cfg['memory_dirs'] = [os.path.expanduser(p) for p in cfg['memory_dirs']]
    for p in cfg['projects']:
        p['paths'] = [os.path.expanduser(x).rstrip('/') for x in p.get('paths', [])]
    return cfg


C = load_config()
ROOT = C['root']
DIR = f'{ROOT}/agents/_shared/progress'
INDEX = f'{DIR}/index.json'
BOARD = f'{ROOT}/agents/_shared/progress.md'
LOCK = f'{DIR}/.lock'
READ_ONLY = f'{ROOT}/.read-only'          # touch this on a second machine that syncs the same folder
MIRROR_STAMP = f'{DIR}/.memory_mirrored'
TZ = timezone(timedelta(hours=C['utc_offset_hours']))
SKIP_PREFIXES = ('<command-', '<local-command', '<system-reminder', '<scheduled-task', '# AGENTS.md',
                 '<environment_context', '<user_instructions', '<task-notification', 'Caveat:',
                 'The following is the Codex agent history',
                 'This session is being continued from a previous conversation')
HEADLESS_CLAUDE_EP = {'sdk-cli', 'sdk-py', 'sdk-ts', 'mcp'}
PATH_RE = re.compile(r'((?:/|~/)[^\s`)\]\'"<>|]+\.[A-Za-z0-9]{1,5})')
TAG_BLOCK = re.compile(r'^<([a-z_-]+)[^>]*>.*?</\1>\s*', re.S)
PATCH_RE = re.compile(r'\*\*\* (?:Add|Update) File: ([^\s"\\]+)')


def now():
    return datetime.now(TZ)


def fmt_ts(ts):
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone(TZ).strftime('%m-%d %H:%M')
    except Exception:
        return (ts or '')[:16]


def clip(s, n):
    s = re.sub(r'\s+', ' ', s or '').strip()
    return s if len(s) <= n else s[:n - 1] + '…'


def short_path(p):
    return p.replace(HOME, '~', 1) if p.startswith(HOME) else p


# ---------- project inference ----------
def infer_project(paths, texts):
    prefixes = sorted(((pre, p['name']) for p in C['projects'] for pre in p['paths']), key=lambda x: -len(x[0]))
    for path in paths:
        for pre, name in prefixes:
            if path and path.startswith(pre):
                return name
    score = {}
    for t in texts:  # one vote per message, and at least two messages must agree
        for p in C['projects']:
            if any(k.lower() in t.lower() for k in p.get('keywords', [])):
                score[p['name']] = score.get(p['name'], 0) + 1
                break
    if score:
        name, n = max(score.items(), key=lambda x: x[1])
        if n >= min(2, len(texts)):
            return name
    return ''


# ---------- index ----------
def load():
    try:
        return json.load(open(INDEX, encoding='utf-8'))
    except Exception:
        return {'sessions': {}}


def save(idx):
    if os.path.exists(READ_ONLY):
        return
    tmp = INDEX + '.tmp'
    json.dump(idx, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False)
    os.replace(tmp, INDEX)
    render(idx)


class Locked:
    def __enter__(self):
        os.makedirs(DIR, exist_ok=True)
        self.f = open(LOCK, 'w')
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def render(idx):
    cutoff = time.time() - C['board_days'] * 86400
    rows = [s for s in idx['sessions'].values()
            if s.get('updated_epoch', 0) >= cutoff and s.get('asks') and not s.get('hidden')]
    rows.sort(key=lambda s: -s['updated_epoch'])
    lines = ['---', 'title: Progress', 'generated_by: agent_handoff.py (do not edit by hand)',
             f'updated: {now():%Y-%m-%d %H:%M}', '---', '',
             f"# Progress, last {C['board_days']} days, all agents", '',
             'One row per session, written when the session ends. To pick up earlier work run '
             '`agent_handoff.py recent <keyword>`, then `show <ID>`.', '',
             '| Time | Agent | Project | Last ask | Last state | Files | ID |', '|---|---|---|---|---|---|---|']
    for s in rows:
        files = ', '.join(f'`{short_path(f)}`' for f in s.get('files', [])[-3:])
        lines.append('| {} | {} | {} | {} | {} | {} | `{}` |'.format(
            fmt_ts(s['updated']), s['agent'], s.get('project') or '-', clip(s['asks'][-1], 60).replace('|', '/'),
            clip(s.get('last') or '', 90).replace('|', '/'), files or '-', s['id'][:8]))
    open(BOARD, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')


# ---------- transcript parsing ----------
def user_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(c.get('text', '') for c in content
                         if isinstance(c, dict) and c.get('type') in ('text', 'input_text'))
    return ''


def keep_ask(t):
    t = (t or '').strip()
    return bool(t) and not t.startswith(SKIP_PREFIXES)


def norm_ask(t):
    t = (t or '').strip()
    while True:  # drop context blocks a client prepends, keep the human's own words
        m = TAG_BLOCK.match(t)
        if not m:
            break
        t = t[m.end():].strip()
    return t


def add_ask(s, t, ts):
    s.setdefault('asks', []).append(clip(t, 400))
    s['n_asks'] = s.get('n_asks', 0) + 1
    s['started'] = s.get('started') or ts


def add_file(s, fp):
    fl = s.setdefault('files', [])
    if fp in fl:
        fl.remove(fp)
    fl.append(fp)
    del fl[:-15]


def read_new_lines(path, s):
    with open(path, 'rb') as f:
        f.seek(s.get('offset', 0))
        for raw in f:
            if not raw.endswith(b'\n'):
                break  # half-written line, pick it up next time
            s['offset'] = s.get('offset', 0) + len(raw)
            yield raw


def parse_claude(path, s):
    for raw in read_new_lines(path, s):
        try:
            d = json.loads(raw)
        except Exception:
            continue
        if d.get('isSidechain'):
            continue
        s.setdefault('cwd', d.get('cwd') or '')
        if d.get('entrypoint'):
            s['entrypoint'] = d['entrypoint']
        ts = d.get('timestamp')
        if d.get('type') == 'user' and not d.get('isMeta') and not d.get('toolUseResult'):
            t = norm_ask(user_text((d.get('message') or {}).get('content')))
            if s.get('n_asks', 0) == 0 and t.startswith('<scheduled-task'):
                s['source'] = 'scheduled'
            if keep_ask(t):
                add_ask(s, t, ts)
        elif d.get('type') == 'assistant':
            for c in (d.get('message') or {}).get('content') or []:
                if c.get('type') == 'text' and c.get('text', '').strip():
                    s['last'] = clip(c['text'], 600)
                    s['last_full'] = c['text']
                elif c.get('type') == 'tool_use' and c.get('name') in ('Write', 'Edit', 'MultiEdit', 'NotebookEdit'):
                    fp = (c.get('input') or {}).get('file_path')
                    if fp:
                        add_file(s, fp)
        if ts:
            s['updated'] = ts


def parse_codex(path, s):
    for raw in read_new_lines(path, s):
        # most lines are tool output and token counts, filter on bytes before parsing JSON
        if not (b'"session_meta"' in raw[:200] or b'UserMessage' in raw or b'task_complete' in raw
                or b'*** Add File' in raw or b'*** Update File' in raw):
            continue
        try:
            d = json.loads(raw)
        except Exception:
            continue
        p = d.get('payload') or {}
        ts = d.get('timestamp')
        if d.get('type') == 'session_meta':
            s['cwd'] = p.get('cwd', '')
            if p.get('source') == 'exec':
                s['source'] = 'codex exec'
        elif p.get('type') == 'item_completed' and (p.get('item') or {}).get('type') == 'UserMessage':
            t = norm_ask(user_text(p['item'].get('content')))
            if keep_ask(t):
                add_ask(s, t, ts)
        elif p.get('type') == 'task_complete' and p.get('last_agent_message'):
            s['last'] = clip(p['last_agent_message'], 600)
            for fp in PATH_RE.findall(p['last_agent_message']):
                add_file(s, fp)
        else:
            for fp in PATCH_RE.findall(raw.decode('utf-8', 'ignore')):
                add_file(s, fp)
        if ts:
            s['updated'] = ts


def finish(s):
    s['asks'] = s.get('asks', [])[-30:]
    s['updated_epoch'] = (datetime.fromisoformat(s['updated'].replace('Z', '+00:00')).timestamp()
                          if s.get('updated') else time.time())
    s['project'] = s.get('project_manual') or infer_project(s.get('files', [])[::-1] + [s.get('cwd', '')],
                                                            s.get('asks', []))


def ingest(idx, agent, path, sid=None):
    sid = sid or os.path.basename(path).rsplit('.', 1)[0][-36:]
    key = f'{agent}:{sid}'
    s = idx['sessions'].get(key) or {'id': sid, 'agent': agent, 'path': path}
    size = os.path.getsize(path)
    if s.get('offset', 0) > size:
        s['offset'] = 0
    if s.get('offset', 0) == size:
        return
    (parse_claude if agent == 'Claude' else parse_codex)(path, s)
    if agent == 'Claude':  # paths named in the final reply count as outputs too
        for fp in PATH_RE.findall(s.pop('last_full', '') or ''):
            add_file(s, fp)
    headless = agent == 'Claude' and (not s.get('entrypoint') or s['entrypoint'] in HEADLESS_CLAUDE_EP)
    s['hidden'] = headless or s.get('source') in ('scheduled', 'codex exec') or not s.get('asks')
    finish(s)
    idx['sessions'][key] = s


def ingest_card(idx, agent, path):
    key = f'{agent}:card:{os.path.basename(path)}'
    mt = os.path.getmtime(path)
    if idx['sessions'].get(key, {}).get('mtime') == mt:
        return
    text = open(path, encoding='utf-8', errors='ignore').read()
    title = re.search(r'^title:\s*(.+)$', text, re.M)
    body = re.sub(r'^---.*?---\s*', '', text, flags=re.S)
    heads = re.findall(r'^#+\s*(.+)$', body, re.M)
    s = {'id': os.path.basename(path)[:-3], 'agent': agent, 'path': path, 'mtime': mt,
         'asks': [clip(title.group(1) if title else (heads[0] if heads else os.path.basename(path)), 200)],
         'last': clip(re.sub(r'^#.*$', '', body, flags=re.M), 300), 'files': [path],
         'updated': datetime.fromtimestamp(mt, timezone.utc).isoformat()}
    finish(s)
    idx['sessions'][key] = s


def scan(idx, days=3):
    cutoff = time.time() - days * 86400
    for agent, pattern in (('Claude', C['claude_glob']), ('Codex', C['codex_glob'])):
        for p in glob.glob(pattern):
            try:
                if os.path.getmtime(p) >= cutoff:
                    ingest(idx, agent, p)
            except OSError:
                pass
    for agent in C['card_agents']:
        for p in glob.glob(f'{ROOT}/agents/{agent}/return/*.md'):
            if os.path.getmtime(p) >= cutoff:
                ingest_card(idx, agent, p)
    old = time.time() - C['keep_days'] * 86400
    idx['sessions'] = {k: v for k, v in idx['sessions'].items() if v.get('updated_epoch', time.time()) >= old}


# ---------- queries ----------
def visible(idx, days, agent=None, kw=None):
    cutoff = time.time() - days * 86400
    out = []
    for s in idx['sessions'].values():
        if s.get('hidden') or s.get('updated_epoch', 0) < cutoff:
            continue
        if agent and s['agent'].lower() != agent.lower():
            continue
        if kw:
            blob = ' '.join([s.get('project', ''), s.get('last', ''), ' '.join(s.get('asks', [])),
                             ' '.join(s.get('files', []))]).lower()
            if not all(k.lower() in blob for k in kw.split()):
                continue
        out.append(s)
    return sorted(out, key=lambda s: -s['updated_epoch'])


def refreshed(days):
    with Locked():
        idx = load()
        scan(idx, days)
        save(idx)
    return idx


def cmd_recent(a):
    idx = refreshed(max(a.days, 1))
    rows = visible(idx, a.days, a.agent, a.keyword)
    if not rows:
        print(f'(no matching sessions in the last {a.days} days)')
    for s in rows[:a.limit]:
        print(f"{fmt_ts(s['updated'])}  {s['agent']:<7} {s['id'][:8]}  [{s.get('project') or '-'}]  "
              f"asked: {clip(s['asks'][-1], 50)}  ->  last: {clip(s.get('last', ''), 70)}")


def cmd_show(a):
    idx = refreshed(C['keep_days'] if a.all else 7)
    cands = [s for s in idx['sessions'].values() if s['id'].startswith(a.target)] or visible(idx, C['keep_days'], None, a.target)
    if not cands:
        print('not found:', a.target)
        return 1
    s = cands[0]
    print(f"# {s['agent']} session {s['id']}  [{s.get('project') or '-'}]")
    print(f"time: {fmt_ts(s.get('started') or s['updated'])} -> {fmt_ts(s['updated'])}    cwd: {short_path(s.get('cwd', ''))}")
    print(f"transcript: {short_path(s['path'])}\n")
    print(f"## What {C['human']} said, in order")
    for i, t in enumerate(s.get('asks', []), 1):
        print(f'{i}. {t}')
    print('\n## Last conclusion\n' + (s.get('last') or '(none)'))
    if s.get('files'):
        print('\n## Files written or produced')
        for f in s['files']:
            print('- ' + short_path(f))
    if len(cands) > 1:
        print('\nother matches: ' + '  '.join(f"{c['agent']}:{c['id'][:8]}" for c in cands[1:6]))


def cmd_log(a):
    sid = a.id or f"{a.agent}-{now():%Y%m%d-%H%M%S}"
    with Locked():
        idx = load()
        key = f'{a.agent}:{sid}'
        s = idx['sessions'].get(key) or {'id': sid, 'agent': a.agent, 'path': '(manual entry)', 'asks': []}
        s['asks'].append(clip(a.status, 400))
        s['last'] = clip(a.status + (f'. Next: {a.next}' if a.next else ''), 600)
        for f in a.files or []:
            add_file(s, f)
        s['project_manual'] = a.project
        s['updated'] = datetime.now(timezone.utc).isoformat()
        finish(s)
        idx['sessions'][key] = s
        save(idx)
    print('logged', key)


def maybe_mirror():
    """Run the configured mirror command once when any watched memory file changed since the last run."""
    if not C['mirror_cmd'] or not C['memory_dirs']:
        return
    try:
        last = os.path.getmtime(MIRROR_STAMP)
    except OSError:
        last = 0
    if not any(os.path.getmtime(p) > last for d in C['memory_dirs'] for p in glob.glob(f'{d}/*.md')):
        return
    open(MIRROR_STAMP, 'w').close()
    subprocess.run(C['mirror_cmd'], shell=True, capture_output=True, timeout=60)


def cmd_hook(agent):
    if os.path.exists(READ_ONLY):
        return
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    if not os.environ.get('AGENT_HANDOFF_FOREGROUND') and os.fork():
        os._exit(0)  # parent returns at once so the hook never slows a reply
    if not os.environ.get('AGENT_HANDOFF_FOREGROUND'):
        os.setsid()
    path, sid = payload.get('transcript_path'), payload.get('session_id')
    if agent == 'Codex' and (not path or not os.path.exists(path)) and sid:
        hits = glob.glob(C['codex_glob'].replace('*.jsonl', f'*{sid}.jsonl'))
        path = hits[0] if hits else None
    if path and os.path.exists(path):
        with Locked():
            idx = load()
            ingest(idx, agent, path, sid)
            save(idx)
        maybe_mirror()
    if not os.environ.get('AGENT_HANDOFF_FOREGROUND'):
        os._exit(0)


def cmd_init(_):
    here = os.path.dirname(os.path.abspath(__file__))
    tpl = os.path.join(os.path.dirname(here), 'templates')
    made = []
    for agent in ['Claude', 'Codex'] + list(C['card_agents']):
        for sub in ('memory', 'return'):
            d = f'{ROOT}/agents/{agent}/{sub}'
            if not os.path.isdir(d):
                os.makedirs(d)
                made.append(d)
    os.makedirs(DIR, exist_ok=True)
    os.makedirs(f'{ROOT}/kb', exist_ok=True)
    for name in os.listdir(f'{tpl}/shared'):
        dst = f'{ROOT}/agents/_shared/{name}'
        if not os.path.exists(dst):
            open(dst, 'w', encoding='utf-8').write(open(f'{tpl}/shared/{name}', encoding='utf-8').read())
            made.append(dst)
    for f in made:
        print('created', short_path(f))
    print('layout ready at', short_path(ROOT))


def main(argv=None):
    ap = argparse.ArgumentParser(description='Shared progress index for coding agents')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('init')
    r = sub.add_parser('recent'); r.add_argument('keyword', nargs='?'); r.add_argument('--days', type=int, default=3)
    r.add_argument('--agent'); r.add_argument('--limit', type=int, default=15)
    s = sub.add_parser('show'); s.add_argument('target'); s.add_argument('--all', action='store_true')
    l = sub.add_parser('log'); l.add_argument('--agent', required=True); l.add_argument('--project', required=True)
    l.add_argument('--status', required=True); l.add_argument('--files', nargs='*'); l.add_argument('--next')
    l.add_argument('--id')
    sub.add_parser('scan'); sub.add_parser('hook-claude'); sub.add_parser('hook-codex')
    a = ap.parse_args(argv)
    if a.cmd == 'init':
        return cmd_init(a)
    if a.cmd == 'recent':
        return cmd_recent(a)
    if a.cmd == 'show':
        return cmd_show(a)
    if a.cmd == 'log':
        return cmd_log(a)
    if a.cmd == 'scan':
        refreshed(3)
        return
    return cmd_hook('Claude' if a.cmd == 'hook-claude' else 'Codex')


if __name__ == '__main__':
    sys.exit(main() or 0)
