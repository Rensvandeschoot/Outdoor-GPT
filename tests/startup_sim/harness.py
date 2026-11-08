"""Run ONE start-up scenario of OutdoorGPT against the real overlay code.

    python harness.py '<scenario json>'

The repo's own scripts/voice_agent_cli.py, voice_agent.py, voice_agent_utils.py,
leds.py and device_settings.py run unchanged on a scaled sim clock, with
upstream's gpio_inputs.py (vendored in upstream/). Hardware, models and servers
are fakes (fakes/), which come first on the path and so shadow eink_display.py
and rag.py. A driver thread plays the scenario (dial, button, user speech,
server faults); at the end the observations are checked against the oracles
and one JSON line is printed.
"""
import importlib.abc
import importlib.machinery
import json
import os
import queue
import re
import sys
import threading
import traceback
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
# run_matrix.py copies the code to a local temp dir first (SIM_ROOT): every
# real second spent reading files from a slow (network) drive would count 20x
# on the sim clock. Run on its own, the harness uses the repo in place.
ROOT = os.environ.get('SIM_ROOT')
if ROOT:
    FAKES, UPSTREAM = os.path.join(ROOT, 'fakes'), os.path.join(ROOT, 'upstream')
    SCRIPTS, PROMPTS = os.path.join(ROOT, 'scripts'), os.path.join(ROOT, 'prompts.json')
else:
    FAKES, UPSTREAM = os.path.join(HERE, 'fakes'), os.path.join(HERE, 'upstream')
    SCRIPTS, PROMPTS = os.path.join(REPO, 'scripts'), os.path.join(REPO, 'prompts.json')
    sys.dont_write_bytecode = True      # never leave __pycache__ in the repo
sys.path[:0] = [FAKES, UPSTREAM, SCRIPTS]
sys.setswitchinterval(0.0005)

import simworld as S  # noqa: E402

CFG = json.loads(sys.argv[1])
CFG.setdefault('chat_load', 21.0)
CFG.setdefault('embed_load', 3.0)
CFG.setdefault('end', 110.0)
S.install_clock()
W = S.World(CFG)
S.W = W
CFG['_chat_load'] = W.jit(CFG['chat_load'], 'chat_load', spread=0.15)
CFG['_embed_load'] = W.jit(CFG['embed_load'], 'embed_load')
W.init_dial(CFG.get('start_dial', 'pos1'))

REAL_OUT = sys.__stdout__
DIAL_MODE = {'pos1': 'TIPS', 'pos2': 'RECIPE', 'pos3': 'SURVIVE'}
TAGS = ('TIPS', 'SURVIVE', 'RECIPE')


class _Capture:
    def __init__(self):
        self.buf = ''

    def write(self, s):
        self.buf += s
        while '\n' in self.buf:
            line, self.buf = self.buf.split('\n', 1)
            if line.strip():
                W.stdout.append((round(S.now(), 2), line.strip()[:160]))
        return len(s)

    def flush(self):
        pass


sys.stdout = _Capture()


def _hook(args):
    W.thread_exc.append((round(S.now(), 2), args.thread.name if args.thread else '?',
                         f'{type(args.exc_value).__name__}: {args.exc_value}'))


threading.excepthook = _hook

# ---------------------------------------------------------------- sim threads
trace = []          # (t, snapshot) on change
phase = {'ready': [], 'gen_start': [], 'delivered': []}


def mic_loop():
    last = S.now()
    while True:
        S.real_sleep(0.1 * S.SCALE)
        t = S.now()
        fr = W.frame(last, t)
        last = t
        for s in list(W.input_streams):
            if s._active:
                try:
                    s.q.put_nowait(fr)
                except queue.Full:
                    pass


def sampler():
    prev = None
    was_gen = was_deliv = False
    while True:
        snap = W.snapshot_state()
        snap.pop('playing', None)
        snap['playing'] = W.playing is not None
        t = round(S.now(), 2)
        if snap != prev:
            trace.append((t, dict(snap)))
            prev = snap
        if snap.get('led') == 'listening' and snap.get('mic') and not phase['ready']:
            phase['ready'].append(t)
        g = bool(snap.get('gen'))
        if g and not was_gen:
            phase['gen_start'].append(t)
        was_gen = g
        d = bool(snap.get('delivered'))
        if d and not was_deliv:
            phase['delivered'].append(t)
        was_deliv = d
        S.sleep(0.05)


