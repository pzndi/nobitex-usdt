#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_filltime_fix.py — P2-1: سن پوزیشن/مدت نگهداری از زمان fill (نه زمان ثبت سفارش)
۱) sync: مهر «fill@زمان» در ستون پیام هنگام گذار خرید→پر شد (یک‌بار)
۲) helper _fill_time_of با fallback به col 0
۳) check_position_timeout و record_closed از helper می‌خوانند
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

E1_OLD = ("            log.info('گذار خرید به پرشد %s | use_oco=%s | در pending_sells=%s',\n"
          "                     sym_c,\n"
          "                     (getattr(st, 'use_exchange_oco', None) if st is not None else None),\n"
          "                     sym_c in led.get('pending_sells', set()))")
E1_NEW = E1_OLD + """
            # P2-1 (fill-time): مهر زمان fill در ستون پیام — سن پوزیشن timeout و
            # مدت نگهداری از fill محاسبه شوند نه زمان ثبت سفارش (شاهد: BAT با سن
            # کاذب 18.1h در ۵ دقیقه پس از fill). یک‌بار؛ گارد fill@ دارد.
            _msg = str(r[12] or '')
            if 'fill@' not in _msg:
                try:
                    ws_t.update_cell(row_num, 13, (_msg + ' | fill@' + jnow())[:250])
                except Exception:
                    pass"""

E2_OLD = "def check_position_timeout(st, ws_t, client, dry, led, prices):"
E2_NEW = """def _fill_time_of(rr):
    \"\"\"P2-1: زمان fill ردیف خرید از مهر «fill@» در ستون پیام؛ fallback: زمان ثبت.
    مبنای سن پوزیشن (timeout) و مدت معاملات بسته — نه زمان ثبت سفارش.\"\"\"
    msg = str(rr[12]) if len(rr) > 12 else ''
    if 'fill@' in msg:
        return msg.split('fill@', 1)[1][:16]
    return rr[0]


def check_position_timeout(st, ws_t, client, dry, led, prices):"""

E3_OLD = "                entry_t = rr[0]"
E3_NEW = "                entry_t = _fill_time_of(rr)"

E4_OLD = ("            t_in = next((rr[0] for _, rr in reversed(led['rows'])\n"
          "                         if rr[1].strip().upper() == sym_c and rr[2].strip() == 'خرید'\n"
          "                         and rr[11].strip() in EXECUTED), '—')")
E4_NEW = ("            t_in = next((_fill_time_of(rr) for _, rr in reversed(led['rows'])\n"
          "                         if rr[1].strip().upper() == sym_c and rr[2].strip() == 'خرید'\n"
          "                         and rr[11].strip() in EXECUTED), '—')")


def build_candidate():
    with open(SRC, encoding='utf-8') as f:
        text = f.read()
    if 'fill@' in text:
        sys.exit('ABORT: قبلاً patch شده')
    for tag, old in (('E1', E1_OLD), ('E3', E3_OLD), ('E4', E4_OLD)):
        if text.count(old) != 1:
            sys.exit(f'ABORT [{tag}]: {text.count(old)} بار یافت شد (انتظار: ۱)')
    if text.count(E2_OLD) != 1:
        sys.exit('ABORT [E2]: تعریف check_position_timeout یافت نشد')
    text = text.replace(E1_OLD, E1_NEW, 1)
    text = text.replace(E2_OLD, E2_NEW, 1)
    text = text.replace(E3_OLD, E3_NEW, 1)
    text = text.replace(E4_OLD, E4_NEW, 1)
    with open(CAND, 'w', encoding='utf-8') as f:
        f.write(text)
    print('E1-E4 اعمال شد — کاندید:', CAND)


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

    def order_status(self, oid):
        return (200, {'status': 'ok', 'order': {'status': 'Done',
                                                'matchedAmount': '10', 'price': '1.0'}})

    def place_order(self, otype, sym, price, vol, is_market, client_order_id=None):
        self.place_calls.append((otype, sym, float(price), float(vol)))
        return (200, {'status': 'ok', 'order': {'id': 555}})

    def place_oco_sell(self, sym, vol, tp, sl, stop_limit=None):
        return (200, {'status': 'ok', 'order': {'id': 11}, 'orders': [{'id': 11}, {'id': 12}]})


def _mk_row(msg, status='پر شد', t='1405/07/21 04:00'):
    return [t, 'TST', 'خرید', '1h', 'رأی', '1.0', '100', '100.0',
            '0.95', '1.10', '999', status, msg]


