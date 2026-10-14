#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_fillanchor_fix.py — بهبود ۲ (G-fillanchor): SL/TP لنگر به قیمت واقعی fill
درج در گذار «خرید → پر شد»ی sync (بعد از مهر fill@):
- fill از averagePrice (fallback: price) پاسخ orders/status
- ATR از خود ردیف: (سیگنال − SL)/ضریب — بدون فراخوانی API
- ستون‌های SL/TP ردیف به‌روز + r محلی mutated → OCO همان چرخه سطوح جدید می‌گیرد
- fail-open: دادهٔ ناقص/انحراف >۲۰٪ → حفظ مقادیر سیگنال-محور
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

OLD = """            _msg = str(r[12] or '')
            if 'fill@' not in _msg:
                try:
                    ws_t.update_cell(row_num, 13, (_msg + ' | fill@' + jnow())[:250])
                except Exception:
                    pass"""

NEW = OLD + """
            # بهبود ۲ (G-fillanchor): SL/TP از قیمت واقعی fill بازمحاسبه — ریشهٔ
            # «fill روی استاپ»: SL/TP ردیف لنگر قیمت سیگنال است ولی fill پولبکی
            # ~۱٪ پایین‌تر رخ می‌دهد. ATR از خود ردیف بازیابی می‌شود
            # (ATR = (سیگنال−SL)/ضریب) — سازگار با ریسک لحظهٔ تصمیم. fail-open.
            try:
                _fill_px = parse_price(o.get('averagePrice')) or parse_price(o.get('price'))
                _p_sig = parse_price(r[5])
                _sl_old, _tp_old = parse_price(r[8]), parse_price(r[9])
                _slm = getattr(st, 'sl_atr_mult', 0) or 0
                _tpm = getattr(st, 'tp_atr_mult', 0) or 0
                if (_fill_px and _p_sig and _sl_old and _tp_old and _slm > 0
                        and _tpm > 0 and abs(_fill_px / _p_sig - 1) < 0.20
                        and _p_sig > _sl_old):
                    _atr = (_p_sig - _sl_old) / _slm
                    _sl_new = _fill_px - _slm * _atr
                    _tp_new = _fill_px + _tpm * _atr
                    if 0 < _sl_new < _fill_px < _tp_new:
                        r[8] = fmt_price(_sl_new)
                        r[9] = fmt_price(_tp_new)
                        try:
                            ws_t.update_cell(row_num, 9, r[8])
                            ws_t.update_cell(row_num, 10, r[9])
                        except Exception:
                            pass
                        log.info('G-fillanchor %s: SL %s → %s | TP %s → %s (fill=%.6g)',
                                 sym_c, fmt_price(_sl_old), r[8],
                                 fmt_price(_tp_old), r[9], _fill_px)
            except Exception:
                pass"""


def build_candidate():
    with open(SRC, encoding='utf-8') as f:
        text = f.read()
    if 'G-fillanchor' in text:
        sys.exit('ABORT: قبلاً patch شده')
    if text.count(OLD) != 1:
        sys.exit(f'ABORT: لنگر {text.count(OLD)} بار (انتظار ۱)')
    with open(CAND, 'w', encoding='utf-8') as f:
        f.write(text.replace(OLD, NEW, 1))
    print('بلوک G-fillanchor درج شد — کاندید:', CAND)


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
    def __init__(self, avg=None, matched='54.0'):
        self.avg = avg
        self.matched = matched
        self.oco_calls = []

    def order_status(self, oid):
        o = {'status': 'Done', 'matchedAmount': self.matched}
        if self.avg is not None:
            o['averagePrice'] = self.avg
            o['price'] = self.avg
        return (200, {'status': 'ok', 'order': o})

    def place_oco_sell(self, sym, vol, tp, sl, stop_limit=None):
        self.oco_calls.append((sym, float(vol), float(tp), float(sl)))
        return (200, {'status': 'ok', 'order': {'id': 11},
                      'orders': [{'id': 11}, {'id': 12}]})


