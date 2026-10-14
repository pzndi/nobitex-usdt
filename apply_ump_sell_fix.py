#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_ump_sell_fix.py — G-ump-sell: رفع P0-B
۱) sell_one: retry با قیمت تازه روی شکست قطعی UnexpectedMarketPrice + خروجی True/False
۲) فلگ _pe_done: ردیف «ناموفق» خروج جزئی → done نمی‌کند
۳) بلوک خروج جزئی: حسابداری/بازثبت OCO فقط پس از فروش موفق + لاگ شکست بازثبت
بدون --deploy هیچ فایلی از پروژه عوض نمی‌شود.
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

A_START = "    code, data = client.place_order('sell', sym, price, vol, st.exit_order_type == 'market')"
A_END = ("        record_trade(ws_t, 'فروش', sym, '', reason, fmt_price(price), vol, amount,\n"
         "                     '—', '—', '', 'ناموفق', str(data)[:100])")

A_NEW = """    code, data = client.place_order('sell', sym, price, vol, st.exit_order_type == 'market')
    ok = code == 200 and isinstance(data, dict) and data.get('status') == 'ok'
    # G-ump-sell: شکست قطعی UnexpectedMarketPrice = قیمت ارسالی از بازار فعلی عقب مانده؛
    # یک تلاش مجدد با قیمت تازه (آینهٔ G-ump خرید — برای خروج فوریت بالاست پس حد sanity
    # نسبت به خرید loosen است). مطابق X2: فقط روی پاسخ صریح failed، نه پاسخ گمشده.
    if (not ok and code == 200 and isinstance(data, dict)
            and data.get('status') == 'failed'
            and data.get('code') == 'UnexpectedMarketPrice'):
        _fresh = _public_price(sym)
        if _fresh and _fresh > 0 and price and abs(_fresh - price) / price < 0.20:
            log.info('G-ump-sell: retrying %s with fresh price %.6g (was %.6g)',
                     sym, _fresh, price)
            price = _fresh
            amount = round(vol * price, 2)
            if entry:
                pnl = round(vol * price - vol * entry, 2)
                pnl_msg = f' | P&L: {pnl:+.2f} USDT'
            code, data = client.place_order('sell', sym, price, vol,
                                            st.exit_order_type == 'market')
            ok = code == 200 and isinstance(data, dict) and data.get('status') == 'ok'
    o = (data.get('order') or {}) if isinstance(data, dict) else {}
    oid = clean_oid(o.get('id') if isinstance(o, dict) else None or (data.get('id') if isinstance(data, dict) else ''))
    if ok:
        record_trade(ws_t, 'فروش', sym, '', reason, fmt_price(price), vol, amount,
                     '—', '—', oid, ST_PLACED, str(data)[:80] + pnl_msg)
        return True
    else:
        log.error('ثبت سفارش واقعی فروش %s ناموفق: HTTP %s | %s', sym, code, str(data)[:150])
        record_trade(ws_t, 'فروش', sym, '', reason, fmt_price(price), vol, amount,
                     '—', '—', '', 'ناموفق', str(data)[:100])
        return False"""

B_OLD = """            _pe_done = any(
                ('خروج جزئی' in str(rr[4])
                 or 'OCO post-partial' in str(rr[12]))
                and str(rr[1]).strip().upper() == sym
                for _, rr in led['rows'])"""

B_NEW = """            # G-ump-sell: ردیف «ناموفق» فلگ را set نمی‌کند — شکست خروج جزئی باید
            # در چرخهٔ بعد تلاش مجدد شود؛ ردیف‌های «ثبت‌شده»/«پر شد» (سفارش کارکردی)
            # همچنان race-protection را حفظ می‌کنند
            _pe_done = any(
                (('خروج جزئی' in str(rr[4]) and str(rr[11]).strip() != 'ناموفق')
                 or 'OCO post-partial' in str(rr[12]))
                and str(rr[1]).strip().upper() == sym
                for _, rr in led['rows'])"""

C_START = "                if _pe_vol > 1e-12:"
C_END = "                    log.warning('G-pexit %s: no sellable volume after OCO cancel', sym)"

