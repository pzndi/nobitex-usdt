#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_cancel_fix.py — G-cancel: رفع P0-A (لغو سفارش کهنه با شناسه عددی واقعی)
۱) یافتن دقیق بلوک معیوب در trader.py (assert یکتایی نشانگرها + محتوای مورد انتظار)
۲) ساخت trader_candidate.py
۳) py_compile کاندید
۴) ۱۰ تست واحد با mock (شامل تست منفیِ «هرگز id غیرعددی به cancel نرود»)
۵) فقط با --deploy: بکاپ + جایگزینی اتمیک
بدون --deploy، trader.py دست نمی‌خورد.
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

START = "        oid = clean_oid(o.get('pairId'))"
END = "            log.warning('لغو سفارش کهنه %s ناموفق: %s', sym, str(data_c)[:120])"

NEW_BLOCK = """        # G-cancel: apiv2 برای سفارش‌های دارای clientOrderId فیلد pairId در
        # orders/list نمی‌فرستد → شناسه عددی از ردیف خرید باز همان نماد در دفتر
        # (ثبت‌شده هنگام ثبت سفارش از پاسخ orders/add). آخرین ردیف منطبق برنده است.
        oid = clean_oid(o.get('pairId'))
        if not oid:
            for _rn, _rr in led.get('rows') or []:
                if (len(_rr) > 11 and str(_rr[1]).strip().upper() == sym
                        and str(_rr[2]).strip() == 'خرید'
                        and str(_rr[11]).strip() in OPENISH):
                    _c = clean_oid(_rr[10])
                    if _c.isdigit():
                        oid = _c
        if not oid:
            log.warning('لغو سفارش کهنه %s ناموفق: شناسه عددی سفارش یافت نشد '
                        '(pairId غایب و ردیف دفتر بدون oid)', sym)
            continue
        # تأیید هویت: شناسه دفتر باید به همین سفارش (cid) تعلق داشته و فعال باشد
        try:
            _cs, _ds = client.order_status(oid)
            _ord = _ds.get('order') if isinstance(_ds, dict) else None
            _ord = _ord if isinstance(_ord, dict) else {}
            if str(_ord.get('clientOrderId') or '') != cid:
                log.warning('لغو سفارش کهنه %s ناموفق: شناسه دفتر %s با سفارش زنده '
                            'هم‌خوان نیست — رد شد', sym, oid)
                continue
            if str(_ord.get('status')) != 'Active':
                log.info('سفارش کهنه %s فعال نیست (%s) — به همگام‌سازی واگذار شد',
                         sym, _ord.get('status'))
                continue
        except Exception:
            log.warning('لغو سفارش کهنه %s: استعلام وضعیت ناموفق — این چرخه رد شد', sym)
            continue
        code_c, data_c = client.cancel_order(oid)
        ok = (code_c in (200, 201)
              and not (isinstance(data_c, dict) and data_c.get('status') == 'failed'))
        if ok:
            for row_num, rr in led['rows']:
                if oid in str(rr[10]).replace(',', ''):
                    ws_t.update_cell(row_num, 12, ST_CANCELLED)
                    break
            led['pending'].discard(sym)
            log.info('سفارش ورود کهنه لغو شد: %s (سن %.0f دقیقه)', sym, age_min)
        elif isinstance(data_c, dict) and str(data_c.get('error')) == 'NotFound':
            # سفارش در فاصله fetch→cancel از لیست خارج شده (fill/لغو بیرونی) —
            # وضعیت واقعی را همگام‌سازی چرخه بعد تعیین می‌کند؛ دفتر دست نمی‌خورد
            log.info('سفارش کهنه %s پیش از لغو از لیست خارج شد — به همگام‌سازی واگذار شد', sym)
        else:
            log.warning('لغو سفارش کهنه %s ناموفق: %s', sym, str(data_c)[:120])"""


def build_candidate():
    with open(SRC, encoding='utf-8') as f:
        text = f.read()
    if text.count(START) != 1:
        sys.exit(f'ABORT: نشانگر START {text.count(START)} بار یافت شد (انتظار: ۱)')
    if text.count(END) != 1:
        sys.exit(f'ABORT: نشانگر END {text.count(END)} بار یافت شد (انتظار: ۱)')
    i = text.index(START)
    j = text.index(END, i) + len(END)
    old = text[i:j]
    if 'تلاش دوم با clientOrderId' not in old:
        sys.exit('ABORT: بلوک فعلی با انتظار هم‌خوان نیست (شاید قبلاً patch شده)')
    print(f'بلوک فعلی: {len(old.splitlines())} خط — جایگزین با {len(NEW_BLOCK.splitlines())} خط')
    with open(CAND, 'w', encoding='utf-8') as f:
        f.write(text[:i] + NEW_BLOCK + text[j:])
    print(f'کاندید نوشته شد: {CAND}')


