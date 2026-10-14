#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_slbuf_guard.py — بهبود ۱ (G-slbuf): گارد حداقل بافر SL در ورود
۱) helper _sl_buffer_skip (درج قبل از run)
۲) گارد در حلقهٔ خرید (درج قبل از G3.2 momentum guard)
بدون --deploy هیچ فایلی عوض نمی‌شود.
"""
import importlib.util
import os
import py_compile
import shutil
import sys
import time
import types

SRC = 'trader.py'
CAND = 'trader_candidate.py'

H_OLD = "def run(sh, st, rows, state=None):"
H_NEW = """def _sl_buffer_skip(a, st):
    # G-slbuf (بهبود ۱): (skip, buf, fill_est) — آیا ورود به‌خاطر بافر SL ریز رد شود؟
    # بافر = فاصلهٔ SL از قیمت fill تخمینی (limit_pullback: سیگنال×(1−پولبک) —
    # همان فرمول buy_one). شواهد: وقتی 1.5×ATR < پولبک، fill روی استاپ می‌نشیند —
    # XRP 0.07٪، SOL 0.13٪، ADA 0.31٪ → استاپ آنی؛ سطل [0–0.5٪): ۱۰/۱۶ استاپ.
    # دادهٔ ناقص → False (fail-open: گارد کیفیت است، نه ایمنی).
    row = (a.get('best') or (None, None))[1]
    if row is None or len(row) < 10:
        return False, None, None
    p = parse_price(row[2])
    sl = parse_price(row[9])
    if not (p and sl and p > 0 and sl < p):
        return False, None, None
    mkt = (st.order_type == 'market' and st.entry_mode != 'limit_pullback')
    fill = p if mkt else p * (1 - st.pullback_pct / 100.0)
    buf = (fill - sl) / fill * 100.0
    return (buf < 0.5), buf, fill


def run(sh, st, rows, state=None):"""

G_OLD = """        # G3.2 momentum guard (ORCA 1405/07/14: entry near top of +17% rally
        # -> loss): entry price must not be far above SMA20(1h)
        if st.pump_guard_pct > 0:"""
G_NEW = """        # G-slbuf (بهبود ۱): حداقل بافر SL نسبت به fill تخمینی — رد ورود وقتی
        # 1.5×ATR از پولبک کوچک‌تر است (fill روی استاپ). حداقل ۰.۵٪؛ قابل ارتقا
        # به کلید شیت پس از walk-forward
        _skip_buf, _buf, _fill_est = _sl_buffer_skip(a, st)
        if _skip_buf:
            log.info('skip buy %s: SL buffer %.2f%% < 0.5%% at est. fill %.6g',
                     sym, _buf, _fill_est)
            continue
        # G3.2 momentum guard (ORCA 1405/07/14: entry near top of +17% rally
        # -> loss): entry price must not be far above SMA20(1h)
        if st.pump_guard_pct > 0:"""


def build_candidate():
    with open(SRC, encoding='utf-8') as f:
        text = f.read()
    if '_sl_buffer_skip' in text:
        sys.exit('ABORT: قبلاً patch شده')
    if text.count(H_OLD) != 1:
        sys.exit(f'ABORT [helper]: نشانگر {text.count(H_OLD)} بار (انتظار ۱)')
    if text.count(G_OLD) != 1:
        sys.exit(f'ABORT [guard]: نشانگر {text.count(G_OLD)} بار (انتظار ۱)')
    text = text.replace(H_OLD, H_NEW, 1)
    text = text.replace(G_OLD, G_NEW, 1)
    with open(CAND, 'w', encoding='utf-8') as f:
        f.write(text)
    print('helper + guard درج شد — کاندید:', CAND)


def _st(order_type='limit', entry_mode='limit_pullback', pullback=1.0):
    return types.SimpleNamespace(order_type=order_type, entry_mode=entry_mode,
                                 pullback_pct=pullback)


def _agg(price, sl):
    try:
        tp = str(price * 1.1)
    except (TypeError, ValueError):
        tp = '—'
    row = ['SYM', '1h', str(price), 'صعودی', 'خرید', '80', '3', '1', '1',
           str(sl), tp, 'note']
    return {'buys': 3, 'sells': 1, 'total': 4, 'best': (80, row)}


def run_tests(mod):
    results = []

    def check(name, cond, extra=''):
        results.append((name, bool(cond)))
        print(('PASS' if cond else 'FAIL'), '-', name, ('| ' + extra) if (extra and not cond) else '')

    skip, buf, fill = mod._sl_buffer_skip(_agg(1.3740, 1.3594), _st())
    check('T1 XRP: رد شود', skip is True, str((skip, buf, fill)))
    check('T1 بافر ~0.06٪', buf is not None and 0.03 < buf < 0.09, str(buf))

    skip2, buf2, _ = mod._sl_buffer_skip(_agg(0.1843, 0.17354), _st())
    check('T2 BAT: مجاز (بافر ~4.9٪)', skip2 is False and buf2 > 4.5, str((skip2, buf2)))

    skip3, buf3, fill3 = mod._sl_buffer_skip(_agg(100.0, 99.6), _st('market', 'market'))
    check('T3a market بافر 0.4٪ → رد (fill=سیگنال)',
          skip3 is True and abs(fill3 - 100.0) < 1e-9, str((skip3, buf3, fill3)))
    skip3b, _, _ = mod._sl_buffer_skip(_agg(100.0, 99.0), _st('market', 'market'))
    check('T3b market بافر 1٪ → مجاز', skip3b is False)

    skip4, buf4, _ = mod._sl_buffer_skip(_agg(100.0, 101.0), _st())
    check('T4 SL≥قیمت → مجاز (fail-open)', skip4 is False and buf4 is None)

    skip5, _, _ = mod._sl_buffer_skip({'buys': 1, 'sells': 0, 'total': 4, 'best': None}, _st())
    check('T5 بدون best → مجاز', skip5 is False)

    skip6, buf6, _ = mod._sl_buffer_skip(_agg(100.0, 99.7), _st(pullback=0.0))
    check('T6 پولبک ۰ با بافر 0.3٪ → رد', skip6 is True and abs(buf6 - 0.3) < 0.01)

    skip7, _, _ = mod._sl_buffer_skip(_agg('x', 'y'), _st())
    check('T7 دادهٔ خراب → مجاز (fail-open)', skip7 is False)
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
        print('کاندید آماده. برای استقرار: venv/bin/python apply_slbuf_guard.py --deploy')
    return 0


if __name__ == '__main__':
    sys.exit(main())
