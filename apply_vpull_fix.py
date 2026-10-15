#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_vpull_fix.py — بهبود ۳ (G-vpull): پولبک volatility-based
helper _eff_pullback_pct = clamp(0.5×ATR٪, 0.3, 2.0) — ATR از ردیف.
سه نقطهٔ مصرف: buy_one، UMP-retry، تخمین fill گارد G-slbuf.
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

E1_OLD = """    _is_market = (st.order_type == 'market' and st.entry_mode != 'limit_pullback')
    _limit_price = price
    if not _is_market and st.entry_mode == 'limit_pullback' and st.pullback_pct > 0:
        _limit_price = price * (1 - st.pullback_pct / 100.0)"""
E1_NEW = """    _is_market = (st.order_type == 'market' and st.entry_mode != 'limit_pullback')
    # بهبود ۳ (G-vpull): عمق پولبک volatility-based (نه ثابت شیت)
    _pull_pct = _eff_pullback_pct(row, st) if (not _is_market and row) else st.pullback_pct
    _limit_price = price
    if not _is_market and st.entry_mode == 'limit_pullback' and _pull_pct > 0:
        _limit_price = price * (1 - _pull_pct / 100.0)"""

E2_OLD = "                    _limit = _fresh * (1 - st.pullback_pct / 100.0)"
E2_NEW = "                    _limit = _fresh * (1 - _pull_pct / 100.0)"

E3_OLD = """    mkt = (st.order_type == 'market' and st.entry_mode != 'limit_pullback')
    fill = p if mkt else p * (1 - st.pullback_pct / 100.0)"""
E3_NEW = """    mkt = (st.order_type == 'market' and st.entry_mode != 'limit_pullback')
    _pp = st.pullback_pct if mkt else _eff_pullback_pct(row, st)
    fill = p if mkt else p * (1 - _pp / 100.0)"""

H_OLD = "def run(sh, st, rows, state=None):"
H_NEW = """def _eff_pullback_pct(row, st):
    # بهبود ۳ (G-vpull): پولبک volatility-based — clamp(0.5×ATR٪, 0.3٪, 2.0٪).
    # ATR از خود ردیف: (سیگنال−SL)/ضریب — سازگار با G-fillanchor. دادهٔ ناقص →
    # st.pullback_pct (رفتار فعلی؛ fail-open).
    try:
        p = parse_price(row[2])
        sl = parse_price(row[9])
        slm = getattr(st, 'sl_atr_mult', 0) or 0
        if p and sl and slm > 0 and 0 < sl < p:
            atr_pct = (p - sl) / slm / p * 100.0
            return min(max(0.5 * atr_pct, 0.3), 2.0)
    except Exception:
        pass
    return st.pullback_pct


def run(sh, st, rows, state=None):"""


def build_candidate():
    with open(SRC, encoding='utf-8') as f:
        text = f.read()
    if 'G-vpull' in text:
        sys.exit('ABORT: قبلاً patch شده')
    for tag, old in (('E1', E1_OLD), ('E2', E2_OLD), ('E3', E3_OLD), ('H', H_OLD)):
        if text.count(old) != 1:
            sys.exit(f'ABORT [{tag}]: {text.count(old)} بار (انتظار ۱)')
    # ترتیب: اول جایگزینی‌ها، آخر درج helper (درس G-rank)
    text = text.replace(E1_OLD, E1_NEW, 1)
    text = text.replace(E2_OLD, E2_NEW, 1)
    text = text.replace(E3_OLD, E3_NEW, 1)
    text = text.replace(H_OLD, H_NEW, 1)
    with open(CAND, 'w', encoding='utf-8') as f:
        f.write(text)
    print('E1-E3 + helper اعمال شد — کاندید:', CAND)


class FakeSheet:
    def __init__(self):
        self.rows = []
        self.cells = []

    def append_row(self, row):
        self.rows.append([str(x) for x in row])
        return len(self.rows) + 3

    def update(self, values=None, range_name=None):
        pass

    def update_cell(self, row, col, val):
        self.cells.append((row, col, val))