class FakeWS:
    def __init__(self):
        self.cells = []

    def update_cell(self, row, col, val):
        self.cells.append((row, col, val))


class FakeClient:
    def __init__(self, orders=None, status_map=None, cancel_result=None):
        self._orders = orders or []
        self._status_map = status_map or {}
        self._cancel_result = cancel_result or (lambda oid: (200, {'status': 'ok', 'updatedStatus': 'Canceled'}))
        self.cancel_calls = []

    def open_orders(self):
        return 200, {'orders': self._orders}

    def order_status(self, oid):
        return self._status_map.get(str(oid), (404, {'error': 'NotFound', 'order': {}}))

    def cancel_order(self, oid):
        oid = str(oid)
        assert oid.isdigit(), f'NON-NUMERIC cancel id (ریشه ParseError): {oid!r}'
        self.cancel_calls.append(oid)
        return self._cancel_result(oid)


def _st(ttl=60):
    return types.SimpleNamespace(entry_ttl_min=ttl)


def _led(rows=(), pending=()):
    return {'positions': {}, 'pending': set(pending), 'pending_sells': set(),
            'daily_count': 0, 'dry_net_spent': 0.0, 'rows': list(rows)}


def _buy_row(sym, oid, status='باز', row_num=10):
    r = ['1405/07/22 08:00', sym, 'خرید', '1h', 'رأی خرید', '1.0', '10', '10.0',
         '0.9', '1.1', oid, status, 'msg']
    return (row_num, r)


def _order(sym, cid, age_min=120, matched=0, pair_id=None):
    o = {'type': 'buy', 'execution': 'Limit', 'srcCurrency': sym,
         'price': '1.0', 'amount': '10', 'matchedAmount': str(matched),
         'unmatchedAmount': str(10 - matched), 'clientOrderId': cid}
    if pair_id is not None:
        o['pairId'] = pair_id
    return o


def _cid(sym, age_min=120):
    return f'nbx-{sym.lower()}-{int(time.time() - age_min * 60)}'


def _status_ok(cid):
    return (200, {'status': 'ok', 'order': {'clientOrderId': cid, 'type': 'buy',
                                            'status': 'Active'}})


