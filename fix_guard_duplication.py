#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_guard_duplication.py - separate OPEN_POSITION_EXISTS from MAX_OPEN_POSITIONS"""
import os, sys, shutil, py_compile, time

DEPLOY = '--deploy' in sys.argv

T1_OLD = """    ('MAX_OPEN_POSITIONS',   'پوزیشن یا سفارش باز موجود',     True),"""
T1_NEW = """    ('OPEN_POSITION_EXISTS', 'پوزیشن یا سفارش باز موجود',     True),"""

T2_OLD = """    'MAX_OPEN_POSITIONS': 'جلوگیری از ورود همزمان به نمادی که پوزیشن باز دارد',"""
T2_NEW = """    'OPEN_POSITION_EXISTS': 'جلوگیری از ورود همزمان به نمادی که پوزیشن باز دارد',"""

CHANGES = {
    'trader.py': [(T1_OLD, T1_NEW, 'rename guard to OPEN_POSITION_EXISTS in GUARDS_DEFS'),
                  (T2_OLD, T2_NEW, 'rename key in GUARDS_DUTY')]
}

def main():
    os.chdir(os.path.expanduser('~/nobitex-usdt'))
    print('=' * 72)
    print('fix_guard_duplication.py - separate OPEN_POSITION_EXISTS')
    print('mode: DEPLOY' if DEPLOY else 'mode: DRY-RUN (preview only)')
    print('=' * 72)
    all_ok = True
    applied = []
    fname = 'trader.py'
    if not os.path.exists(fname):
        print('X %s not found' % fname)
        sys.exit(1)
    src = open(fname, encoding='utf-8').read()
    cand = src
    file_ok = True
    for old, new, desc in CHANGES[fname]:
        if old in cand:
            cand = cand.replace(old, new, 1)
            print('+ %s: %s' % (fname, desc))
            applied.append((fname, desc))
        else:
            print('X %s: pattern not found: %s' % (fname, desc))
            file_ok = False
            all_ok = False
    if not file_ok:
        sys.exit(1)
    cand_name = 'trader_candidate.py'
    with open(cand_name, 'w', encoding='utf-8') as f:
        f.write(cand)
    try:
        py_compile.compile(cand_name, doraise=True)
        print('  + py_compile: OK')
    except py_compile.PyCompileError as e:
        print('  X py_compile FAILED: %s' % e)
        sys.exit(1)
    if DEPLOY:
        bak = '%s.bak.%s' % (fname, time.strftime('%Y%m%d_%H%M'))
        shutil.copy2(fname, bak)
        print('  + backup: %s' % bak)
        shutil.move(cand_name, fname)
        print('  + deployed: %s' % fname)
    else:
        print('  (dry-run: candidate saved as %s)' % cand_name)
    print()
    print('=' * 72)
    print('+ %d patches ready' % len(applied))
    if DEPLOY:
        print('Deploy complete.')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python fix_guard_duplication.py --deploy')
    print('=' * 72)

if __name__ == '__main__':
    main()