def _led():
    row = ['1405/07/22 20:00', 'TST', 'خرید', '1h', 'رأی خرید', '1.05', '54',
           '10.0', '1.00', '1.20', '999', 'ثبت‌شده', "{'status': 'ok'}"]
    return {'rows': [(10, row)], 'positions': {}, 'pending': set(),
            'pending_sells': set()}


def _st():
    return types.SimpleNamespace(use_exchange_oco=True, sl_atr_mult=1.0,
                                 tp_atr_mult=3.0)


def _cell(ws, row, col):
    for r, c, v in ws.cells:
        if r == row and c == col:
            return v
    return None


def run_tests(mod):
    results = []
    mod.currency_available = lambda client, cur, use_active=True: 54.0

    def check(name, cond, extra=''):
        results.append((name, bool(cond)))
        print(('PASS' if cond else 'FAIL'), '-', name, ('| ' + extra) if (extra and not cond) else '')

    # FA1: زنجیرهٔ کامل — fill=1.0395 (−1٪) → SL/TP جدید + OCO با سطوح جدید
    # ATR = (1.05−1.00)/1.0 = 0.05 → SL=0.9895، TP=1.0395+0.15=1.1895
    fc = FakeClient(avg='1.0395')
    ws = FakeSheet()
    mod.sync_order_statuses(ws, _led(), fc, _st())
    check('FA1 وضعیت → پر شد', _cell(ws, 10, 12) == mod.ST_FILLED)
    check('FA1 مهر fill@', 'fill@' in str(_cell(ws, 10, 13)))
    sl_w = _cell(ws, 10, 9)
    tp_w = _cell(ws, 10, 10)
    check('FA1 SL ردیف = fill-محور (~0.9895)',
          sl_w is not None and abs(float(sl_w) - 0.9895) < 1e-6, str(sl_w))
    check('FA1 TP ردیف = fill-محور (~1.1895)',
          tp_w is not None and abs(float(tp_w) - 1.1895) < 1e-6, str(tp_w))
    check('FA1 OCO با سطوح جدید',
          len(fc.oco_calls) == 1 and abs(fc.oco_calls[0][3] - 0.9895) < 1e-6
          and abs(fc.oco_calls[0][2] - 1.1895) < 1e-6, str(fc.oco_calls))

    # FA2: بدون قیمت fill → fail-open (OCO با سطوح اصلی)
    fc2 = FakeClient(avg=None)
    ws2 = FakeSheet()
    mod.sync_order_statuses(ws2, _led(), fc2, _st())
    check('FA2 بدون fill-px → SL/TP دست‌نخورده',
          _cell(ws2, 10, 9) is None and _cell(ws2, 10, 10) is None)
    check('FA2 OCO با سطوح اصلی (1.20/1.00)',
          len(fc2.oco_calls) == 1 and abs(fc2.oco_calls[0][3] - 1.00) < 1e-6
          and abs(fc2.oco_calls[0][2] - 1.20) < 1e-6, str(fc2.oco_calls))

    # FA3: انحراف fill > ۲۰٪ → fail-open
    fc3 = FakeClient(avg='2.0')
    ws3 = FakeSheet()
    mod.sync_order_statuses(ws3, _led(), fc3, _st())
    check('FA3 انحراف بزرگ → SL/TP دست‌نخورده', _cell(ws3, 10, 9) is None)
    check('FA3 OCO با سطوح اصلی',
          len(fc3.oco_calls) == 1 and abs(fc3.oco_calls[0][3] - 1.00) < 1e-6)

    # FA4: st=None → بدون بازمحاسبه (و بدون OCO)
    fc4 = FakeClient(avg='1.0395')
    ws4 = FakeSheet()
    mod.sync_order_statuses(ws4, _led(), fc4, None)
    check('FA4 st=None → بدون بازمحاسبه/OCO',
          _cell(ws4, 10, 9) is None and fc4.oco_calls == [])
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
        print('کاندید آماده. برای استقرار: venv/bin/python apply_fillanchor_fix.py --deploy')
    return 0


if __name__ == '__main__':
    sys.exit(main())
