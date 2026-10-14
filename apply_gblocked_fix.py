#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_gblocked_fix.py — P0-C: بررسی «استاپ در حال پرشدن» قبل از لغو OCO (آینهٔ Fix-4)
درج یک بلوک ۱۱خطی قبل از old_ids در apply_trailing. بررسی موجود پس از لغو دست‌نخورده
می‌ماند (هندلر race). بدون --deploy هیچ فایلی عوض نمی‌شود.
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

OLD_ANCHOR = ("            if client is None or (p.get('real_volume') or 0) <= 1e-12:\n"
              "                continue\n"
              "            old_ids = [clean_oid(x) for x in str(oco_row[1][10]).split('|'")

INSERT = """            # G-blocked-fix (P0-C): بررسی «استاپ در حال پرشدن» قبل از لغو OCO —
            # آینهٔ واقعی Fix-4. قبلاً این بررسی بعد از لغو انجام می‌شد → استاپِ در حال
            # اجرا قطع می‌شد و باقیمانده بدون OCO ردیابی‌شده می‌ماند (W/RSR/S در ۱۲ اکتبر)
            _av0 = currency_available(client, sym)
            _tot0 = currency_available(client, sym, use_active=False)
            _rv0 = p.get('real_volume') or 0
            if (_av0 is not None and _tot0 is not None
                    and _rv0 > 1e-12 and _av0 < _rv0 * 0.5 and _tot0 >= _rv0 * 0.5):
                log.info('G-blocked-fix: OCO rebuild deferred BEFORE cancel for %s '
                         '(exchange stop filling: active=%.6f total=%.6f)',
                         sym, _av0, _tot0)
                continue
"""

NEW_ANCHOR = ("            if client is None or (p.get('real_volume') or 0) <= 1e-12:\n"
              "                continue\n"
              + INSERT +
              "            old_ids = [clean_oid(x) for x in str(oco_row[1][10]).split('|'")


def build_candidate():
    with open(SRC, encoding='utf-8') as f:
        text = f.read()
    if text.count(OLD_ANCHOR) != 1:
        sys.exit(f'ABORT: لنگر {text.count(OLD_ANCHOR)} بار یافت شد (انتظار: ۱)')
    if 'G-blocked-fix' in text:
        sys.exit('ABORT: قبلاً patch شده')
    with open(CAND, 'w', encoding='utf-8') as f:
        f.write(text.replace(OLD_ANCHOR, NEW_ANCHOR, 1))
    print(f'درج {len(INSERT.splitlines())} خط قبل از old_ids — کاندید: {CAND}')


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
        self.cancel_calls = []
        self.oco_calls = []

    def place_order(self, otype, sym, price, vol, is_market, client_order_id=None):
        return (200, {'status': 'ok', 'order': {'id': 555}})

    def place_oco_sell(self, sym, vol, tp, sl, stop_limit=None):
        self.oco_calls.append((sym, float(vol), float(tp), float(sl)))
        return (200, {'status': 'ok', 'order': {'id': 11},
                      'orders': [{'id': 11}, {'id': 12}]})

    def cancel_order(self, oid):
        self.cancel_calls.append(str(oid))
        return (200, {'status': 'ok', 'updatedStatus': 'Canceled'})


def _tr_st():
    return types.SimpleNamespace(trail_enabled=True, trail_activation_pct=0.0,
                                 trail_atr_mult=0, trail_distance_pct=0.5,
                                 partial_exit_pct=0, partial_exit_trigger=2.0)


def _rb_led():
    rows = [
        (10, ['1405/07/22 10:00', 'TST', 'خرید', '1h', 'رأی خرید', '1.0', '100', '100.0',
              '0.90', '1.20', '111', 'پر شد', 'm']),
        (11, ['1405/07/22 10:05', 'TST', 'فروش', '', 'OCO حد سود/ضرر بومی صرافی',
              '1.20', '100', '120.0', '0.90', '1.20', '777|888', 'ثبت‌شده',
              'OCO: TP=1.2 | SL=0.9']),
    ]
    return {'positions': {'TST': {'volume': 100.0, 'sim_volume': 0.0,
                                  'real_volume': 100.0, 'entry_price': 1.0,
                                  'sl': 0.90, 'tp': 1.20}},
            'pending': set(), 'pending_sells': {'TST'}, 'rows': rows,
            'daily_count': 0, 'dry_net_spent': 0.0}


