# apply_guards_syms.py v3 - G-syms: distinct symbols rejected in last 60 min
# display-only, zero trading-behavior change
import py_compile, shutil, datetime, sys
SRC = 'trader.py'
T = open(SRC, encoding='utf-8').read()

def rep(old, new, n=1):
    global T
    c = T.count(old)
    assert c == n, 'anchor x%d (expected %d): %r' % (c, n, old[:60])
    T = T.replace(old, new)

if 'G-syms' in T:
    print('already applied'); sys.exit(0)

# 1) reference time = newest log line timestamp
rep("""        rows = []
        for name, pattern, cond in GUARDS_DEFS:""",
"""        rows = []
        _ref_time = None  # G-syms: ref = newest log timestamp
        for _line in reversed(recent_lines):
            _mt = _re.match(r'(\\d{4}-\\d{2}-\\d{2}) (\\d{2}:\\d{2}:\\d{2})', _line)
            if _mt:
                try:
                    _ref_time = _dt.strptime(_mt.group(1) + ' ' + _mt.group(2), '%Y-%m-%d %H:%M:%S')
                except Exception:
                    pass
                break
        for name, pattern, cond in GUARDS_DEFS:""")

# 2) init distinct-symbol list per guard
rep("""            last_reason = '—'
            for line in recent_lines:""",
"""            last_reason = '—'
            syms = []  # G-syms: distinct symbols rejected in last 60 min
            for line in recent_lines:""")

# 3) collect symbols inside the 60-min window
rep("""                    if _gs:
                        last_sym = _gs""",
"""                    if _gs:
                        last_sym = _gs
                    if _gs and _gs not in syms:
                        _mt = _re.match(r'(\\d{4}-\\d{2}-\\d{2}) (\\d{2}:\\d{2}:\\d{2})', line)
                        if _mt and _ref_time:
                            try:
                                _lt = _dt.strptime(_mt.group(1) + ' ' + _mt.group(2), '%Y-%m-%d %H:%M:%S')
                                if 0 <= (_ref_time - _lt).total_seconds() <= 3600:
                                    syms.append(_gs)
                            except Exception:
                                pass""")

# 4) newest-5 display after the loop
rep("""                        last_reason = _gr
            note = ''""",
"""                        last_reason = _gr
            if syms:
                last_sym = '، '.join(syms[-5:]) + (' ...' if len(syms) > 5 else '')
            note = ''""")

# 5) header rename
rep("'آخرین رد (۲۴س)', 'نماد', 'علت'", "'آخرین رد (۲۴س)', 'نمادها (۶۰د)', 'علت'", 1)

bak = 'trader.py.bak-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
shutil.copy2(SRC, bak)
open(SRC, 'w', encoding='utf-8').write(T)
py_compile.compile(SRC, doraise=True)
print('patched OK, backup:', bak)
