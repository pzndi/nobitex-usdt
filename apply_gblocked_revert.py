#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_gblocked_revert.py — حذف گارد pre-cancel گارد G-blocked-fix (رفع رگرسیون)
شاهد زنده (2026-10-14 16:08:17): شرط کیف‌پول pre-cancel برای هر OCO سالمِ کاملاً
قفل‌شده هم صادق است → rebuild تریلینگ تعویق نامحدود. heuristic فقط در بافت
post-cancel معنا دارد. حذف ۱۲ خط → رفتار اصلی بازمی‌گردد.
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

BLOCK = ("            # G-blocked-fix (P0-C): بررسی «استاپ در حال پرشدن» قبل از لغو OCO —\n"
         "            # آینهٔ واقعی Fix-4. قبلاً این بررسی بعد از لغو انجام می‌شد → استاپِ در حال\n"
         "            # اجرا قطع می‌شد و باقیمانده بدون OCO ردیابی‌شده می‌ماند (W/RSR/S در ۱۲ اکتبر)\n"
         "            _av0 = currency_available(client, sym)\n"
         "            _tot0 = currency_available(client, sym, use_active=False)\n"
         "            _rv0 = p.get('real_volume') or 0\n"
         "            if (_av0 is not None and _tot0 is not None\n"
         "                    and _rv0 > 1e-12 and _av0 < _rv0 * 0.5 and _tot0 >= _rv0 * 0.5):\n"
         "                log.info('G-blocked-fix: OCO rebuild deferred BEFORE cancel for %s '\n"
         "                         '(exchange stop filling: active=%.6f total=%.6f)',\n"
         "                         sym, _av0, _tot0)\n"
         "                continue\n")


def build_candidate():
    with open(SRC, encoding='utf-8') as f:
        text = f.read()
    n = text.count(BLOCK)
    if n != 1:
        sys.exit(f'ABORT: بلوک {n} بار یافت شد (انتظار ۱)')
    with open(CAND, 'w', encoding='utf-8') as f:
        f.write(text.replace(BLOCK, '', 1))
    print('۱۲ خط گارد pre-cancel حذف شد — کاندید:', CAND)


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

    # R1: حالت زندهٔ 16:08 — سکه‌ها در OCO قفل؛ لغوی موفق آزادشان می‌کند → rebuild
    state1 = {'locked': True}

    def ca1(client, cur, use_active=True):
        if use_active:
            return 0.004 if state1['locked'] else 100.0
        return 100.0

    mod.currency_available = ca1
    fc = FakeClient()
    orig_cancel1 = fc.cancel_order

    def cancel_unlock(oid):
        state1['locked'] = False  # لغوی OCO سالم → سکه‌ها آزاد
        return orig_cancel1(oid)

    fc.cancel_order = cancel_unlock
    led = _rb_led()
    mod.apply_trailing(_tr_st(), FakeSheet(), led, {'TST': 1.05}, fc)
    check('R1 OCO قفل سالم + لغوی موفق → rebuild (رفع رگرسیون)',
          fc.cancel_calls == ['777', '888'] and len(fc.oco_calls) == 1,
          str((fc.cancel_calls, fc.oco_calls)))
    check('R1 SL پوزیشن بالا رفت', abs(led['positions']['TST']['sl'] - 1.04475) < 1e-6)

    # R2: race اصلی — لغو «موفق» ولی سکه‌ها قفل می‌مانند (استاپ در حال پرشدن)
    state2 = {'locked': False}

    def ca2(client, cur, use_active=True):
        if use_active:
            return 0.004 if state2['locked'] else 100.0
        return 100.0

    mod.currency_available = ca2
    fc2 = FakeClient()
    orig_cancel2 = fc2.cancel_order

    def cancel_lock(oid):
        state2['locked'] = True  # استاپ هم‌زمان شروع به پر شدن کرد
        return orig_cancel2(oid)

    fc2.cancel_order = cancel_lock
    mod.apply_trailing(_tr_st(), FakeSheet(), _rb_led(), {'TST': 1.05}, fc2)
    check('R2 race post-cancel → بازثبت به چرخهٔ بعد (هندلر اصلی حفظ شد)',
          fc2.cancel_calls == ['777', '888'] and fc2.oco_calls == [])

    # R3: آزاد کامل → rebuild کامل
    mod.currency_available = lambda client, cur, use_active=True: 100.0
    fc3 = FakeClient()
    mod.apply_trailing(_tr_st(), FakeSheet(), _rb_led(), {'TST': 1.05}, fc3)
    check('R3 آزاد کامل → rebuild کامل',
          fc3.cancel_calls == ['777', '888'] and len(fc3.oco_calls) == 1)
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
        print('کاندید آماده. برای استقرار: venv/bin/python apply_gblocked_revert.py --deploy')
    return 0


if __name__ == '__main__':
    sys.exit(main())
