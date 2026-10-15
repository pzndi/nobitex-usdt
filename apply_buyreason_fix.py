#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_buyreason_fix.py — ستون «علت رأی خرید» (O) در تب «معاملات»
+ اصلاح وضعیت کاندید به معیار واقعی (MIN_TFS/اکثریت — سازگار با G-rank).
فقط نمایشی؛ بدون --deploy هیچ فایلی عوض نمی‌شود.
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

E1_OLD = """        if sym in led.get('positions', {}):
            status = 'پوزیشن باز'
        elif sym in led.get('pending', set()):
            status = 'سفارش باز'
        else:
            status = 'کاندید خرید' if r[4] == 'خرید' else '—'"""
E1_NEW = """        sym_rows = [x for x in rows if len(x) > 4 and str(x[0]).strip().upper() == sym
                    and str(x[4]).strip() in ('خرید', 'فروش', 'خنثی')]
        n_buys = sum(1 for x in sym_rows if str(x[4]).strip() == 'خرید')
        n_sells = sum(1 for x in sym_rows if str(x[4]).strip() == 'فروش')
        if sym in led.get('positions', {}):
            status = 'پوزیشن باز'
        elif sym in led.get('pending', set()):
            status = 'سفارش باز'
        elif (n_buys >= MIN_TFS and n_buys >= (len(sym_rows) + 1) // 2
                and n_buys > n_sells):
            status = 'کاندید خرید'  # معیار واقعی (سازگار با MIN_TFS/G-rank)
        else:
            status = '—'
        reason = _buy_reason(sym_rows) if status == 'کاندید خرید' else '—'"""

E2_OLD = """        data.append([rank, sym, r[4], r[5], r[6], r[7], r[8],
                     r[2], r[2], r[10], r[9], rr, strat, status])"""
E2_NEW = """        data.append([rank, sym, r[4], r[5], r[6], r[7], r[8],
                     r[2], r[2], r[10], r[9], rr, strat, status, reason])"""

E3_OLD = "    data = data + [[''] * 14] * (n - len(data))"
E3_NEW = "    data = data + [[''] * 15] * (n - len(data))"

E4_OLD = "    ws.update(values=data, range_name=f'A4:N{3 + n}')"
E4_NEW = "    ws.update(values=data, range_name=f'A4:O{3 + n}')"

E5_OLD = """    ws.update(values=[['رتبه‌بندی لحظه‌ای برای سفارشگزاری — بازه: INTERVAL_SIGNALS_MIN در تب تنظیمات',
                       'به‌روزرسانی:', jnow()]], range_name='A1:C1')"""
E5_NEW = E5_OLD + """
    ws.update(values=[['علت رأی خرید (TFهای رأی‌داده + دلایل اندیکاتوری)']], range_name='O3')"""

H_OLD = "def write_ranking(sh, st, rows, led, bt_params=None):"
H_NEW = """def _buy_reason(sym_rows):
    # بهبود (G-reason): علت دقیق رأی خرید — TFهای خریدخور با قوتشان + یادداشت
    # اندیکاتوری بهترین TF (note = دلایل رأی‌های غیرخنثی همان TF)
    buys = [(str(x[1]).strip(), str(x[5]).strip(),
             str(x[11]).strip() if len(x) > 11 else '')
            for x in sym_rows if str(x[4]).strip() == 'خرید']
    if not buys:
        return '—'

    def _num(s):
        try:
            return int(float(s))
        except (TypeError, ValueError):
            return 0
    tf_list = ' + '.join(f'{tf}({st_}٪)' for tf, st_, _ in buys)
    best_note = max(buys, key=lambda b: _num(b[1]))[2]
    return (f'{len(buys)}/{len(sym_rows)} TF: {tf_list} | '
            + (best_note[:110] if best_note else 'بدون یادداشت'))


def write_ranking(sh, st, rows, led, bt_params=None):"""


def build_candidate():
    with open(SRC, encoding='utf-8') as f:
        text = f.read()
    if '_buy_reason' in text:
        sys.exit('ABORT: قبلاً patch شده')
    for tag, old in (('E1', E1_OLD), ('E2', E2_OLD), ('E3', E3_OLD),
                     ('E4', E4_OLD), ('E5', E5_OLD), ('H', H_OLD)):
        if text.count(old) != 1:
            sys.exit(f'ABORT [{tag}]: {text.count(old)} بار (انتظار ۱)')
    # ترتیب: اول جایگزینی‌ها، آخر درج helper
    for old, new in ((E1_OLD, E1_NEW), (E2_OLD, E2_NEW), (E3_OLD, E3_NEW),
                     (E4_OLD, E4_NEW), (E5_OLD, E5_NEW)):
        text = text.replace(old, new, 1)
    text = text.replace(H_OLD, H_NEW, 1)
    with open(CAND, 'w', encoding='utf-8') as f:
        f.write(text)
    print('E1-E5 + helper اعمال شد — کاندید:', CAND)


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
    _srow('OTH', '4h', 'خنثی', 50),
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

    tst_rows = [x for x in ROWS if x[0] == 'TST']
    r1 = mod._buy_reason(tst_rows)
    check('BR1 فرمت 3/4 و TFها', r1.startswith('3/4 TF:')
          and '15m(75٪)' in r1 and '1D(80٪)' in r1, r1)
    check('BR1 یادداشت بهترین TF (1D)', 'MACD' in r1 and 'RSI=28' in r1, r1)
    check('BR2 بدون خرید → —', mod._buy_reason([_srow('X', '1h', 'خنثی', 50)]) == '—')
    short = [_srow('X', '1h', 'خرید', 75)][:1]
    short[0] = short[0][:11]
    check('BR3 بدون ستون یادداشت → بدون یادداشت', 'بدون یادداشت' in mod._buy_reason(short))

    fws = FakeRankSheet()
    sh = types.SimpleNamespace(worksheet=lambda name: fws)
    st = types.SimpleNamespace(top_n=15, threshold_pct=60, interval_signals_min=3)
    led = {'positions': {}, 'pending': set()}
    mod.write_ranking(sh, st, ROWS, led, {})
    data_upd = next((v for rng, v in fws.updates if str(rng).startswith('A4:O')), None)
    check('INT1 بازه A4:O', data_upd is not None,
          str([rng for rng, _ in fws.updates]))
    if data_upd:
        tst_row = next((row for row in data_upd if len(row) > 14 and row[1] == 'TST'), None)
        oth_row = next((row for row in data_upd if len(row) > 14 and row[1] == 'OTH'), None)
        check('INT1 TST کاندید + علت', tst_row is not None
              and tst_row[13] == 'کاندید خرید' and tst_row[14].startswith('3/4 TF:'),
              str(tst_row))
        check('INT1 OTH (2/4) نه کاندید', oth_row is not None
              and oth_row[13] == '—' and oth_row[14] == '—', str(oth_row))
        check('INT1 همهٔ ردیف‌ها ۱۵ ستون', all(len(row) == 15 for row in data_upd))
    check('INT2 هدر O3', any(str(rng) == 'O3' for rng, _ in fws.updates))
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
        print('کاندید آماده. برای استقرار: venv/bin/python apply_buyreason_fix.py --deploy')
    return 0


if __name__ == '__main__':
    sys.exit(main())
