#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_mintfs_fix.py — MIN_TFS: 2 → 3 (ورود/خروج سیگنالی نیازمند ≥۳ تایم‌فریم)
اثر جانبی اعلام‌شده: is_sell_candidate هم همین حد را می‌گیرد.
بدون --deploy هیچ فایلی عوض نمی‌شود.
"""
import importlib.util
import os
import py_compile
import shutil
import sys
import time

SRC = 'trader.py'
CAND = 'trader_candidate.py'

OLD = "MIN_TFS = 2"
NEW = "MIN_TFS = 3  # بهبود: ورود نیازمند ≥۳ TF رأی خرید — کلاس 2/4 حذف (تحلیل ۱۵۵ پوزیشن؛ era-mixed)"


def build_candidate():
    with open(SRC, encoding='utf-8') as f:
        text = f.read()
    if 'MIN_TFS = 3' in text:
        sys.exit('ABORT: قبلاً patch شده')
    if text.count(OLD) != 1:
        sys.exit(f'ABORT: {text.count(OLD)} بار (انتظار ۱)')
    with open(CAND, 'w', encoding='utf-8') as f:
        f.write(text.replace(OLD, NEW, 1))
    print('MIN_TFS 2 → 3 — کاندید:', CAND)


def run_tests(mod):
    results = []

    def check(name, cond, extra=''):
        results.append((name, bool(cond)))
        print(('PASS' if cond else 'FAIL'), '-', name, ('| ' + extra) if (extra and not cond) else '')

    a2 = {'buys': 2, 'sells': 1, 'total': 4, 'best': (60, [])}
    check('MB1 2/4 دیگر کاندید نیست', mod.is_buy_candidate(a2) is False)
    a3 = {'buys': 3, 'sells': 1, 'total': 4, 'best': (75, [])}
    check('MB2 3/4 کاندید است', mod.is_buy_candidate(a3) is True)
    a4 = {'buys': 4, 'sells': 0, 'total': 4, 'best': (100, [])}
    check('MB3 4/4 کاندید است', mod.is_buy_candidate(a4) is True)
    a35 = {'buys': 3, 'sells': 2, 'total': 5, 'best': (60, [])}
    check('MB4 3/5 کاندید است', mod.is_buy_candidate(a35) is True)
    s2 = {'sells': 2, 'buys': 1, 'total': 4}
    check('MB5 2 فروش سیگنالی دیگر فروش نیست (اثر جانبی)', mod.is_sell_candidate(s2) is False)
    s3 = {'sells': 3, 'buys': 1, 'total': 4}
    check('MB6 3 فروش سیگنالی معتبر', mod.is_sell_candidate(s3) is True)
    agg = {'W': {'buys': 2, 'sells': 1, 'total': 4, 'best': (60, [])},
           'S': {'buys': 3, 'sells': 1, 'total': 4, 'best': (75, [])}}
    check('MB7 رتبه‌بندی فقط 3+', mod._rank_candidates(agg) == ['S'])
    return results


def deploy():
    bak = f'trader.py.bak.{time.strftime("%Y%m%d_%H%M")}'
    shutil.copy2(SRC, bak)
    os.replace(CAND, SRC)
    py_compile.compile(SRC, doraise=True)
    print(f'استقرار انجام شد: {SRC} (بکاپ: {bak})')


def main():
    build_candidate()
    try:
        py_compile.compile(CAND, doraise=True)
        print('COMPILE OK (کاندید)')
    except Exception as e:
        sys.exit(f'ABORT: کامپایل ناموفق: {e}')
    spec = importlib.util.spec_from_file_location('trader_candidate', CAND)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    results = run_tests(mod)
    n_fail = sum(1 for _, ok_ in results if not ok_)
    print(f'--- {len(results) - n_fail}/{len(results)} تست PASS ---')
    if n_fail:
        sys.exit(f'ABORT: {n_fail} تست FAIL — trader.py دست نخورده')
    if '--deploy' in sys.argv:
        deploy()
    else:
        print('کاندید آماده. برای استقرار: venv/bin/python apply_mintfs_fix.py --deploy')
    return 0


if __name__ == '__main__':
    sys.exit(main())