def phase_times(name):
    if name in phase:
        return list(phase[name])
    played = list(W.played)
    if name == 'start_msg':
        return [p['start'] for p in played[:1]]
    if name == 'answer':
        return [p['start'] for p in played if any(w in p['text'].split() for w in TAGS)]
    if name == 'readback':
        return [p['start'] for p in played if p['text'].startswith('I heard')]
    if name == 'cooking':
        return [p['start'] for p in played if p['text'].startswith('Thanks. Give me')]
    if name == 'reset':
        return [r['t0'] for r in W.resets]
    if name == 'say':
        return [u['t0'] for u in W.utterances]
    raise ValueError(name)


def do_action(ev):
    a = ev['do']
    if a == 'dial':
        W.turn_dial(ev['pos'], bounce=ev.get('bounce', 0))
    elif a == 'press':
        W.press(ev.get('dur', 0.2))
    elif a == 'say':
        W.say(ev['text'], ev.get('dur'))
    elif a == 'kill_chat':
        W.chat_killed_at = S.now()
        W.ev('chat_server_killed')
    else:
        raise ValueError(a)


def user_loop(spec):
    qs = spec.get('questions') or [
        'how do I keep my feet dry on a long hike', 'what should I pack for rain',
        'how do I find north without a compass', 'how much water do I need per day',
        'what is the best way to light wet wood', 'how do I treat a blister']
    turns, i = spec.get('turns', 2), 0
    S.sleep(spec.get('start_after', 0))
    while i < turns and S.now() < CFG['end'] - 5:
        if W.agent_exit:
            return
        # wait for the agent's turn to end: mic open, quiet, not thinking, stable
        stable_since = None
        while S.now() < CFG['end'] - 5 and not W.agent_exit:
            s = W.snapshot_state()
            ok = s['mic'] and W.playing is None and not s.get('gen') and s['led'] == 'listening'
            if ok:
                stable_since = stable_since or S.now()
                if S.now() - stable_since >= spec.get('reaction', 0.8):
                    break
            else:
                stable_since = None
            S.sleep(0.05)
        else:
            return
        oh = W.va.output_handler
        if oh.recipe_mode:
            if oh.recipe_delivered:
                return
            last = W.played[-1]['text'] if W.played else ''
            text = 'yes that is right' if last.startswith('I heard') else 'pasta tuna and an onion'
        else:
            text = qs[i % len(qs)]
        u = W.say(text)
        i += 1
        t_end = S.now() + 45
        while S.now() < t_end and not W.agent_exit:
            if any(p['start'] > u['t1'] for p in list(W.played)):
                break
            S.sleep(0.1)


def driver():
    pending = [dict(e) for e in CFG.get('events', [])]
    while S.now() < CFG['end']:
        if W.agent_exit and S.now() > W.agent_exit['t'] + 12:
            break
        for ev in list(pending):
            if 't' in ev:
                due = ev['t']
            else:
                ts = phase_times(ev['at'])
                n = ev.get('n', 1)
                if len(ts) < n:
                    continue
                due = ts[n - 1] + ev.get('delay', 0.0)
            if S.now() >= due:
                pending.remove(ev)
                W.ev('scenario_action', **{k: v for k, v in ev.items() if k != 'text'})
                threading.Thread(target=do_action, args=(ev,), name=f"act-{ev['do']}", daemon=True).start()
        S.sleep(0.02)
    finish(pending)


# --------------------------------------------------------------- the oracles
def value_at(t, key):
    v = None
    for tt, snap in trace:
        if tt > t:
            break
        v = snap.get(key)
    return v