def run_tests(mod):
    results = []

    def check(name, cond, extra=''):
        results.append((name, bool(cond)))
        print(('PASS' if cond else 'FAIL'), '-', name, ('| ' + extra) if (extra and not cond) else '')

    # FT1: مهر در گذار خرید→پر شد + idempotency
    st = types.SimpleNamespace(use_exchange_oco=False)
    fc = FakeClient()
    ws = FakeSheet()
    led = {'rows': [(10, _mk_row("{'status': 'ok'}", status='ثبت‌شده', t='1405/07/22 07:00'))],
           'positions': {}, 'pending': set(), 'pending_sells': set()}
    mod.sync_order_statuses(ws, led, fc, st)
    check('FT1 وضعیت → پر شد', any(r == 10 and c == 12 and v == mod.ST_FILLED
                                    for r, c, v in ws.cells), str(ws.cells))
    stamps = [v for r, c, v in ws.cells if r == 10 and c == 13]
    check('FT1 مهر fill@ ثبت شد', len(stamps) == 1 and 'fill@' in str(stamps[0]), str(stamps))

    fc2, ws2 = FakeClient(), FakeSheet()
    led2 = {'rows': [(10, _mk_row("{'status': 'ok'} | fill@1405/07/22 07:30",
                                  status='ثبت‌شده', t='1405/07/22 07:00'))],
            'positions': {}, 'pending': set(), 'pending_sells': set()}
    mod.sync_order_statuses(ws2, led2, fc2, st)
    stamps2 = [v for r, c, v in ws2.cells if r == 10 and c == 13]
    check('FT1 ردیف مهرخورده → بدون مهر دوباره', len(stamps2) == 0, str(ws2.cells))

    # FT2: timeout سن را از fill می‌گیرد
    mod.currency_available = lambda client, cur, use_active=True: 100.0
    stt = types.SimpleNamespace(position_timeout_h=8, position_timeout_min_pct=0.0,
                                exit_order_type='market')
    import jdatetime as _jd
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    _t = (_dt.now(_tz.utc) + _td(hours=3, minutes=30) - _td(hours=2)).replace(tzinfo=None)
    marker = _jd.datetime.fromgregorian(datetime=_t).strftime('%Y/%m/%d %H:%M')
    led_a = {'rows': [(10, _mk_row('x | fill@' + marker))],
             'positions': {'TST': {'volume': 100.0, 'sim_volume': 0.0, 'real_volume': 100.0,
                                   'entry_price': 1.0, 'sl': 0.95, 'tp': 1.10}},
             'pending': set(), 'pending_sells': set(), 'daily_count': 0, 'dry_net_spent': 0.0}
    fc_a = FakeClient()
    mod.check_position_timeout(stt, FakeSheet(), fc_a, False, led_a, {'TST': 0.99})
    check('FT2 مهر ۲h پیش → بدون timeout', fc_a.place_calls == [], str(fc_a.place_calls))

    led_b = {'rows': [(10, _mk_row('x بدون مهر'))],
             'positions': {'TST': {'volume': 100.0, 'sim_volume': 0.0, 'real_volume': 100.0,
                                   'entry_price': 1.0, 'sl': 0.95, 'tp': 1.10}},
             'pending': set(), 'pending_sells': set(), 'daily_count': 0, 'dry_net_spent': 0.0}
    fc_b = FakeClient()
    mod.check_position_timeout(stt, FakeSheet(), fc_b, False, led_b, {'TST': 0.99})
    check('FT2 بدون مهر (~۳۰h) → timeout فعال', len(fc_b.place_calls) == 1, str(fc_b.place_calls))

    # FT3: helper
    rr = ['t0', 'TST', 'خرید', '1h', 'r', '1', '1', '1', '0.9', '1.1', '9', 'پر شد',
          'x | fill@1405/07/22 08:41 | P&L: +0.10']
    check('FT3 مهر خوانده شد', mod._fill_time_of(rr) == '1405/07/22 08:41', mod._fill_time_of(rr))
    rr2 = list(rr)
    rr2[12] = 'بدون مهر'
    check('FT3 fallback به col 0', mod._fill_time_of(rr2) == 't0')
    check('FT3 ردیف کوتاه → col 0', mod._fill_time_of(rr[:12]) == 't0')
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
        print('کاندید آماده. برای استقرار: venv/bin/python apply_filltime_fix.py --deploy')
    return 0


if __name__ == '__main__':
    sys.exit(main())
