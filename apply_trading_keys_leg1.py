#!/usr/bin/env python3
# G-mhalf2: add 'LEG1_MARKET' to TRADING_KEYS whitelist in settings.py
# Root cause: from_sheet stores only whitelisted keys (L183-184);
# G-mhalf S1 added the property (L315) but missed the whitelist entry,
# so sheet row 95 (LEG1_MARKET=bale) is silently dropped.
# BUILD  : verify anchors on the real file (expect OLD=1, NEW=0)
# DEPLOY : backup .bak-TS + replace once + py_compile (auto-restore on fail)
import sys, shutil, subprocess, datetime, pathlib

ROOT = pathlib.Path(__file__).resolve().parent
SET = ROOT / 'settings.py'
OLD = "'MIN_TFS_SELL'}"
NEW = "'MIN_TFS_SELL', 'LEG1_MARKET'}"

def snap():
    t = SET.read_text(encoding='utf-8')
    return t, t.count(OLD), t.count(NEW)

def build():
    t, co, cn = snap()
    print('BUILD: count(OLD)=%d expect 1 | count(NEW)=%d expect 0' % (co, cn))
    ok = (co == 1 and cn == 0)
    print('BUILD:', 'PASS' if ok else 'FAIL')
    return ok

def deploy():
    t, co, cn = snap()
    if not (co == 1 and cn == 0):
        print('DEPLOY: ABORT - anchor precondition failed')
        return False
    ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    bak = ROOT / ('settings.py.bak-' + ts)
    shutil.copy2(SET, bak)
    print('DEPLOY: backup ->', bak.name)
    SET.write_text(t.replace(OLD, NEW, 1), encoding='utf-8')
    r = subprocess.run([sys.executable, '-m', 'py_compile', str(SET)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        shutil.copy2(bak, SET)
        print('DEPLOY: py_compile FAIL -> restored from backup')
        print(r.stderr)
        return False
    t2, co2, cn2 = snap()
    n = t2.count('LEG1_MARKET')
    print('DEPLOY: NEW=%d expect 1 | OLD=%d expect 0 | LEG1_MARKET occurrences=%d expect 2' % (cn2, co2, n))
    ok = (cn2 == 1 and co2 == 0 and n == 2)
    print('DEPLOY:', 'PASS' if ok else 'FAIL')
    return ok

if __name__ == '__main__':
    mode = (sys.argv[1] if len(sys.argv) > 1 else 'BUILD').upper()
    sys.exit(0 if (build() if mode == 'BUILD' else deploy()) else 1)
