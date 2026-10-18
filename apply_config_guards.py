#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_config_guards.py — افزودن ۵ گارد جدید به تب «کانفیگ مؤثر»"""
import os, sys, shutil, py_compile, time

DEPLOY = '--deploy' in sys.argv

OLD = """            ['momentum guard', '%.1f%% above SMA20(1h)' % st.pump_guard_pct, 'Fix-3.2'],"""

NEW = """            ['momentum guard', '%.1f%% above SMA20(1h)' % st.pump_guard_pct, 'Fix-3.2'],
            ['G-volsize', 'cap $%.2f' % RISK_TARGET_USDT, 'vol-targeted sizing — برابرسازی ریسک دلاری هر معامله'],
            ['G-bandcap', '≤ %.1f%%' % MAX_SL_BAND_PCT, 'فیلتر دم پرنوسان (STRK/WAL) — رد نمادهای پرنوسان'],
            ['G-global', 'mark > 0', 'رد نمادهای بدون داده جهانی (COPXON, SLVON) — فقط نمادهایی که mark نوبیتکس دارند'],
            ['G-premium', '≤ %.1f%%' % MAX_LOCAL_PREMIUM_PCT, 'رد اگر پریمیوم محلی/جهانی > حد مجاز (ریسک تومانی شدید)'],
            ['G-mark-dev', '≤ %.1f%%' % MAX_MARK_DEVIATION_PCT, 'رد اگر قیمت محلی > حد مجاز بالاتر از جهانی (پامپ محلی بدون پشتوانه)'],"""

FNAME = 'trader.py'

def main():
    os.chdir(os.path.expanduser('~/nobitex-usdt'))
    print('=' * 72)
    print('apply_config_guards.py — افزودن گاردهای جدید به تب «کانفیگ مؤثر»')
    print('mode: DEPLOY' if DEPLOY else 'mode: DRY-RUN (preview only)')
    print('=' * 72)

    if not os.path.exists(FNAME):
        print('X %s not found' % FNAME)
        sys.exit(1)

    src = open(FNAME, encoding='utf-8').read()
    if OLD not in src:
        print('X pattern not found in trader.py')
        print('  expected: %s...' % OLD[:80])
        sys.exit(1)

    cand = src.replace(OLD, NEW, 1)
    print('+ trader.py: 5 new guards added to write_effective_config')

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
        bak = '%s.bak.%s' % (FNAME, time.strftime('%Y%m%d_%H%M'))
        shutil.copy2(FNAME, bak)
        print('  + backup: %s' % bak)
        shutil.move(cand_name, FNAME)
        print('  + deployed: %s' % FNAME)
    else:
        print('  (dry-run: candidate saved as %s)' % cand_name)

    print()
    print('=' * 72)
    if DEPLOY:
        print('Deploy complete. Verify with:')
        print('  cd ~/nobitex-usdt && venv/bin/python daily_report.py')
        print('Then check tab "کانفیگ مؤثر" in the sheet.')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python apply_config_guards.py --deploy')
    print('=' * 72)


if __name__ == '__main__':
    main()
