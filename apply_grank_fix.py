#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_grank_fix.py — بهبود ۴ (G-rank): اولویت خرید بر اساس کیفیت سیگنال
۱) helper _rank_candidates (درج قبل از run)
۲) cands = _rank_candidates(agg) در run
فقط ترتیب تلاش عوض می‌شود — بدون --deploy هیچ فایلی عوض نمی‌شود.
"""
import importlib.util
import os
import py_compile
import shutil
import sys
import time

SRC = 'trader.py'
CAND = 'trader_candidate.py'

E1_OLD = ("    cands = [s for s, a in agg.items() if is_buy_candidate(a)]\n"
          "    log.info('کاندیدهای خرید این اجرا: %s', '، '.join(cands) if cands else 'هیچ')")
E1_NEW = ("    cands = _rank_candidates(agg)\n"
          "    log.info('کاندیدهای خرید این اجرا: %s', '، '.join(cands) if cands else 'هیچ')")

E2_OLD = "def run(sh, st, rows, state=None):"
E2_NEW = """def _rank_candidates(agg):
    # بهبود ۴ (G-rank): اولویت خرید = کیفیت سیگنال — اکثریت TF (نزولی)، سپس
    # قوت بهترین TF (نزولی)؛ برابرها → ترتیب universe/نقدشوندگی (sort پایدار).
    # تا پیش از این ترتیب خرید = ترتیب universe بود و «رتبه‌بندی برای سفارشگزاری»
    # صرفاً نمایشی بود (ممیزی ۱۴۰۵/۰۷/۲۲ — cands بدون هیچ sort).
    cands = [s for s, a in agg.items() if is_buy_candidate(a)]
    cands.sort(key=lambda s: (-agg[s]['buys'],
                              -(agg[s]['best'][0] if agg[s]['best'] else 0)))
    return cands


def run(sh, st, rows, state=None):"""


def build_candidate():
    with open(SRC, encoding='utf-8') as f:
        text = f.read()
    if '_rank_candidates' in text:
        sys.exit('ABORT: قبلاً patch شده')
    if text.count(E1_OLD) != 1:
        sys.exit(f'ABORT [E1]: {text.count(E1_OLD)} بار (انتظار ۱)')
    if text.count(E2_OLD) != 1:
        sys.exit(f'ABORT [E2]: {text.count(E2_OLD)} بار (انتظار ۱)')
    text = text.replace(E1_OLD, E1_NEW, 1)
    text = text.replace(E2_OLD, E2_NEW, 1)
    with open(CAND, 'w', encoding='utf-8') as f:
        f.write(text)
    print('helper + جایگزینی cands اعمال شد — کاندید:', CAND)


def _agg_entry(buys, sells, total, strength=60):
    return {'buys': buys, 'sells': sells, 'total': total,
            'best': (strength, ['SYM', '1h', '1.0', 'صعودی', 'خرید',
                                str(strength), str(buys), str(sells), '0',
                                '0.95', '1.1', 'n'])}


def run_tests(mod):
    results = []

    def check(name, cond, extra=''):
        results.append((name, bool(cond)))
        print(('PASS' if cond else 'FAIL'), '-', name, ('| ' + extra) if (extra and not cond) else '')

    agg1 = {'B': _agg_entry(2, 1, 4), 'A': _agg_entry(3, 1, 4), 'C': _agg_entry(4, 0, 4)}
    check('RK1 اکثریت نزولی حاکم است', mod._rank_candidates(agg1) == ['C', 'A', 'B'],
          str(mod._rank_candidates(agg1)))

    agg2 = {'B': _agg_entry(3, 1, 4, strength=80), 'A': _agg_entry(3, 1, 4, strength=60)}
    check('RK2 تساوی اکثریت → قوت نزولی', mod._rank_candidates(agg2) == ['B', 'A'],
          str(mod._rank_candidates(agg2)))

    agg3 = {'A': _agg_entry(3, 1, 4, strength=80), 'B': _agg_entry(3, 1, 4, strength=80)}
    check('RK3 تساوی کامل → ترتیب universe (پایدار)', mod._rank_candidates(agg3) == ['A', 'B'])

    agg4 = {'X': _agg_entry(1, 3, 4), 'A': _agg_entry(3, 1, 4), 'Y': _agg_entry(2, 2, 4)}
    check('RK4 غیرکاندیدها فیلتر می‌شوند', mod._rank_candidates(agg4) == ['A'])

    agg5 = {'A': {'buys': 2, 'sells': 1, 'total': 4, 'best': None}}
    check('RK5 best=None بدون کرش', mod._rank_candidates(agg5) == ['A'])

    check('RK6 ورودی خالی', mod._rank_candidates({}) == [])
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
        print('کاندید آماده. برای استقرار: venv/bin/python apply_grank_fix.py --deploy')
    return 0


if __name__ == '__main__':
    sys.exit(main())
