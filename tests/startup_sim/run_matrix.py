"""Run the OutdoorGPT start-up scenario matrix and write results + a report.

    python run_matrix.py [--seeds 3] [--jobs 8] [--only B,C3] [--fuzz 20] [--report results/x.md]

About three minutes for the full matrix with 8 jobs. Every run is a separate
process (harness.py), so runs cannot influence each other.

Sim timeline of a normal cold start (t = 0 when custom.sh starts, ~5 s after power):
  0-8 s    Python imports            8 s   GPIO set up, dial read -> initial prompt
  8-15     ASR model                 15-17 RAG index + embedding server
  17-19    Piper                     19-~21 wait for llama-server, TTS + LLM warm-up
  ~27      callbacks for dial/button registered, LEDs on, start message spoken
  ~31      listening (green)
"""
import argparse
import datetime
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))

U2 = {'turns': 2}
REC = {'turns': 2}          # recipe: the ingredients, then "yes"

LEGEND = {
    'AGENT_EXIT': 'the agent process ended; without a restart loop in the boot script the box is dead until power-cycled',
    'DIAL_MISMATCH': 'at the end the box runs another mode than the dial points at',
    'DIAL_EVENT_LOST': 'info: a dial edge came before its callback existed (harmless if the mode still matches)',
    'BUTTON_LOST_AT_BOOT': 'info: a button press came before its callback existed',
    'RANDOM_PROMPT': 'no dial position could be read, so a random mode was chosen',
    'STALE_SPEECH': 'an answer from the previous mode was spoken after a switch',
    'CONTEXT_POLLUTED': 'a request to the model had a broken history (wrong roles or another mode\'s answer)',
    'BOGUS_RECIPE_SCREEN': 'a non-recipe answer was drawn on the e-ink panel as the recipe',
    'BOGUS_RECIPE_STATE': 'recipe mode marked "delivered" (purple, deaf) without a confirmed ingredient list',
    'ECHO_HEARD': 'the microphone transcribed the agent\'s own voice',
    'ECHO_AS_INPUT': 'the agent\'s own voice was sent to the model as a question',
    'CONTEXT_OVERFLOW': 'the server refused a request that no longer fit the context window',
    'BUTTON_IGNORED_THINKING': 'a press during the thinking pause did not stop the answer',
    'BUTTON_IGNORED_SPEECH': 'a press while speaking did not stop the answer',
    'BUTTON_NO_RESTART': 'a press after a delivered recipe did not start a new one',
    'LONG_PRESS_NO_EFFECT': 'holding the button for 2 s or more did nothing',
    'GREEN_BUT_DEAF': 'the LED showed green (your turn) while the microphone was off for > 1.5 s',
    'OVERLAPPING_SPEECH': 'two sentences played at the same time',
    'THREAD_CRASH': 'an exception escaped a background thread',
    'SCENARIO_STEP_NOT_REACHED': 'a scenario step never got its moment (e.g. the agent died first)',
}


def S(id, title, **kw):
    kw.setdefault('start_dial', 'pos1')
    kw.setdefault('user', U2)
    return dict(id=id, title=title, **kw)


