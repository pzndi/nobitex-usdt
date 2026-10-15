#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_tfagg_fix.py — ستون P «رأی TFها» در تب «معاملات» (لایهٔ تجمیع همیشه مرئی)
از همان n_buys/n_sells وضعیت. صرفاً نمایشی؛ بدون --deploy هیچ فایلی عوض نمی‌شود.
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

E1_OLD = "        reason = _buy_reason(sym_rows) if status == 'کاندید خرید' else '—'"
E1_NEW = E1_OLD + """
        tf_agg = f'خرید {n_buys}/{len(sym_rows)} · فروش {n_sells}/{len(sym_rows)}'"""

E2_OLD = """        data.append([rank, sym, r[4], r[5], r[6], r[7], r[8],
                     r[2], r[2], r[10], r[9], rr, strat, status, reason])"""
E2_NEW = """        data.append([rank, sym, r[4], r[5], r[6], r[7], r[8],
                     r[2], r[2], r[10], r[9], rr, strat, status, reason, tf_agg])"""

E3_OLD = "    data = data + [[''] * 15] * (n - len(data))"
E3_NEW = "    data = data + [[''] * 16] * (n - len(data))"

E4_OLD = "    ws.update(values=data, range_name=f'A4:O{3 + n}')"
E4_NEW = "    ws.update(values=data, range_name=f'A4:P{3 + n}')"

E5_OLD = "    ws.update(values=[['علت رأی خرید (TFهای رأی‌داده + دلایل اندیکاتوری)']], range_name='O3')"
E5_NEW = E5_OLD + """
    ws.update(values=[['رأی TFها (خرید/فروش)']], range_name='P3')"""


def build_candidate():
    with open(SRC, encoding='utf-8') as f:
        text = f.read()
    if 'tf_agg' in text:
        sys.exit('ABORT: قبلاً patch شده')
    for tag, old in (('E1', E1_OLD), ('E2', E2_OLD), ('E3', E3_OLD),
                     ('E4', E4_OLD), ('E5', E5_OLD)):
        if text.count(old) != 1:
            sys.exit(f'ABORT [{tag}]: {text.count(old)} بار (انتظار ۱)')
    for old, new in ((E1_OLD, E1_NEW), (E2_OLD, E2_NEW), (E3_OLD, E3_NEW),
                     (E4_OLD, E4_NEW), (E5_OLD, E5_NEW)):
        text = text.replace(old, new, 1)
    with open(CAND, 'w', encoding='utf-8') as f:
        f.write(text)
    print('E1-E5 اعمال شد — کاندید:', CAND)


def _srow(sym, tf, sig, strength, note=''):
    return [sym, tf, '1.05', 'صعودی' if sig == 'خرید' else '—', sig, str(strength),
            '3' if sig == 'خرید' else '0', '0', '1', '0.95', '1.15', note]


ROWS = [
    _srow('TST', '15m', 'خرید', 75, 'SMA20 بالاتر از SMA50؛ MACD بالای خط سیگنال'),
    _srow('TST', '1h', 'خنثی', 50),
    _srow('TST', '4h', 'خرید', 75, 'EMA9 بالاتر از EMA21'),
    _srow('TST', '1D', 'خرید', 80, 'SMA20 بالاتر از SMA50؛ MACD بالای خط سیگنال؛ RSI=28'),
    _srow('OTH', '15m', 'خرید', 75, 'SMA20 بالاتر از SMA50'),
    _srow('OTH', '1h', 'خنثی', 50),
    _srow('OTH', '4h', 'فروش', 75),
    _srow('OTH', '1D', 'خرید', 75, 'EMA9 بالاتر از EMA21'),
]


class FakeRankSheet:
    def __init__(self):
        self.updates = []

    def update(self, values=None, range_name=None):
        self.updates.append((range_name, values))


def run_tests(mod):
    results = []

    def check(name, cond, extra=''):
        results.append((name, bool(cond)))
        print(('PASS' if cond else 'FAIL'), '-', name, ('| ' + extra) if (extra and not cond) else '')

    fws = FakeRankSheet()
    sh = types.SimpleNamespace(worksheet=lambda name: fws)
    st = types.SimpleNamespace(top_n=15, threshold_pct=60, interval_signals_min=3)
    led = {'positions': {}, 'pending': set()}
    mod.write_ranking(sh, st, ROWS, led, {})
    data_upd = next((v for rng, v in fws.updates if str(rng).startswith('A4:P')), None)
    check('TA1 بازه A4:P', data_upd is not None, str([rng for rng, _ in fws.updates]))
    if data_upd:
        tst = next((row for row in data_upd if len(row) > 15 and row[1] == 'TST'), None)
        oth = next((row for row in data_upd if len(row) > 15 and row[1] == 'OTH'), None)
        check('TA2 TST: «خرید 3/4 · فروش 0/4»', tst is not None
              and tst[15] == 'خرید 3/4 · فروش 0/4', str(tst and tst[15]))
        check('TA3 OTH: «خرید 2/4 · فروش 1/4»', oth is not None
              and oth[15] == 'خرید 2/4 · فروش 1/4', str(oth and oth[15]))
        check('TA4 همهٔ ردیف‌ها ۱۶ ستون', all(len(row) == 16 for row in data_upd))
        check('TA5 رگرسیون: TST همچنان کاندید+علت', tst is not None
              and tst[13] == 'کاندید خرید' and tst[14].startswith('3/4 TF:'))
        check('TA6 رگرسیون: OTH همچنان رد', oth is not None
              and oth[13] == '—' and oth[14] == '—')
    check('TA7 هدر P3', any(str(rng) == 'P3' for rng, _ in fws.updates))
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
        print('کاندید آماده. برای استقرار: venv/bin/python apply_tfagg_fix.py --deploy')
    return 0


if __name__ == '__main__':
    sys.exit(main())
