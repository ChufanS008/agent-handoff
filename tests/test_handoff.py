"""End-to-end test: synthetic Claude and Codex transcripts in, recent / show / log / board out.

  python3 -m unittest discover tests
"""
import json, os, subprocess, sys, tempfile, unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), 'handoff', 'agent_handoff.py')


class HandoffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        ts = datetime.now(timezone.utc).isoformat()
        code = os.path.join(self.tmp, 'code')
        for name, sub in (('claude-session.jsonl', 'claude/proj'), ('codex-session.jsonl', 'codex/2026/01/01')):
            d = os.path.join(self.tmp, sub)
            os.makedirs(d)
            text = open(os.path.join(HERE, 'fixtures', name)).read().replace('__TS__', ts).replace('~/code', code)
            sid = 'aaaaaaaa-1111-2222-3333-444444444444' if 'claude' in name else 'bbbbbbbb-1111-2222-3333-444444444444'
            open(os.path.join(d, sid + '.jsonl'), 'w').write(text)
        self.cfg = os.path.join(self.tmp, 'config.json')
        json.dump({'root': os.path.join(self.tmp, 'kb'),
                   'claude_glob': os.path.join(self.tmp, 'claude/*/*.jsonl'),
                   'codex_glob': os.path.join(self.tmp, 'codex/*/*/*/*.jsonl'),
                   'card_agents': ['Gemini'],
                   'projects': [{'name': 'Website', 'paths': [os.path.join(code, 'website')]},
                                {'name': 'Mobile app', 'paths': [os.path.join(code, 'app')]}]},
                  open(self.cfg, 'w'))

    def run_cli(self, *args, stdin=None):
        env = dict(os.environ, AGENT_HANDOFF_CONFIG=self.cfg, AGENT_HANDOFF_FOREGROUND='1')
        r = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=env, input=stdin)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_flow(self):
        self.assertIn('layout ready', self.run_cli('init'))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, 'kb/agents/_shared/conventions.md')))

        out = self.run_cli('recent')
        self.assertIn('[Website]', out)
        self.assertIn('[Mobile app]', out)
        self.assertNotIn('subagent chatter', out)

        show = self.run_cli('show', 'aaaaaaaa')
        self.assertIn('1. Make the pricing page show annual prices by default', show)
        self.assertIn('2. Also keep the monthly toggle', show)
        self.assertNotIn('ignore me', show)
        self.assertIn('website/src/pricing.tsx', show)
        self.assertIn('website/docs/pricing.md', show)

        codex = self.run_cli('show', 'bbbbbbbb')
        self.assertIn('Fix the TestFlight build number bump', codex)
        self.assertIn('app/scripts/bump.sh', codex)
        self.assertNotIn('bump.sh@@', codex)

        self.assertIn('logged', self.run_cli('log', '--agent', 'Gemini', '--project', 'Website',
                                             '--status', 'Hero copy drafted', '--next', 'review'))
        self.assertIn('Hero copy drafted', self.run_cli('recent', 'hero'))
        self.assertIn('no matching', self.run_cli('recent', 'nothing-like-this'))

        board = open(os.path.join(self.tmp, 'kb/agents/_shared/progress.md')).read()
        self.assertEqual(board.count('| Claude |') + board.count('| Codex |') + board.count('| Gemini |'), 3)

    def test_card_and_hook(self):
        self.run_cli('init')
        card = os.path.join(self.tmp, 'kb/agents/Gemini/return/2026-01-01-0900-launch.md')
        open(card, 'w').write('---\nsource: Gemini\nstatus: pending\n---\n\n# Launch checklist\n\nAll items done.\n')
        self.assertIn('Launch checklist', self.run_cli('recent', 'launch'))

        path = os.path.join(self.tmp, 'claude/proj/aaaaaaaa-1111-2222-3333-444444444444.jsonl')
        self.run_cli('hook-claude', stdin=json.dumps({'transcript_path': path, 'session_id': 'aaaaaaaa-1111-2222-3333-444444444444'}))
        idx = json.load(open(os.path.join(self.tmp, 'kb/agents/_shared/progress/index.json')))
        s = idx['sessions']['Claude:aaaaaaaa-1111-2222-3333-444444444444']
        self.assertEqual(s['offset'], os.path.getsize(path))
        with open(path, 'a') as f:  # appended turn is read incrementally
            f.write(json.dumps({'type': 'user', 'timestamp': datetime.now(timezone.utc).isoformat(),
                                'message': {'role': 'user', 'content': 'Ship it'}}) + '\n')
        self.assertIn('3. Ship it', self.run_cli('show', 'aaaaaaaa'))

    def test_read_only_machine_writes_nothing(self):
        self.run_cli('init')
        open(os.path.join(self.tmp, 'kb/.read-only'), 'w').close()
        self.run_cli('recent')
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'kb/agents/_shared/progress/index.json')))

    def test_memory_mirror(self):
        mem = os.path.join(self.tmp, 'mem')
        os.makedirs(mem)
        with open(os.path.join(mem, 'tone.md'), 'w') as f:
            f.write('---\nname: tone\ntype: feedback\n---\nShort replies. Token sk-abcdefghijklmnopqrstuv\n')
        with open(os.path.join(mem, 'scratch.md'), 'w') as f:
            f.write('---\ntype: scratch\n---\nnot mirrored\n')
        with open(os.path.join(mem, 'current-focus.md'), 'w') as f:
            f.write('---\ntype: project\n---\nShip pricing\n')
        cfg = json.load(open(self.cfg))
        cfg.update(memory_dirs=[mem], focus_file='current-focus.md')
        with open(self.cfg, 'w') as f:
            json.dump(cfg, f)
        env = dict(os.environ, AGENT_HANDOFF_CONFIG=self.cfg)
        mirror = os.path.join(os.path.dirname(SCRIPT), 'memory_mirror.py')
        subprocess.run([sys.executable, mirror], check=True, env=env, capture_output=True)
        dst = os.path.join(self.tmp, 'kb/agents/Claude/memory')
        self.assertEqual(sorted(os.listdir(dst)), ['_index.md', 'current-focus.md', 'tone.md'])
        self.assertIn('sk-***', open(os.path.join(dst, 'tone.md')).read())
        self.assertIn('Ship pricing', open(os.path.join(self.tmp, 'kb/agents/_shared/focus.md')).read())


if __name__ == '__main__':
    unittest.main()