C_NEW = """                if _pe_vol > 1e-12:
                    _ok_sell = sell_one(st, ws_t, client, False, sym,
                                        'خروج جزئی (+%.1f%%)' % st.partial_exit_trigger,
                                        price, _pe_vol, led)
                    if not _ok_sell:
                        # G-ump-sell: فروش جزئی ناموفق — حجم‌ها و OCO دست نمی‌خورند؛
                        # ردیف «ناموفق» فلگ را set نمی‌کند → تلاش مجدد چرخهٔ بعد؛
                        # تور ایمنی backfill سکه‌های آزادشده را پوشش می‌دهد
                        log.warning('G-pexit %s: فروش جزئی ناموفق — به چرخهٔ بعد موکول', sym)
                    else:
                        p['real_volume'] = max(0, p['real_volume'] - _pe_vol)
                        p['volume'] = max(0, p.get('volume', 0) - _pe_vol)
                        led['positions'][sym] = p
                        # OCO جدید با حجم باقیمانده
                        _pe_remaining = p['real_volume']
                        _pe_sl = p.get('sl')
                        _pe_tp = p.get('tp')
                        _pe_avail = currency_available(client, sym)
                        if _pe_avail is not None:
                            _pe_remaining = min(_pe_remaining, _pe_avail)
                        if _pe_remaining > 1e-12 and _pe_sl and _pe_tp:
                            _c2, _d2 = client.place_oco_sell(sym, _pe_remaining, _pe_tp, _pe_sl)
                            _ok2 = _c2 == 200 and isinstance(_d2, dict) and _d2.get('status') == 'ok'
                            if _ok2:
                                _o2 = (_d2.get('order') or {}) if isinstance(_d2, dict) else {}
                                _legs = []
                                if isinstance(_o2, dict):
                                    for _k2 in ('id', 'pairId', 'orderId'):
                                        if _o2.get(_k2):
                                            _legs.append(clean_oid(_o2.get(_k2)))
                                if isinstance(_d2, dict) and isinstance(_d2.get('orders'), list):
                                    for _lg2 in _d2['orders']:
                                        if isinstance(_lg2, dict):
                                            for _k2 in ('id', 'pairId', 'orderId'):
                                                if _lg2.get(_k2):
                                                    _legs.append(clean_oid(_lg2.get(_k2)))
                                record_trade(ws_t, 'فروش', sym, '', 'OCO حد سود/ضرر بومی صرافی',
                                             fmt_price(_pe_tp), _pe_remaining,
                                             round(_pe_remaining * _pe_tp, 2),
                                             fmt_price(_pe_sl), fmt_price(_pe_tp),
                                             '|'.join(dict.fromkeys(_legs)), ST_PLACED,
                                             'OCO post-partial: TP=' + fmt_price(_pe_tp) + ' | SL=' + fmt_price(_pe_sl))
                                led.setdefault('pending_sells', set()).add(sym)
                                log.info('G-pexit-fix: OCO re-placed for %s | vol=%.6f | SL=%s',
                                         sym, _pe_remaining, fmt_price(_pe_sl))
                            else:
                                log.error('G-pexit %s: بازثبت OCO ناموفق (HTTP %s) — تور ایمنی چرخهٔ بعد جبران می‌کند',
                                          sym, _c2)
                        log.info('G-pexit: sold %.1f%% of %s at +%.1f%% (state persisted)',
                                 st.partial_exit_pct, sym, st.partial_exit_trigger)
                else:
                    log.warning('G-pexit %s: no sellable volume after OCO cancel', sym)"""