def run_tests(mod):
    results = []

    def check(name, cond, extra=''):
        results.append((name, bool(cond)))
        print(('PASS' if cond else 'FAIL'), '-', name, ('| ' + extra) if (extra and not cond) else '')

    # TB1: استاپ در حال پرشدن → تعویق قبل از هر لغویی
    mod.currency_available = lambda client, cur, use_active=True: (0.004 if use_active else 100.0)
    fc = FakeClient()
    ws = FakeSheet()
    led = _rb_led()
    mod.apply_trailing(_tr_st(), ws, led, {'TST': 1.05}, fc)
    check('TB1 بدون لغو', fc.cancel_calls == [], str(fc.cancel_calls))
    check('TB1 بدون OCO جدید', fc.oco_calls == [], str(fc.oco_calls))
    check('TB1 ردیف OCO دست‌نخورده', not any(r == 11 and c == 12 for r, c, v in ws.cells))
    check('TB1 SL پوزیشن تغییر نکرد', abs(led['positions']['TST']['sl'] - 0.90) < 1e-9)

    # TB2: وضعیت سالم → rebuild کامل (رفتار موجود حفظ شود)
    mod.currency_available = lambda client, cur, use_active=True: 100.0
    fc2 = FakeClient()
    ws2 = FakeSheet()
    led2 = _rb_led()
    mod.apply_trailing(_tr_st(), ws2, led2, {'TST': 1.05}, fc2)
    check('TB2 لغو هر دو پایه', fc2.cancel_calls == ['777', '888'], str(fc2.cancel_calls))
    check('TB2 OCO جدید با SL متحرک', len(fc2.oco_calls) == 1
          and abs(fc2.oco_calls[0][3] - 1.04475) < 1e-6, str(fc2.oco_calls))
    check('TB2 ردیف قدیمی لغو شد', any(r == 11 and c == 12 for r, c, v in ws2.cells))
    check('TB2 ردیف OCO متحرک ثبت شد', any('OCO متحرک' in str(r[4]) for r in ws2.rows))
    check('TB2 SL پوزیشن به‌روز شد', abs(led2['positions']['TST']['sl'] - 1.04475) < 1e-6)

    # TB3: race — استاپ بین بررسیِ قبل از لغو و خودِ لغو شروع به پر شدن کند
    state = {'blocked': False}

    def ca3(client, cur, use_active=True):
        if use_active:
            return 0.004 if state['blocked'] else 100.0
        return 100.0

    mod.currency_available = ca3
    fc3 = FakeClient()
    orig_cancel = fc3.cancel_order

    def cancel_flip(oid):
        state['blocked'] = True
        return orig_cancel(oid)

    fc3.cancel_order = cancel_flip
    led3 = _rb_led()
    mod.apply_trailing(_tr_st(), FakeSheet(), led3, {'TST': 1.05}, fc3)
    check('TB3 race: لغو انجام شد', fc3.cancel_calls == ['777', '888'])
    check('TB3 race: بازثبت به چرخهٔ بعد موکول (هندلر موجود)', fc3.oco_calls == [])

    return results


def deploy():
    bak = f'trader.py.bak.{time.strftime("%Y%m%d_%H%M")}'
    shutil.copy2(SRC, bak)
    os.replace(CAND, SRC)
    py_compile.compile(SRC, doraise=True)
    print(f'استقرار انجام شد: {SRC} (بکاپ: {bak})')


def main():
    if not os.path.exists(SRC):
        sys.exit('ABORT: trader.py یافت نشد')
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
        print('کاندید آماده. برای استقرار: venv/bin/python apply_gblocked_fix.py --deploy')
    return 0


if __name__ == '__main__':
    sys.exit(main())
