#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_volsize_fix.py — گزینهٔ الف (G-volsize) + گزینهٔ ب (G-bandcap)
الف: size = min(ORDER_SIZE, RISK_TARGET ÷ عرض استاپ) — برابرسازی ریسک دلاری
ب: رد ورود اگر عرض استاپ > MAX_SL_BAND_PCT — فیلتر دُم پرنوسان
عرض = 1.5×ATR ÷ fill تخمینی + 0.5٪ اسلیپیج (ATR از ردیف، بدون API)
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

E1_OLD = """    vol = math.floor((st.order_size_usdt / price) * 1e8) / 1e8
    if vol <= 0:
        return
    amount = round(st.order_size_usdt, 2)"""
E1_NEW = """    # گزینهٔ الف (G-volsize): vol-targeted sizing — cap-style
    _size = _eff_order_usdt(row, st)
    vol = math.floor((_size / price) * 1e8) / 1e8
    if vol <= 0:
        return
    amount = round(_size, 2)"""

E3_OLD = """        _skip_buf, _buf, _fill_est = _sl_buffer_skip(a, st)
        if _skip_buf:
            log.info('skip buy %s: SL buffer %.2f%% < 0.5%% at est. fill %.6g',
                     sym, _buf, _fill_est)
            continue
        # G3.2 momentum guard (ORCA 1405/07/14: entry near top of +17% rally"""
E3_NEW = """        _skip_buf, _buf, _fill_est = _sl_buffer_skip(a, st)
        if _skip_buf:
            log.info('skip buy %s: SL buffer %.2f%% < 0.5%% at est. fill %.6g',
                     sym, _buf, _fill_est)
            continue
        # گزینهٔ ب (G-bandcap): سقف عرض استاپ — رد دُم پرنوسان (STRK 8.8٪،
        # WAL 11.1٪ → رد؛ BAT 6.3٪ → عبور با سایزِ کاهش‌یافته از گزینهٔ الف)
        _w_pct = _sl_width_pct(row, st)
        if _w_pct is not None and _w_pct > MAX_SL_BAND_PCT:
            log.info('skip buy %s: SL band %.1f%% > %.1f%% (high-volatility tail)',
                     sym, _w_pct, MAX_SL_BAND_PCT)
            continue
        # G3.2 momentum guard (ORCA 1405/07/14: entry near top of +17% rally"""

E2_OLD = "def buy_one(st, ws_t, client, dry, sym, a, price, led, coid=None):"
E2_NEW = """RISK_TARGET_USDT = 0.50  # گزینهٔ الف (G-volsize): سقف ریسک دلاری هر معامله — قابل ارتقا به کلید شیت
MAX_SL_BAND_PCT = 8.0    # گزینهٔ ب (G-bandcap): سقف عرض استاپ ٪ — فیلتر دُم پرنوسان


def _sl_width_pct(row, st):
    \"\"\"عرض استاپ تخمینی (٪ از fill): ضریبSL×ATR ÷ fill + اسلیپیج ۰.۵٪.
    ATR از ردیف ((سیگنال−SL)÷ضریب)؛ fill تخمینی با پولبک G-vpull.
    دادهٔ ناقص → None (fail-open).\"\"\"
    try:
        p = parse_price(row[2])
        sl = parse_price(row[9])
        slm = getattr(st, 'sl_atr_mult', 0) or 0
        if p and sl and slm > 0 and 0 < sl < p:
            atr = (p - sl) / slm
            pull = _eff_pullback_pct(row, st) / 100.0
            fill_est = p * (1 - pull)
            if fill_est > 0:
                return (slm * atr) / fill_est * 100.0 + 0.5
    except Exception:
        pass
    return None


def _eff_order_usdt(row, st):
    \"\"\"گزینهٔ الف (cap-style): min(ORDER_SIZE, RISK_TARGET ÷ عرض).
    دادهٔ ناقص → ORDER_SIZE (رفتار فعلی).\"\"\"
    w = _sl_width_pct(row, st)
    if w and w > 0.5:
        return min(st.order_size_usdt, RISK_TARGET_USDT / (w / 100.0))
    return st.order_size_usdt


def buy_one(st, ws_t, client, dry, sym, a, price, led, coid=None):"""