def build_candidate():
    with open(SRC, encoding='utf-8') as f:
        text = f.read()

    def span(text, start, end, new, tag, anchors):
        if text.count(start) != 1:
            sys.exit(f'ABORT [{tag}]: نشانگر START {text.count(start)} بار (انتظار ۱)')
        if text.count(end) != 1:
            sys.exit(f'ABORT [{tag}]: نشانگر END {text.count(end)} بار (انتظار ۱)')
        i = text.index(start)
        j = text.index(end, i) + len(end)
        old = text[i:j]
        for must in anchors:
            if must not in old:
                sys.exit(f'ABORT [{tag}]: بلوک فعلی با انتظار هم‌خوان نیست: {must!r} یافت نشد')
        return text[:i] + new + text[j:], old

    text, old_a = span(text, A_START, A_END, A_NEW, 'A:sell_one',
                       ['ثبت سفارش واقعی فروش', 'place_order'])
    if 'G-ump-sell' in old_a:
        sys.exit('ABORT [A]: قبلاً patch شده')
    if text.count(B_OLD) != 1:
        sys.exit(f'ABORT [B]: بلوک فلگ {text.count(B_OLD)} بار یافت شد')
    text = text.replace(B_OLD, B_NEW, 1)
    text, old_c = span(text, C_START, C_END, C_NEW, 'C:partial',
                       ["G-pexit: sold", "sell_one(st, ws_t, client, False, sym,"])
    if '_ok_sell' in old_c:
        sys.exit('ABORT [C]: قبلاً patch شده')
    with open(CAND, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f'A: {len(old_a.splitlines())} → {len(A_NEW.splitlines())} خط | '
          f'B: {len(B_OLD.splitlines())} → {len(B_NEW.splitlines())} خط | '
          f'C: {len(old_c.splitlines())} → {len(C_NEW.splitlines())} خط')
    print(f'کاندید نوشته شد: {CAND}')


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
    def __init__(self, place_responses=None):
        self.place_responses = list(place_responses or [])
        self.place_calls = []
        self.oco_calls = []

    def place_order(self, otype, sym, price, vol, is_market, client_order_id=None):
        self.place_calls.append((otype, sym, float(price), float(vol), bool(is_market)))
        if self.place_responses:
            return self.place_responses.pop(0)
        return (200, {'status': 'ok', 'order': {'id': 555}})

    def place_oco_sell(self, sym, vol, tp, sl, stop_limit=None):
        self.oco_calls.append((sym, float(vol), float(tp), float(sl)))
        return (200, {'status': 'ok', 'order': {'id': 11},
                      'orders': [{'id': 11}, {'id': 12}]})


UMP = (200, {'status': 'failed', 'code': 'UnexpectedMarketPrice', 'message': 'Price validation failed'})
SMALL = (200, {'status': 'failed', 'code': 'SmallOrder', 'message': 'x'})
OK = (200, {'status': 'ok', 'order': {'id': 555}})


def _sell_st():
    return types.SimpleNamespace(exit_order_type='market')


def _sell_led():
    return {'positions': {'TST': {'entry_price': 1.10}}, 'rows': [], 'dry_net_spent': 0.0}


def run_sell_tests(mod):
    results = []

    def check(name, cond, extra=''):
        results.append((name, bool(cond)))
        print(('PASS' if cond else 'FAIL'), '-', name, ('| ' + extra) if (extra and not cond) else '')

    def price_of(ws):
        return float(str(ws.rows[-1][5]).replace(',', ''))

    mod._public_price = lambda s: 1.135
    fc = FakeClient([UMP, OK])
    ws = FakeSheet()
    r = mod.sell_one(_sell_st(), ws, fc, False, 'TST', 'تست', 1.14, 10.0, _sell_led())
    check('S1 UMP→retry موفق → True', r is True, str(r))
    check('S1 دو فراخوانی', len(fc.place_calls) == 2, str(fc.place_calls))
    check('S1 قیمت تازه در فراخوانی دوم', abs(fc.place_calls[1][2] - 1.135) < 1e-9)
    check('S1 ردیف ثبت‌شده', ws.rows[-1][11] == mod.ST_PLACED, ws.rows[-1][11])
    check('S1 قیمت ردیف = تازه', abs(price_of(ws) - 1.135) < 1e-6, str(price_of(ws)))

    fc2 = FakeClient([UMP, UMP])
    ws2 = FakeSheet()
    r2 = mod.sell_one(_sell_st(), ws2, fc2, False, 'TST', 'تست', 1.14, 10.0, _sell_led())
    check('S2 retry هم ناموفق → False', r2 is False, str(r2))
    check('S2 ردیف ناموفق', ws2.rows[-1][11] == 'ناموفق')
    check('S2 دو فراخوانی', len(fc2.place_calls) == 2)

    mod._public_price = lambda s: 2.0
    fc3 = FakeClient([UMP])
    r3 = mod.sell_one(_sell_st(), FakeSheet(), fc3, False, 'TST', 'تست', 1.14, 10.0, _sell_led())
    check('S3 انحراف>20٪ → بدون retry', len(fc3.place_calls) == 1 and r3 is False)

    mod._public_price = lambda s: None
    fc4 = FakeClient([UMP])
    r4 = mod.sell_one(_sell_st(), FakeSheet(), fc4, False, 'TST', 'تست', 1.14, 10.0, _sell_led())
    check('S4 بدون قیمت تازه → بدون retry', len(fc4.place_calls) == 1 and r4 is False)

    mod._public_price = lambda s: 1.135
    fc5 = FakeClient([SMALL])
    r5 = mod.sell_one(_sell_st(), FakeSheet(), fc5, False, 'TST', 'تست', 1.14, 10.0, _sell_led())
    check('S5 غیر UMP → هرگز retry (X2)', len(fc5.place_calls) == 1 and r5 is False)

    fc6 = FakeClient([OK])
    r6 = mod.sell_one(_sell_st(), FakeSheet(), fc6, False, 'TST', 'تست', 1.14, 10.0, _sell_led())
    check('S6 موفقیت مستقیم', r6 is True and len(fc6.place_calls) == 1)
    return results


