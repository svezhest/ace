"""6.11: входы v2 -> входы на голых видах: номера строк src/*.py по карте plain_view, без фраз о комментариях."""
import json, re, sys
V = {'00': 'alf_n4', '01': 'app_r1', '02': 'app_r1', '03': 'app_r1', '04': 'app_r4', '05': 'app_r4',
     '06': 'alf_r1', '07': 'alf_r4chk', '08': 'alf_r1', '09': 'app_n2'}
DROP = {'01': ' The docstring at src/harness.py:13-17 says the loop detection catches repeats.',
        '04': ' The comment at :187-190 says the recent-steps check catches these.'}
H = '/Users/user/Projects/nrhsi/runs'
for i, v in V.items():
    t = open(f'{H}/manual_1103/v2/in/{i}_v_rr.txt').read()
    if i in DROP:
        assert t.count(DROP[i]) == 1, i
        t = t.replace(DROP[i], '')
    m = {f: {int(k): n for k, n in d.items()} for f, d in json.load(open(f'{H}/plain_1106/{v}.linemap.json'))['map'].items()}
    cur = [None]
    def sub(x):
        if x.group(1):
            cur[0] = x.group(1)
        f = cur[0]
        if f not in m:                      # .md и прочее — без изменений
            return x.group(0)
        a = int(x.group(2)); b = int(x.group(3) or a)
        na = m[f].get(a) or m[f][min(k for k in m[f] if k > a)]
        nb = m[f].get(b) or m[f][max(k for k in m[f] if k < b)]
        r = f"{x.group(1) or ''}:{na}" + (f"-{nb}" if x.group(3) else "")
        print(f"  {i} {f}:{a}{'-'+str(b) if x.group(3) else ''} -> {r}", file=sys.stderr)
        return r
    code = t.split('\nCode: ')[1].split('\n')[0] if '\nCode: ' in t else ''
    newcode = re.sub(r'(src/[\w.]+)?:(\d+)(?:-(\d+))?', sub, code)
    t = t.replace(code, newcode)
    open(f'{H}/plain_1106/in/{i}_v_rr.txt', 'w').write(t)