def run_tests(mod):
    results = []

    def check(name, cond, extra=''):
        results.append((name, bool(cond)))
        print(('PASS' if cond else 'FAIL'), '-', name, ('| ' + extra) if (extra and not cond) else '')

    # T1: سناریوی دقیق باگ — سفارش با cid بدون pairId + oid عددی در ردیف دفتر
    cid = _cid('bat')
    fc = FakeClient(orders=[_order('BAT', cid)], status_map={'6630240648': _status_ok(cid)})
    ws = FakeWS()
    led = _led(rows=[_buy_row('BAT', '6630240648')], pending=['BAT'])
    mod.cancel_stale_entries(_st(), ws, fc, led)
    check('T1 لغو با شناسه عددی دفتر', fc.cancel_calls == ['6630240648'], str(fc.cancel_calls))
    check('T1 علامت ردیف لغو', ws.cells == [(10, 12, mod.ST_CANCELLED)], str(ws.cells))
    check('T1 حذف از pending', 'BAT' not in led['pending'])

    # T2: سفارش فروش هرگز لمس نمی‌شود
    fc2 = FakeClient(orders=[{'type': 'sell', 'execution': 'Limit', 'srcCurrency': 'S',
                              'matchedAmount': '0', 'clientOrderId': None, 'pairId': 1}])
    mod.cancel_stale_entries(_st(), FakeWS(), fc2, _led())
    check('T2 فروش لمس نمی‌شود', fc2.cancel_calls == [])

    # T3: بخشی‌پر لمس نمی‌شود
    fc3 = FakeClient(orders=[_order('BAT', _cid('bat'), matched=5)])
    mod.cancel_stale_entries(_st(), FakeWS(), fc3, _led())
    check('T3 بخشی‌پر لمس نمی‌شود', fc3.cancel_calls == [])

    # T4: سفارش زیر TTL لمس نمی‌شود
    fc4 = FakeClient(orders=[_order('BAT', _cid('bat', age_min=10))])
    mod.cancel_stale_entries(_st(), FakeWS(), fc4, _led())
    check('T4 زیر TTL لمس نمی‌شود', fc4.cancel_calls == [])

    # T5: سفارش دستی کاربر لمس نمی‌شود
    fc5 = FakeClient(orders=[_order('BAT', 'my-manual-order')])
    mod.cancel_stale_entries(_st(), FakeWS(), fc5, _led())
    check('T5 سفارش دستی لمس نمی‌شود', fc5.cancel_calls == [])

    # T6: NotFound (خروج سفارش بین fetch تا cancel) → بدون write دفتر
    cid6 = _cid('bat')
    fc6 = FakeClient(orders=[_order('BAT', cid6)],
                     status_map={'6630240648': _status_ok(cid6)},
                     cancel_result=lambda oid: (404, {'error': 'NotFound'}))
    ws6 = FakeWS()
    led6 = _led(rows=[_buy_row('BAT', '6630240648')], pending=['BAT'])
    mod.cancel_stale_entries(_st(), ws6, fc6, led6)
    check('T6 NotFound: لغو تلاش شد', fc6.cancel_calls == ['6630240648'])
    check('T6 NotFound: دفتر دست نخورد', ws6.cells == [])
    check('T6 NotFound: pending دست نخورد', 'BAT' in led6['pending'])

    # T7: ناهم‌خوانی هویت → بدون لغو
    cid7 = _cid('bat')
    fc7 = FakeClient(orders=[_order('BAT', cid7)],
                     status_map={'6630240648': _status_ok('nbx-bat-9999999999')})
    mod.cancel_stale_entries(_st(), FakeWS(), fc7, _led(rows=[_buy_row('BAT', '6630240648')]))
    check('T7 ناهم‌خوانی هویت → بدون لغو', fc7.cancel_calls == [])

    # T8: ردیف دفتر بدون oid → بدون فراخوانی لغو
    fc8 = FakeClient(orders=[_order('BAT', _cid('bat'))])
    mod.cancel_stale_entries(_st(), FakeWS(), fc8, _led(rows=[_buy_row('BAT', '—')]))
    check('T8 بدون oid دفتر → بدون لغو', fc8.cancel_calls == [])

    # T9: اگر pairId موجود باشد همان استفاده می‌شود
    cid9 = _cid('bat')
    fc9 = FakeClient(orders=[_order('BAT', cid9, pair_id=7770001111)],
                     status_map={'7770001111': _status_ok(cid9)})
    ws9 = FakeWS()
    led9 = _led(rows=[_buy_row('BAT', '7770001111', row_num=12)], pending=['BAT'])
    mod.cancel_stale_entries(_st(), ws9, fc9, led9)
    check('T9 pairId موجود → لغو با آن', fc9.cancel_calls == ['7770001111'])
    check('T9 علامت ردیف', ws9.cells == [(12, 12, mod.ST_CANCELLED)])

    # T10: سفارش fill شده (status != Active) → بدون لغو، واگذار به sync
    cid10 = _cid('bat')
    fc10 = FakeClient(orders=[_order('BAT', cid10)],
                      status_map={'6630240648': (200, {'status': 'ok', 'order': {
                          'clientOrderId': cid10, 'type': 'buy', 'status': 'Done'}})})
    mod.cancel_stale_entries(_st(), FakeWS(), fc10, _led(rows=[_buy_row('BAT', '6630240648')]))
    check('T10 سفارش Done → بدون لغو', fc10.cancel_calls == [])

    return results


def deploy():
    bak = f'trader.py.bak.{time.strftime("%Y%m%d_%H%M")}'
    shutil.copy2(SRC, bak)
    os.replace(CAND, SRC)
    py_compile.compile(SRC, doraise=True)
    print(f'استقرار انجام شد: {SRC} (بکاپ: {bak})')
    print('پایش: tail -n 60 update.log برای دو چرخه آینده')


def main():
    if not os.path.exists(SRC):
        sys.exit('ABORT: trader.py یافت نشد')
    build_candidate()
    try:
        py_compile.compile(CAND, doraise=True)
        print('COMPILE OK (کاندید)')
    except Exception as e:
        sys.exit(f'ABORT: کامپایل کاندید ناموفق: {e}')
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
        print('کاندید آماده و تست‌شده. برای استقرار: venv/bin/python apply_cancel_fix.py --deploy')
    return 0


if __name__ == '__main__':
    sys.exit(main())