def check(pending):
    flags = []

    def flag(code, msg):
        flags.append({'code': code, 'msg': msg})

    ready = phase['ready'][0] if phase['ready'] else None
    if CFG.get('button_stuck') and W.agent_exit and W.agent_exit['how'].startswith('os._exit(3)'):
        flag('RESTART_FROM_STUCK_BUTTON', f"{W.agent_exit['t']:.1f}s a button that read pressed from power-up "
                                          f"was taken for a 20 s hold: the pipeline restarts, in a loop")
    if W.agent_exit and W.agent_exit['how'].startswith('os._exit(3)'):
        flag('PIPELINE_RESTART', f"{W.agent_exit['t']:.1f}s the agent asked the boot script to restart "
                                 f"everything (exit code 3)")
    elif W.agent_exit:
        # What happens next is up to the boot script (see test_boot_script.sh):
        # without a restart loop this is a dead box until the power is cycled.
        flag('AGENT_EXIT', f"agent process ended at {W.agent_exit['t']:.1f}s ({W.agent_exit['how']})")
    for t, th, e in W.thread_exc:
        flag('THREAD_CRASH', f'{t:.1f}s in thread {th}: {e}')

    # LEDs while the phone starts: red only after an error (failed_starts)
    fs = CFG.get('failed_starts', 0)
    t_ready = ready if ready is not None else S.now()
    boot = [s for t, s in W.led_frames if t < t_ready - 0.5]
    holds = [(p['down'], p['up'] if p['up'] is not None else S.now()) for p in W.presses]
    red_boot = [t for t, s in W.led_frames if s == 'error' and t < t_ready - 0.5
                and not any(d + 1.9 <= t <= u + 0.2 for d, u in holds)]
    if fs >= 3 and (not red_boot or 'starting' in boot):
        flag('FAILURE_NOT_SHOWN', f'{fs} failed starts in a row, but the start-up did not blink red: {boot[:6]}')
    elif 0 < fs < 3 and (len(red_boot) < 2 or 'starting' not in boot):
        flag('RECOVERY_NOT_SHOWN', f'starting after {fs} failed start(s), but no red flicks in the breath: {boot[:6]}')
    elif fs == 0 and red_boot:
        flag('FALSE_ERROR_SIGNAL', f'red during a normal start-up at {red_boot[:3]}')

    # LEDs dark while the phone starts
    first_led = next((t for t, s in W.led_frames if s not in ('off', 'dark')), None)
    if first_led is None or first_led > 3.0:
        flag('BOOT_LEDS_DARK', f'the LEDs stayed dark for the first '
                               f'{first_led if first_led is not None else S.now():.1f}s of the start-up')

    # boot path: random prompt, lost GPIO edges
    for t, line in W.stdout:
        if 'using random prompt' in line:
            flag('RANDOM_PROMPT', f'{t:.1f}s: {line}')
        if 'no rotary position detected' in line:
            flag('NO_DIAL_POSITION', f'{t:.1f}s: {line}')
    lost = [(t, d) for t, k, d in W.events if k == 'gpio_edge_lost']
    lost_dial = [(t, d) for t, d in lost if d['pin'] != S.PIN_BUTTON and d['edge'] == 'press']
    # A short press before the agent is ready has nothing to act on; the LEDs
    # must still show that it arrived (one breath at full brightness).
    lost_btn = [(pr['up'], None) for pr in W.presses
                if pr['up'] is not None and pr['dur'] < 2.0 and pr['state_at_up'].get('led') in ('starting', 'dark')
                and not any(pr['down'] - 0.1 <= t <= pr['up'] + 1.0 for t in W.boot_acks)]
    if lost_dial:
        flag('DIAL_EVENT_LOST', 'dial edges before the callback existed: ' +
             ', '.join(f"{t:.1f}s pin{d['pin']}" for t, d in lost_dial))
    if lost_btn:
        flag('BUTTON_LOST_AT_BOOT', 'a press during start-up showed nothing on the LEDs: ' +
             ', '.join(f'{t:.1f}s' for t, d in lost_btn))

    # dial vs the prompt actually in use
    va_mode = W.va_mode()
    last_move = W.dial_moves[-1][0] if W.dial_moves else 0
    want = DIAL_MODE.get(W.dial_pos)
    if want and va_mode and va_mode != want and not W.agent_exit:
        flag('DIAL_MISMATCH', f"at the end the dial says {W.dial_pos} ({want}) but the agent runs {va_mode} "
                              f"(last dial move {last_move:.1f}s)")
    mism, start = 0.0, None
    moves = [m[0] for m in W.dial_moves]
    for t, snap in trace:
        want_t = DIAL_MODE.get(snap.get('dial'))
        bad = (ready is not None and t >= ready and want_t and snap.get('mode') and snap.get('mode') != want_t
               and not any(0 <= t - m < 4.0 for m in moves))
        if bad and start is None:
            start = t
        if not bad and start is not None:
            mism = max(mism, t - start)
            start = None
    if start is not None:
        mism = max(mism, S.now() - start)

    # what was spoken
    for p in W.played:
        tags = [w for w in TAGS if w in p['text'].split()]
        if tags and p['mode_at_start'] and tags[0] != p['mode_at_start']:
            flag('STALE_SPEECH', f"{p['start']:.1f}s spoke a {tags[0]} answer while the mode was "
                                 f"{p['mode_at_start']}: '{p['text'][:50]}'")
        if p['overlap']:
            flag('OVERLAPPING_SPEECH', f"{p['start']:.1f}s two sentences played at once: '{p['text'][:40]}'")

    # what was sent to the model
    for r in W.llm_requests:
        roles = r['roles']
        expect = ['system'] + ['user' if i % 2 == 0 else 'assistant' for i in range(len(roles) - 1)]
        if roles != expect or roles[-1] != 'user':
            flag('CONTEXT_POLLUTED', f"{r['t']:.1f}s request in {r['mode']} has roles {roles}")
        for role, c in r['msgs'][1:]:
            if role == 'assistant':
                tg = [w for w in TAGS if w in c.split()]
                if tg and tg[0] != r['mode']:
                    flag('CONTEXT_POLLUTED', f"{r['t']:.1f}s {r['mode']} context carries a {tg[0]} answer")
        last_user = [c for role, c in r['msgs'] if role == 'user'][-1:]
        if last_user and '«' in last_user[0]:
            flag('ECHO_AS_INPUT', f"{r['t']:.1f}s the agent's own voice went to the model as a question: "
                                  f"'{last_user[0][:60]}'")
        if r.get('error') == 'exceed_context_size':
            flag('CONTEXT_OVERFLOW', f"{r['t']:.1f}s request of {r['tokens']} tokens refused by the server "
                                     f"(n_ctx {CFG.get('n_ctx', 4096)}), after {len(roles) // 2} turns")
    for t, line in W.convlog:
        if 'USER:' in line and '«' in line:
            flag('ECHO_HEARD', f'{t:.1f}s transcript contains the agent itself: {line[:70]}')
            break

    # recipe integrity
    for e in W.eink:
        if e['kind'] == 'recipe' and 'Ingredients' not in e['text']:
            flag('BOGUS_RECIPE_SCREEN', f"{e['t0']:.1f}s a non-recipe answer was drawn as the recipe: "
                                        f"'{e['text'][:50]}'")
    for t in phase['delivered']:
        since = max([r['t0'] for r in W.resets if r['t0'] <= t] + [0])
        if not any(since <= r['t'] <= t and any(c.startswith('My ingredients:') for _, c in r['msgs'])
                   for r in W.llm_requests):
            flag('BOGUS_RECIPE_STATE', f'{t:.1f}s recipe mode marked "delivered" without a confirmed list')

    # the button
    for pr in W.presses:
        if pr['up'] is None and pr['dur'] < 20.0:
            continue                    # the run ended while it was held
        up, st = (pr['up'] if pr['up'] is not None else S.now()), pr['state_at_up']
        nxt = [u['t0'] for u in W.utterances if u['t0'] > up]
        before_next = nxt[0] if nxt else up + 25
        if pr['dur'] >= 2.0:
            if not [t for t, s in W.led_frames if s == 'hold' and pr['down'] + 1.9 <= t <= up]:
                flag('HOLD_NOT_SHOWN', f"{pr['down']:.1f}-{up:.1f}s held {pr['dur']:.1f}s: the LEDs never "
                                       f"turned white to say 'let go now'")
        if pr['dur'] >= 20.0:
            ex = W.agent_exit or {}
            if not (ex.get('how', '').startswith('os._exit(3)') and pr['down'] + 19.5 <= ex['t'] <= pr['down'] + 21.5):
                flag('RESTART_HOLD_NO_EFFECT', f"{pr['down']:.1f}s held {pr['dur']:.1f}s: no pipeline restart at 20 s")
            continue
        if pr['dur'] >= 2.0:
            if ready is None or up < ready:
                continue    # still starting: the LEDs show it, there is nothing to reset yet
            if not [r for r in W.resets if up - 0.1 <= r['t0'] <= up + 3]:
                flag('LONG_PRESS_NO_EFFECT', f"{pr['down']:.1f}-{up:.1f}s held {pr['dur']:.1f}s: the mode did not "
                                             f"start over")
            continue
        if st.get('delivered'):
            if not [r for r in W.resets if up - 0.1 <= r['t0'] <= up + 2]:
                flag('BUTTON_NO_RESTART', f'{up:.1f}s press after a recipe did not restart the mode')
        elif st.get('gen') and not (st.get('spk') or st.get('proc')) and st.get('recipe_mode'):
            drawn = [e for e in W.eink if e['kind'] == 'recipe' and e['t0'] > up]
            if drawn or not [r for r in W.resets if up - 0.1 <= r['t0'] <= up + 3]:
                flag('BUTTON_IGNORED_THINKING', f'{up:.1f}s press while a recipe was being written: '
                                                f'{"it was still drawn" if drawn else "no new recipe was started"}')
        elif st.get('gen') and not (st.get('spk') or st.get('proc')):
            # The turn stops at the model's next token, so allow for the first
            # token's wait; what must not happen is the answer being spoken.
            if value_at(up + 8.0, 'gen') or [p for p in W.played if up + 1.0 < p['start'] < before_next and
                                              any(w in p['text'].split() for w in TAGS)]:
                flag('BUTTON_IGNORED_THINKING', f'{up:.1f}s press during the thinking pause (blue LED): '
                                                f'generation went on and the answer was still spoken')
        elif st.get('spk') or st.get('proc'):
            later = [p for p in W.played if up + 1.0 < p['start'] < before_next and
                     any(w in p['text'].split() for w in TAGS)]
            if later:
                flag('BUTTON_IGNORED_SPEECH', f'{up:.1f}s press while speaking: the answer went on at '
                                              f"{later[0]['start']:.1f}s")

    # The microphone open while the speaker plays: the agent hears itself
    # (speech recognition on its own voice costs crank power, and it can end
    # up asking itself a question).
    both, start = 0.0, None
    for t, snap in trace:
        bad = snap.get('mic') and snap.get('playing')
        if bad and start is None:
            start = t
        if not bad and start is not None:
            both = max(both, t - start)
            start = None
    if both > 0.3:
        flag('MIC_OPEN_WHILE_SPEAKING', f'the microphone was open while the speaker played, for {both:.1f}s')

    # LED says "your turn" while the microphone is off
    deaf, start = 0.0, None
    for t, snap in trace:
        bad = ready is not None and t > ready and snap.get('led') == 'listening' and not snap.get('mic')
        if bad and start is None:
            start = t
        if not bad and start is not None:
            deaf = max(deaf, t - start)
            start = None
    if deaf > 1.5:
        flag('GREEN_BUT_DEAF', f'LED green while the microphone was off for {deaf:.1f}s')

    for ev in pending:
        flag('SCENARIO_STEP_NOT_REACHED', f'{ev}')
    return flags, mism


