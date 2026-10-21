#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_coid_and_scale.py - Fix ParseError in clientOrderId + Scale reason logic"""
import os, sys, shutil, py_compile, time

DEPLOY = '--deploy' in sys.argv

# پچ ۱: اصلاح تولید clientOrderId در تابع run (حذف کاراکترهای غیرمجاز مثل _)
T1_OLD = "        coid = f'nbx-{sym.lower()}-{int(time.time())}'"
T1_NEW = "        coid = f'nbx-{sym.lower().replace(\"_\", \"\")}-{int(time.time())}'"

# پچ ۲: اصلاح coid2 در G-scale (تغییر _s2 به -s2)
T2_OLD = "                coid2 = (coid + '_s2') if coid else None"
T2_NEW = "                coid2 = (coid + '-s2') if coid else None"

# پچ ۳: اصلاح منطق reason در G-scale
T3_OLD = """    # G-scale: Calculate 2 entry prices for scaling in
    _price1, _price2 = _calc_scaled_entries(sym, price, row, st)
    if _price1 is None:
        _pull = _eff_pullback_pct(row, st) / 100.0
        _price1 = price * (1 - _pull)
        _price2 = None
    # Split volume: 50% each
    _size1 = round(_size * 0.5, 2)
    _size2 = round(_size - _size1, 2) if _price2 else 0
    # Order 1 (Fib 0.618)
    vol = math.floor((_size1 / _price1) * 1e8) / 1e8
    if vol <= 0:
        return
    amount = round(_size1, 2)
    reason = f"رأی خرید {a['buys']}/{a['total']} تایم‌فریم | Scale 1/2 (Fib 0.618)" + _band_tag(st, row)"""

T3_NEW = """    # G-scale: Calculate 2 entry prices for scaling in
    _price1, _price2 = _calc_scaled_entries(sym, price, row, st)
    if _price1 is None:
        # fallback to single order
        _pull = _eff_pullback_pct(row, st) / 100.0
        _price1 = price * (1 - _pull)
        _price2 = None
        reason = f"رأی خرید {a['buys']}/{a['total']} تایم‌فریم" + _band_tag(st, row)
    else:
        reason = f"رأی خرید {a['buys']}/{a['total']} تایم‌فریم | Scale 1/2 (Fib 0.618)" + _band_tag(st, row)
    # Split volume: 50% each
    _size1 = round(_size * 0.5, 2)
    _size2 = round(_size - _size1, 2) if _price2 else 0
    # Order 1 (Fib 0.618)
    vol = math.floor((_size1 / _price1) * 1e8) / 1e8
    if vol <= 0:
        return
    amount = round(_size1, 2)"""

CHANGES = {
    'trader.py': [(T1_OLD, T1_NEW, 'fix coid generation (remove underscore)'),
                  (T2_OLD, T2_NEW, 'fix coid2 generation (use -s2 instead of _s2)'),
                  (T3_OLD, T3_NEW, 'fix scale reason logic')]
}

def main():
    os.chdir(os.path.expanduser('~/nobitex-usdt'))
    print('=' * 72)
    print('fix_coid_and_scale.py - Fix ParseError + Scale logic')
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
        print('  cd ~/nobitex-usdt && venv/bin/python fix_coid_and_scale.py --deploy')
    print('=' * 72)

if __name__ == '__main__':
    main()