SCENARIOS = [
    # A: start position, nobody touches anything
    S('A1', 'start in position 1 (Outdoor Tips)'),
    S('A2', 'start in position 2 (Campfire Recipes), order a recipe', start_dial='pos2', user=REC),
    S('A3', 'start in position 3 (Survive the Night)', start_dial='pos3'),
    S('A4', 'dial between two positions at power-up', start_dial=None),
    S('A5', 'position 3, but its wire (GPIO17) is loose', start_dial='pos3', broken_pins=[17]),

    # B: dial turned while the box is starting
    S('B1', 'turn 1->3 during the imports (t=4s)', events=[{'t': 4, 'do': 'dial', 'pos': 'pos3'}]),
    S('B2', 'turn 1->3 while speech recognition loads (t=12s)', events=[{'t': 12, 'do': 'dial', 'pos': 'pos3'}]),
    S('B3', 'turn 1->3 during the warm-up (t=22s)', events=[{'t': 22, 'do': 'dial', 'pos': 'pos3'}]),
    S('B4', 'turn 1->3 just before ready (t=26.5s)', events=[{'t': 26.5, 'do': 'dial', 'pos': 'pos3'}]),
    S('B5', 'turn 1->3 during the start message', events=[{'at': 'start_msg', 'delay': 1.0, 'do': 'dial', 'pos': 'pos3'}]),
    S('B6', 'sweep 1->2->3 during start-up',
      events=[{'t': 12, 'do': 'dial', 'pos': 'pos2'}, {'t': 12.6, 'do': 'dial', 'pos': 'pos3'}]),
    S('B7', 'start in recipes (2), turn to 1 during start-up', start_dial='pos2',
      events=[{'t': 15, 'do': 'dial', 'pos': 'pos1'}]),
    S('B8', 'during start-up 1->3 and back to 1',
      events=[{'t': 10, 'do': 'dial', 'pos': 'pos3'}, {'t': 20, 'do': 'dial', 'pos': 'pos1'}]),
    S('B9', 'during start-up 1->2 (recipes), then order a recipe', user=REC,
      events=[{'t': 12, 'do': 'dial', 'pos': 'pos2'}]),

    # C: dial turned while talking
    S('C1', 'turn 1->3 while it listens (quiet)', events=[{'at': 'ready', 'delay': 2, 'do': 'dial', 'pos': 'pos3'}]),
    S('C2', 'turn 1->3 while you talk', events=[{'at': 'say', 'delay': 0.8, 'do': 'dial', 'pos': 'pos3'}]),
    S('C3', 'turn 1->3 while it thinks (blue)', events=[{'at': 'gen_start', 'delay': 1.0, 'do': 'dial', 'pos': 'pos3'}]),
    S('C4', 'turn 1->2 (recipes) while it thinks (blue)', events=[{'at': 'gen_start', 'delay': 1.0, 'do': 'dial', 'pos': 'pos2'}]),
    S('C5', 'turn 1->3 while it answers (orange)', events=[{'at': 'answer', 'delay': 1.0, 'do': 'dial', 'pos': 'pos3'}]),
    S('C6', 'recipe being written, then turn to 1', start_dial='pos2', user=REC,
      events=[{'at': 'cooking', 'delay': 2.5, 'do': 'dial', 'pos': 'pos1'}]),
    S('C7', 'two quick turns (1->2, 2 s later ->3)',
      events=[{'at': 'ready', 'delay': 2, 'do': 'dial', 'pos': 'pos2'},
              {'at': 'ready', 'delay': 4, 'do': 'dial', 'pos': 'pos3'}]),
    S('C8', 'turn 1->3 with contact bounce', events=[{'at': 'ready', 'delay': 2, 'do': 'dial', 'pos': 'pos3', 'bounce': 3}]),

    # D: the yellow button
    S('D1', 'short press during start-up (t=10s)', events=[{'t': 10, 'do': 'press', 'dur': 0.2}]),
    S('D2', 'long press (3 s) during start-up (t=12s)', events=[{'t': 12, 'do': 'press', 'dur': 3.0}]),
    S('D3', 'press during the start message', events=[{'at': 'start_msg', 'delay': 1.0, 'do': 'press', 'dur': 0.2}]),
    S('D4', 'press while it thinks (blue)', events=[{'at': 'gen_start', 'delay': 1.0, 'do': 'press', 'dur': 0.2}]),
    S('D5', 'press while it answers (orange)', events=[{'at': 'answer', 'delay': 0.8, 'do': 'press', 'dur': 0.2}]),
    S('D6', 'long press (2.5 s) while it answers', events=[{'at': 'answer', 'delay': 0.5, 'do': 'press', 'dur': 2.5}]),
    S('D7', 'recipe done (purple), press for a new one', start_dial='pos2', user=REC,
      events=[{'at': 'delivered', 'delay': 3, 'do': 'press', 'dur': 0.2}]),
    S('D8', 'press during "give me a moment"', start_dial='pos2', user=REC,
      events=[{'at': 'cooking', 'delay': 3, 'do': 'press', 'dur': 0.2}]),
    S('D8b', 'press while the recipe is being written (blue)', start_dial='pos2', user=REC,
      events=[{'at': 'cooking', 'delay': 7, 'do': 'press', 'dur': 0.2}]),
    S('D9', 'press during "I heard ... is that right?"', start_dial='pos2', user=REC,
      events=[{'at': 'readback', 'delay': 0.5, 'do': 'press', 'dur': 0.2}]),
    S('D10', 'short press while it listens', events=[{'at': 'ready', 'delay': 2, 'do': 'press', 'dur': 0.2}]),
    S('D11', 'long press (3 s) while it listens ("reset")', events=[{'at': 'ready', 'delay': 2, 'do': 'press', 'dur': 3.0}]),

    # E: servers, timing, restarts
    S('E1', 'slow cold start: chat model loads in 40 s (crank, 1.5 GHz)', chat_load=40),
    S('E2', 'very slow start: chat model loads in 55 s', chat_load=55, end=120),
    S('E3', 'chat server never starts (model missing)', chat_dead=True, end=90),
    S('E4', 'embedding server never starts', embed_dead=True, end=90),
    S('E5', 'warm restart (systemctl restart): model from page cache, 8 s', chat_load=8),
    S('E6', 'chat server dies in the middle of an answer', events=[{'at': 'answer', 'delay': 1, 'do': 'kill_chat'}], end=100),
    S('E7', 'long conversation: 40 questions in Outdoor Tips', user={'turns': 40, 'reaction': 0.6},
      answer_words=70, end=1500, jitter=0.05),
    S('E8', 'a question containing "please quite"',
      user={'turns': 1, 'questions': ['can you please quite simply explain how to purify water']}),
    S('E9', 'one request fails (server error), then ask again', user={'turns': 3}, fail_requests=[2]),

    # F: combinations
    S('F1', 'start 2, turn to 3 during start-up and press the button', start_dial='pos2',
      events=[{'t': 12, 'do': 'dial', 'pos': 'pos3'}, {'t': 14, 'do': 'press', 'dur': 0.2}]),
    S('F2', 'dial between positions, press during boot, turn to 1 at t=20', start_dial=None,
      events=[{'t': 9, 'do': 'press', 'dur': 0.3}, {'t': 20, 'do': 'dial', 'pos': 'pos1'}]),
    S('F3', 'start 3, press during the start message, then turn to 1', start_dial='pos3',
      events=[{'at': 'start_msg', 'delay': 1, 'do': 'press', 'dur': 0.2},
              {'at': 'ready', 'delay': 1, 'do': 'dial', 'pos': 'pos1'}]),
    S('F4', 'turn to recipes while thinking, then press to recover', user={'turns': 3},
      events=[{'at': 'gen_start', 'delay': 1, 'do': 'dial', 'pos': 'pos2'},
              {'at': 'delivered', 'delay': 2, 'do': 'press', 'dur': 0.2}]),
]