def finish(pending):
    try:
        _finish(pending)
    except Exception:
        REAL_OUT.write(json.dumps({'id': CFG.get('id'), 'seed': CFG.get('seed'), 'flags': [
            {'code': 'HARNESS_ERROR', 'msg': traceback.format_exc()[-600:]}]}) + '\n')
        REAL_OUT.flush()
    finally:
        os._exit(0)


def _finish(pending):
    try:
        flags, mism = check(pending)
    except Exception:
        flags, mism = [{'code': 'HARNESS_ERROR', 'msg': traceback.format_exc()[-400:]}], 0
    led_first = next((t for t, s in W.led_frames if s not in ('off', 'dark')), None)
    out = {
        'id': CFG.get('id'), 'seed': CFG.get('seed'),
        'flags': flags, 'max_mismatch_s': round(mism, 1),
        'ready_t': phase['ready'][0] if phase['ready'] else None,
        'first_sound_t': W.played[0]['start'] if W.played else None,
        'first_led_t': led_first,
        'mode_end': W.va_mode(), 'dial_end': W.dial_pos,
        'jitters': W.jitters,
        'resets': W.resets,
        'played': [{k: p.get(k) for k in ('start', 'end', 'text', 'aborted', 'thread', 'mode_at_start')}
                   for p in W.played][:40],
        'requests': [{k: r[k] for k in ('t', 'mode', 'tokens', 'roles')} for r in W.llm_requests][:60],
        'eink': W.eink, 'presses': W.presses, 'dial_moves': W.dial_moves,
        'led': W.led_frames[:80], 'agent_exit': W.agent_exit,
        'gpio_cb_log': W.gpio_cb_log[:30],
        'stdout_tail': [l for l in W.stdout if '>>' in l[1] or 'Error' in l[1] or 'Waiting' in l[1]][-25:],
        'utterances': [{'t0': round(u['t0'], 2), 'text': u['text']} for u in W.utterances],
    }
    REAL_OUT.write(json.dumps(out, default=str) + '\n')
    REAL_OUT.flush()