def build_candidate():
    with open(SRC, encoding='utf-8') as f:
        text = f.read()
    if 'G-volsize' in text:
        sys.exit('ABORT: قبلاً patch شده')
    for tag, old in (('E1', E1_OLD), ('E3', E3_OLD), ('E2', E2_OLD)):
        if text.count(old) != 1:
            sys.exit(f'ABORT [{tag}]: {text.count(old)} بار (انتظار ۱)')
    # ترتیب: جایگزینی‌ها اول، درج helper آخر (درس G-rank)
    text = text.replace(E1_OLD, E1_NEW, 1)
    text = text.replace(E3_OLD, E3_NEW, 1)
    text = text.replace(E2_OLD, E2_NEW, 1)
    with open(CAND, 'w', encoding='utf-8') as f:
        f.write(text)
    print('E1/E3 + helperهای الف/ب اعمال شد — کاندید:', CAND)


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


def _row(sl):
    return ['TST', '1h', '1.00', 'صعودی', 'خرید', '75', '3', '1', '1',
            str(sl), '1.10', 'note']


def run_tests(mod):
    results = []

    def check(name, cond, extra=''):
        results.append((name, bool(cond)))
        print(('PASS' if cond else 'FAIL'), '-', name, ('| ' + extra) if (extra and not cond) else '')

    # S-مانند: ATR ۲.۵٪ → عرض ~۴.۳
    w_s = mod._sl_width_pct(_row(0.9625), _st())
    check('W1 S-مانند: عرض ~۴.۳٪', w_s is not None and 4.2 < w_s < 4.4, str(w_s))
    # BAT-مانند: ATR ۳.۸٪ → عرض ~۶.۳
    w_b = mod._sl_width_pct(_row(0.943), _st())
    check('W2 BAT-مانند: عرض ~۶.۳٪', w_b is not None and 6.2 < w_b < 6.4, str(w_b))
    # STRK-مانند: ATR ۵.۴٪ → عرض ~۸.۸ > سقف
    w_k = mod._sl_width_pct(_row(0.919), _st())
    check('W3 STRK-مانند: رد توسط B (>۸٪)',
          w_k is not None and w_k > mod.MAX_SL_BAND_PCT, str(w_k))
    # WAL-مانند: ATR ۶.۹٪ → عرض ~۱۱.۱ > سقف
    w_w = mod._sl_width_pct(_row(0.8965), _st())
    check('W4 WAL-مانند: رد توسط B', w_w is not None and w_w > mod.MAX_SL_BAND_PCT, str(w_w))
    # سایزها
    check('W5 S-مانند: سایز = ۱۰ (سقف سرمایه)',
          abs(mod._eff_order_usdt(_row(0.9625), _st()) - 10.0) < 1e-9)
    s_b = mod._eff_order_usdt(_row(0.943), _st())
    check('W6 BAT-مانند: سایز ~۷.۹', 7.8 < s_b < 8.0, str(s_b))
    check('W7 fail-open: دادهٔ ناقص → ۱۰',
          mod._sl_width_pct(_row(1.05), _st()) is None
          and abs(mod._eff_order_usdt(_row(1.05), _st()) - 10.0) < 1e-9)
    # buy_one integration — BAT-مانند: سایز داینامیک
    fc = FakeClient()
    ws = FakeSheet()
    a = {'buys': 3, 'sells': 1, 'total': 4, 'best': (75, _row(0.943))}
    led = {'positions': {}, 'rows': [], 'pending': set(), 'pending_sells': set(),
           'daily_count': 0, 'dry_net_spent': 0.0}
    mod.buy_one(_st(), ws, fc, False, 'TST', a, 1.00, led)
    check('W8 buy_one BAT-مانند: vol ~۷.۹ و limit ~۰.۹۸۱',
          fc.place_calls and 7.8 < fc.place_calls[0][3] < 8.0
          and abs(fc.place_calls[0][2] - 0.981) < 1e-6, str(fc.place_calls))
    check('W9 amount ثبت‌شده = سایز داینامیک (~۷.۹۲)',
          ws.rows and abs(float(ws.rows[-1][7]) - round(0.5 / (w_b / 100.0), 2)) < 0.02,
          str(ws.rows and ws.rows[-1][7]))
    # buy_one S-مانند: سایز کامل
    fc2 = FakeClient()
    a2 = {'buys': 3, 'sells': 1, 'total': 4, 'best': (75, _row(0.9625))}
    mod.buy_one(_st(), FakeSheet(), fc2, False, 'TST', a2, 1.00, led)
    check('W10 buy_one S-مانند: vol = ۱۰',
          fc2.place_calls and abs(fc2.place_calls[0][3] - 10.0) < 1e-6, str(fc2.place_calls))
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
        print('کاندید آماده. برای استقرار: venv/bin/python apply_volsize_fix.py --deploy')
    return 0


if __name__ == '__main__':
    sys.exit(main())