class FakeClient:
    def __init__(self):
        self.place_calls = []

    def place_order(self, otype, sym, price, vol, is_market, client_order_id=None):
        self.place_calls.append((otype, sym, float(price), float(vol), bool(is_market)))
        return (200, {'status': 'ok', 'order': {'id': 555}})

    def place_oco_sell(self, sym, vol, tp, sl, stop_limit=None):
        return (200, {'status': 'ok', 'order': {'id': 11}, 'orders': [{'id': 11}, {'id': 12}]})


def _st():
    return types.SimpleNamespace(order_type='limit', entry_mode='limit_pullback',
                                 pullback_pct=1.0, sl_atr_mult=1.5,
                                 use_exchange_oco=False, order_size_usdt=10.0)


def _row(price, sl):
    return ['TST', '1h', str(price), 'صعودی', 'خرید', '80', '3', '1', '1',
            str(sl), str(price * 1.1), 'note']


def run_tests(mod):
    results = []

    def check(name, cond, extra=''):
        results.append((name, bool(cond)))
        print(('PASS' if cond else 'FAIL'), '-', name, ('| ' + extra) if (extra and not cond) else '')

    # VP1: ATR بالا (۹.۵٪) → سقف ۲٪
    check('VP1 ATR بالا → پولبک ۲.۰ (سقف)',
          abs(mod._eff_pullback_pct(_row(1.05, 0.90), _st()) - 2.0) < 1e-9,
          str(mod._eff_pullback_pct(_row(1.05, 0.90), _st())))

    # VP2: ATR ۲٪ → ۱.۰٪ (معادل امروز)
    sl2 = 1.05 - 1.5 * 0.021
    check('VP2 ATR ۲٪ → پولبک ۱.۰ (معادل امروز)',
          abs(mod._eff_pullback_pct(_row(1.05, sl2), _st()) - 1.0) < 1e-6)

    # VP3: ATR ریز → کف ۰.۳
    sl3 = 1.05 - 1.5 * 0.001
    check('VP3 ATR ریز → پولبک ۰.۳ (کف)',
          abs(mod._eff_pullback_pct(_row(1.05, sl3), _st()) - 0.3) < 1e-6)

    # VP4: دادهٔ ناقص → fallback شیت
    check('VP4 SL≥قیمت → fallback ۱.۰',
          abs(mod._eff_pullback_pct(_row(1.05, 1.06), _st()) - 1.0) < 1e-9)

    # VP5: buy_one با ATR بالا → limit در −۲٪
    fc = FakeClient()
    a = {'buys': 3, 'sells': 1, 'total': 4, 'best': (80, _row(1.05, 0.90))}
    led = {'positions': {}, 'rows': [], 'pending': set(), 'pending_sells': set(),
           'daily_count': 0, 'dry_net_spent': 0.0}
    mod.buy_one(_st(), FakeSheet(), fc, False, 'TST', a, 1.05, led)
    check('VP5 buy_one → limit در ۱.۰۲۹ (−۲٪)',
          fc.place_calls and abs(fc.place_calls[0][2] - 1.029) < 1e-6,
          str(fc.place_calls))

    # VP6: G-slbuf با ATR ریز → پولبک ۰.۳٪ → بافر سالم می‌ماند
    # (با پولبک ثابت ۱٪ بافر منفی می‌شد؛ با fillanchor سطح‌ها از fill درست می‌شوند)
    a6 = {'buys': 3, 'sells': 1, 'total': 4, 'best': (80, _row(1.05, 1.040))}
    skip6, buf6, _ = mod._sl_buffer_skip(a6, _st())
    check('VP6 ATR ریز + پولبک داینامیک → بدون رد', skip6 is False and buf6 is not None,
          str((skip6, buf6)))

    # VP7: مسیر market → fallback شیت در slbuf
    st7 = types.SimpleNamespace(order_type='market', entry_mode='market',
                                pullback_pct=1.0, sl_atr_mult=1.5)
    a7 = {'buys': 3, 'sells': 1, 'total': 4, 'best': (80, _row(1.05, 1.047))}
    skip7, buf7, fill7 = mod._sl_buffer_skip(a7, st7)
    check('VP7 market → fill=سیگنال', abs(fill7 - 1.05) < 1e-9)
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
        print('کاندید آماده. برای استقرار: venv/bin/python apply_vpull_fix.py --deploy')
    return 0


if __name__ == '__main__':
    sys.exit(main())