def _tr_st():
    return types.SimpleNamespace(trail_enabled=True, trail_activation_pct=0.0,
                                 trail_atr_mult=0, trail_distance_pct=0.5,
                                 partial_exit_pct=50, partial_exit_trigger=2.0,
                                 exit_order_type='market')


def _tr_led(extra_rows=()):
    rows = [(10, ['1405/07/22 10:00', 'TST', 'خرید', '1h', 'رأی خرید', '1.0', '100', '100.0',
                  '0.90', '1.20', '111', 'پر شد', 'm'])]
    rows += list(extra_rows)
    return {'positions': {'TST': {'volume': 100.0, 'sim_volume': 0.0,
                                  'real_volume': 100.0, 'entry_price': 1.0,
                                  'sl': 0.90, 'tp': 1.20}},
            'pending': set(), 'pending_sells': set(), 'rows': rows,
            'daily_count': 0, 'dry_net_spent': 0.0}


def run_partial_tests(mod):
    results = []

    def check(name, cond, extra=''):
        results.append((name, bool(cond)))
        print(('PASS' if cond else 'FAIL'), '-', name, ('| ' + extra) if (extra and not cond) else '')

    saved_ca = mod.currency_available
    mod.currency_available = lambda client, cur, use_active=True: 100.0

    mod._public_price = lambda s: 1.05
    fc = FakeClient([OK])
    ws = FakeSheet()
    led = _tr_led()
    mod.apply_trailing(_tr_st(), ws, led, {'TST': 1.05}, fc)
    check('PE1 حجم نصف شد', abs(led['positions']['TST']['real_volume'] - 50.0) < 1e-9,
          str(led['positions']['TST']['real_volume']))
    check('PE1 OCO بازثبت با باقیمانده', fc.oco_calls and abs(fc.oco_calls[0][1] - 50.0) < 1e-9, str(fc.oco_calls))
    check('PE1 pending_sells set', 'TST' in led['pending_sells'])
    check('PE1 ردیف OCO post-partial', any('OCO post-partial' in str(r[12]) for r in ws.rows))
    check('PE1 ردیف خروج جزئی', any('خروج جزئی' in str(r[4]) for r in ws.rows))

    fc2 = FakeClient([UMP, UMP])
    ws2 = FakeSheet()
    led2 = _tr_led()
    mod.apply_trailing(_tr_st(), ws2, led2, {'TST': 1.05}, fc2)
    check('PE2 حجم دست‌نخورده', abs(led2['positions']['TST']['real_volume'] - 100.0) < 1e-9,
          str(led2['positions']['TST']['real_volume']))
    check('PE2 بدون بازثبت OCO', fc2.oco_calls == [], str(fc2.oco_calls))
    check('PE2 بدون pending_sells', 'TST' not in led2['pending_sells'])
    check('PE2 ردیف ناموفق ثبت شد', any('خروج جزئی' in str(r[4]) and r[11] == 'ناموفق' for r in ws2.rows))

    failed_row = (11, ['1405/07/22 10:05', 'TST', 'فروش', '', 'خروج جزئی (+2.0%)',
                       '1.05', '50', '52.50', '—', '—', '', 'ناموفق', 'x'])
    fc3 = FakeClient([OK])
    led3 = _tr_led(extra_rows=[failed_row])
    mod.apply_trailing(_tr_st(), FakeSheet(), led3, {'TST': 1.05}, fc3)
    check('PE3 تلاش مجدد بعد از ناموفق', len(fc3.place_calls) == 1, str(fc3.place_calls))
    check('PE3 حجم نصف شد', abs(led3['positions']['TST']['real_volume'] - 50.0) < 1e-9)

    done_row = (12, ['1405/07/22 10:10', 'TST', 'فروش', '', 'خروج جزئی (+2.0%)',
                     '1.05', '50', '52.50', '—', '—', '999', 'پر شد', 'x'])
    fc4 = FakeClient()
    mod.apply_trailing(_tr_st(), FakeSheet(), _tr_led(extra_rows=[done_row]), {'TST': 1.05}, fc4)
    check('PE4 فلگ done (پر شد) → بدون تلاش', fc4.place_calls == [])

    pp_row = (13, ['1405/07/22 10:15', 'TST', 'فروش', '', 'OCO حد سود/ضرر بومی صرافی',
                   '1.20', '50', '60.0', '0.90', '1.20', '11|12', 'ثبت‌شده',
                   'OCO post-partial: TP=1.2 | SL=0.9'])
    fc5 = FakeClient()
    mod.apply_trailing(_tr_st(), FakeSheet(), _tr_led(extra_rows=[pp_row]), {'TST': 1.05}, fc5)
    check('PE5 OCO post-partial → بدون تلاش', fc5.place_calls == [])

    fc6 = FakeClient([SMALL])
    led6 = _tr_led()
    mod.apply_trailing(_tr_st(), FakeSheet(), led6, {'TST': 1.05}, fc6)
    check('PE6 غیر UMP در جزئی → تعویق فوری',
          len(fc6.place_calls) == 1
          and abs(led6['positions']['TST']['real_volume'] - 100.0) < 1e-9)

    fc7 = FakeClient([UMP, OK])
    led7 = _tr_led()
    mod.apply_trailing(_tr_st(), FakeSheet(), led7, {'TST': 1.05}, fc7)
    check('PE7 UMP→retry موفق در جزئی → حسابداری کامل',
          len(fc7.place_calls) == 2
          and abs(led7['positions']['TST']['real_volume'] - 50.0) < 1e-9
          and fc7.oco_calls and abs(fc7.oco_calls[0][1] - 50.0) < 1e-9)

    mod.currency_available = saved_ca
    return results


def deploy():
    bak = f'trader.py.bak.{time.strftime("%Y%m%d_%H%M")}'
    shutil.copy2(SRC, bak)
    os.replace(CAND, SRC)
    py_compile.compile(SRC, doraise=True)
    print(f'استقرار انجام شد: {SRC} (بکاپ: {bak})')
    print('پایش: tail -n 60 update.log برای دو چرخه + grep G-ump-sell')


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
    r1 = run_sell_tests(mod)
    r2 = run_partial_tests(mod)
    n_fail = sum(1 for _, ok_ in r1 + r2 if not ok_)
    print(f'--- {len(r1) + len(r2) - n_fail}/{len(r1) + len(r2)} تست PASS ---')
    if n_fail:
        sys.exit(f'ABORT: {n_fail} تست FAIL — trader.py دست نخورده')
    if '--deploy' in sys.argv:
        deploy()
    else:
        print('کاندید آماده. برای استقرار: venv/bin/python apply_ump_sell_fix.py --deploy')
    return 0


if __name__ == '__main__':
    sys.exit(main())