def fuzz(n, base_seed=1000):
    out = []
    for k in range(n):
        r = random.Random(base_seed + k)
        pos = r.choice(['pos1', 'pos2', 'pos3'])
        evs, cur = [], pos
        for _ in range(r.randint(0, 3)):
            nxt = r.choice([p for p in ('pos1', 'pos2', 'pos3') if p != cur])
            evs.append({'t': round(r.uniform(3, 85), 1), 'do': 'dial', 'pos': nxt})
            cur = nxt
        evs.sort(key=lambda e: e['t'])
        for _ in range(r.randint(0, 2)):
            evs.append({'t': round(r.uniform(3, 85), 1), 'do': 'press', 'dur': r.choice([0.2, 0.2, 2.5])})
        out.append(S(f'Z{k + 1:02d}', 'random combination', start_dial=pos, user={'turns': 3},
                     events=evs, end=120))
    return out


def make_snapshot():
    """Copy the code under test to a local temp dir (see SIM_ROOT in harness.py)."""
    root = tempfile.mkdtemp(prefix='outdoorgpt_sim_')
    repo = os.path.dirname(os.path.dirname(HERE))
    ignore = shutil.ignore_patterns('__pycache__')
    shutil.copytree(os.path.join(HERE, 'fakes'), os.path.join(root, 'fakes'), ignore=ignore)
    shutil.copytree(os.path.join(HERE, 'upstream'), os.path.join(root, 'upstream'), ignore=ignore)
    os.makedirs(os.path.join(root, 'scripts'))
    for name in os.listdir(os.path.join(repo, 'scripts')):
        if name.endswith('.py') or name == 'config.sh':
            shutil.copy2(os.path.join(repo, 'scripts', name), os.path.join(root, 'scripts', name))
    shutil.copy2(os.path.join(repo, 'prompts.json'), os.path.join(root, 'prompts.json'))
    shutil.copy2(os.path.join(HERE, 'harness.py'), os.path.join(root, 'harness.py'))
    return root


