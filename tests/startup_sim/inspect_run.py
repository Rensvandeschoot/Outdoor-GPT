"""Print the timeline of selected runs:  python inspect_run.py results.jsonl D10:1 C6 ..."""
import json
import sys

want = sys.argv[2:]
for line in open(sys.argv[1], encoding='utf-8'):
    d = json.loads(line)
    key = f"{d['id']}:{d.get('seed')}"
    if not any(w == d['id'] or w == key for w in want):
        continue
    print('=' * 100)
    print(key, d.get('title'), '| exit:', d.get('agent_exit'))
    for f in d.get('flags', []):
        print('  FLAG', f['code'], '-', f['msg'][:230])
    print('  dial', d.get('dial_moves'), '| presses', [(p['down'], p['up'], p['state_at_up']) for p in d.get('presses', [])])
    print('  resets', d.get('resets'))
    print('  eink', [(e['t0'], e['t1'], e['kind'], e['text'][:30]) for e in d.get('eink', [])])
    print('  led', d.get('led'))
    print('  requests', [(r['t'], r['mode'], r['tokens'], len(r['roles'])) for r in d.get('requests', [])][-8:])
    for p in d.get('played', []):
        print('  PLAY %7.2f-%-7s %-8s ab=%-5s %-26s %s' % (p['start'], p['end'], p['mode_at_start'], p['aborted'],
                                                        (p['thread'] or '')[:26], p['text'][:62]))
    print('  utter', d.get('utterances'))
    for t, l in d.get('stdout_tail', [])[-6:]:
        print('  OUT', t, l[:120])