# ----------------------------------------------------------------- the agent
def read_config_sh(path):
    """KEY=VALUE lines of config.sh (comments and blanks skipped)."""
    vals = {}
    for line in open(path, encoding='utf-8'):
        m = re.match(r'\s*([A-Z_][A-Z0-9_]*)=(.*)$', line)
        if m:
            vals[m.group(1)] = m.group(2).strip().strip('"\'')
    return vals


def boot_argv(c):
    """The agent's command line as startup_script.sh builds it in mode 3.

    Kept in step with the script by hand: when a flag is added there, add it
    here, so the simulation runs the phone exactly as it boots.
    """
    argv = ['voice_agent_cli.py', '--platform', c.get('PLATFORM', 'rpi5'), '--log-conversation',
            '--audio-device-input', c.get('AUDIO_IN', '1'), '--audio-device-output', c.get('AUDIO_OUT', '0'),
            '--speaking_rate', c.get('SPEAKING_RATE', '1.'),
            '--end_of_utterance_duration', c.get('SILENCE_SECONDS', '0.7'),
            '--prompt_file', PROMPTS,
            '--rag_index', c.get('RAG_INDEX', 'rag_index'),
            '--llm_server_url', f"http://localhost:{c.get('CHAT_PORT', '8080')}/v1",
            '--embedding_server_url', f"http://localhost:{c.get('EMBED_PORT', '8081')}/v1",
            '--max_history_turns', c.get('HISTORY_TURNS', '8')]
    if c.get('VERBOSE') == '1':
        argv.append('--verbose')
    if c.get('TTS_WARMUP') == '1':
        argv.append('--tts_warmup')
    for key, flag in (('TTS_THREADS', '--tts_threads'), ('ASR_THREADS', '--asr_threads')):
        if c.get(key) not in (None, '', '0'):
            argv += [flag, c[key]]
    argv += ['--server_wait', c.get('SERVER_WAIT', '90')]
    return argv