def run_one(sc, seed, root):
    cfg = dict(sc, seed=seed)
    cfg.pop('title', None)
    env = dict(os.environ, SIM_ROOT=root)
    try:
        p = subprocess.run([sys.executable, os.path.join(root, 'harness.py'), json.dumps(cfg)],
                           capture_output=True, text=True, timeout=600, env=env)
        line = [l for l in p.stdout.splitlines() if l.startswith('{')][-1]
        res = json.loads(line)
    except Exception as e:
        res = {'id': sc['id'], 'seed': seed, 'flags': [{'code': 'HARNESS_ERROR', 'msg': repr(e)[:300]}]}
    res['title'] = sc['title']
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, default=3)
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--only', default='')
    ap.add_argument('--fuzz', type=int, default=20)
    ap.add_argument('--out', default=os.path.join(HERE, 'results.jsonl'))
    ap.add_argument('--report', default=os.path.join(HERE, 'report.md'))
    a = ap.parse_args()
    scs = SCENARIOS + fuzz(a.fuzz)
    if a.only:
        keep = a.only.split(',')
        scs = [s for s in scs if any(s['id'] == k or s['id'].startswith(k) for k in keep)]
    jobs = []
    for sc in scs:
        seeds = [1] if sc['id'].startswith(('Z', 'E7')) else list(range(1, a.seeds + 1))
        jobs += [(sc, s) for s in seeds]
    print(f'{len(jobs)} runs ...', flush=True)
    rev = git_rev()
    root = make_snapshot()
    try:
        with ThreadPoolExecutor(a.jobs) as ex:
            results = list(ex.map(lambda j: run_one(*j, root), jobs))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    with open(a.out, 'w', encoding='utf-8') as f:
        for r in results:
            f.write(json.dumps(r, default=str) + '\n')
    report(results, scs, a.report, rev)


def git_rev():
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=HERE, capture_output=True,
                              text=True).stdout.strip() + (
            ' (+ uncommitted changes)' if subprocess.run(['git', 'status', '--porcelain', '../../scripts'],
                                                         cwd=HERE, capture_output=True, text=True).stdout.strip()
            else '')
    except Exception:
        return '?'


def report(results, scs, path, rev='?'):
    by = defaultdict(list)
    for r in results:
        by[r['id']].append(r)
    lines = ['| id | scenario | runs | ready (s) | mode / dial at the end | findings (runs) |',
             '|---|---|---|---|---|---|']
    totals = Counter()
    for sc in scs:
        rs = by.get(sc['id'], [])
        c = Counter()
        for r in rs:
            for code in {f['code'] for f in r.get('flags', [])}:
                c[code] += 1
        totals.update({k: 1 for k in c})
        ready = sorted(r.get('ready_t') for r in rs if r.get('ready_t'))
        rd = f'{ready[0]:.0f}-{ready[-1]:.0f}' if ready else '-'
        ends = Counter(f"{r.get('mode_end')}/{r.get('dial_end')}" for r in rs)
        fl = ', '.join(f'{k} ({v}/{len(rs)})' for k, v in sorted(c.items())) or 'ok'
        lines.append(f"| {sc['id']} | {sc['title']} | {len(rs)} | {rd} | {', '.join(ends)} | {fl} |")
    head = [f'# Start-up simulation, scripts at {rev}', '',
            f'{len(results)} runs, {datetime.date.today().isoformat()}. "ready" is sim seconds from the '
            f'start of custom.sh to the first green LED with the microphone open (add ~5 s for the kernel).', '']
    legend = ['', '## Findings', ''] + [f'- `{k}` ({totals.get(k, 0)} scenarios): {v}'
                                        for k, v in LEGEND.items() if totals.get(k)]
    txt = '\n'.join(head + lines + legend)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(txt + '\n')
    print(txt)


if __name__ == '__main__':
    main()