sys.argv = boot_argv(read_config_sh(os.path.join(SCRIPTS, 'config.sh')))
# As the boot script does: the servers' PIDs, so the agent can tell a server
# that is still loading from one whose process has died.
os.environ['OUTDOORGPT_CHAT_PID'] = str(S.CHAT_PID)
os.environ['OUTDOORGPT_EMBED_PID'] = str(S.EMBED_PID)
os.environ['OUTDOORGPT_FAILED_STARTS'] = str(CFG.get('failed_starts', 0))

def watchdog():
    while S.now() < CFG['end'] + 40:
        S.real_sleep(0.05)
    REAL_OUT.write(json.dumps({'id': CFG.get('id'), 'seed': CFG.get('seed'), 'flags': [
        {'code': 'HARNESS_TIMEOUT', 'msg': 'driver did not finish'}]}) + '\n')
    REAL_OUT.flush()
    os._exit(0)


for fn, name in ((mic_loop, 'sim-mic'), (sampler, 'sim-sampler'), (driver, 'sim-driver'),
                 (watchdog, 'sim-watchdog')):
    threading.Thread(target=fn, name=name, daemon=True).start()
if CFG.get('user') is not None:
    threading.Thread(target=user_loop, args=(CFG['user'],), name='sim-user', daemon=True).start()

def patch_voice_agent_utils(m):
    if hasattr(m, 'pid_alive'):
        m.pid_alive = W.server_alive


def patch_voice_agent(voice_agent):
    shim_q = types.ModuleType('queue_shim')

    class _ScaledQueue(queue.Queue):
        def get(self, block=True, timeout=None):
            return super().get(block, None if timeout is None else timeout * S.SCALE)

    shim_q.Queue, shim_q.Empty, shim_q.Full = _ScaledQueue, queue.Empty, queue.Full
    voice_agent.queue = shim_q

    _orig_init = voice_agent.VoiceAgent.__init__

    def _init(self, *a, **k):
        _orig_init(self, *a, **k)
        W.va = self
    voice_agent.VoiceAgent.__init__ = _init

    def _record_reset(orig):
        def _reset(self, system_prompt=None, start_message=None, **k):
            rec = {'t0': round(S.now(), 2), 'thread': threading.current_thread().name,
                   'to': S.mode_of(system_prompt) if system_prompt else None}
            W.resets.append(rec)
            try:
                return orig(self, system_prompt=system_prompt, start_message=start_message, **k)
            except Exception as e:
                rec['exc'] = f'{type(e).__name__}: {e}'
                raise
            finally:
                rec['t1'] = round(S.now(), 2)
        return _reset

    # Whichever method actually performs the reset in this version of the code.
    for _name in ('_do_full_reset', 'full_reset_with_prompt'):
        if hasattr(voice_agent.VoiceAgent, _name):
            setattr(voice_agent.VoiceAgent, _name, _record_reset(getattr(voice_agent.VoiceAgent, _name)))
            break

    _orig_int = voice_agent.LLmToAudio.interrupt

    def _interrupt(self):
        W.out_interrupts.append(round(S.now(), 2))
        return _orig_int(self)
    voice_agent.LLmToAudio.interrupt = _interrupt


def patch_leds(leds):
    leds.POLL_INTERVAL = 0.1 * S.SCALE


class _PatchOnImport(importlib.abc.MetaPathFinder):
    """Patch a module right after it is first imported, wherever that happens.

    The CLI imports its heavy modules itself, after the LEDs and the GPIO are
    up; importing them here first would move that cost to before the LEDs.
    """

    def __init__(self, hooks):
        self.hooks = hooks

    def find_spec(self, name, path=None, target=None):
        hook = self.hooks.get(name)
        if hook is None:
            return None
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        if spec is None or spec.loader is None:
            return spec
        exec_module = spec.loader.exec_module

        def exec_and_patch(module):
            exec_module(module)
            hook(module)
        spec.loader.exec_module = exec_and_patch
        return spec


sys.meta_path.insert(0, _PatchOnImport({'voice_agent': patch_voice_agent, 'leds': patch_leds,
                                        'voice_agent_utils': patch_voice_agent_utils}))

try:
    import voice_agent_cli
    # The 20 s hold ends the process with os._exit(3) for the boot script.
    # Here that ends the run: record it, write the result, stop.
    shim_os = types.ModuleType('os_shim')
    shim_os.__dict__.update(os.__dict__)

    def _agent_exit(code):
        W.agent_exit = {'t': round(S.now(), 2), 'how': f'os._exit({code})'}
        finish([])
    shim_os._exit = _agent_exit
    voice_agent_cli.os = shim_os
    shim_t = types.ModuleType('threading_shim')
    shim_t.__dict__.update(threading.__dict__)

    class _ScaledTimer(threading.Timer):
        def __init__(self, interval, function, args=None, kwargs=None):
            super().__init__(interval * S.SCALE, function, args, kwargs)
            self.name = 'rotary-timer'
    shim_t.Timer = _ScaledTimer
    voice_agent_cli.threading = shim_t

    getattr(voice_agent_cli, 'cli', voice_agent_cli.main)()
    W.agent_exit = {'t': round(S.now(), 2), 'how': 'main() returned'}
except BaseException as e:      # noqa: BLE001 - SystemExit included: that is a dead phone too
    W.agent_exit = {'t': round(S.now(), 2), 'how': f'{type(e).__name__}: {str(e)[:160]}'}

while True:
    S.real_sleep(0.05)
