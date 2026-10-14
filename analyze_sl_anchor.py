#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_sl_anchor.py — P2-2: SL لنگر سیگنال vs قیمت fill (فقط-خواندن، فقط شیت)
جفت‌کردن: آخرین خریدِ اجراشدهٔ نماد قبل از زمان خروج (ربات تک‌پوزیشن/نماد).
"""
import sys

import net_timeout  # noqa: F401

import gspread
import jdatetime
from settings import load_env

EXECUTED = {'پر شد', 'بخشی پر و لغو شد'}


def _f(v):
    try:
        return float(str(v).replace(',', ''))
    except (TypeError, ValueError):
        return None


def _t(v):
    try:
        return jdatetime.datetime.strptime(str(v).strip(), '%Y/%m/%d %H:%M')
    except (ValueError, TypeError):
        return None


def _dur_h(s):
    d = _f(s)
    return d if d is not None else None


def stats(sub):
    if not sub:
        return 'n=0'
    n = len(sub)
    wins = [t for t in sub if (t['pnl'] or 0) > 0]
    pnl = sum(t['pnl'] or 0 for t in sub)
    return f'n={n:3d} | WR={100.0 * len(wins) / n:5.1f}% | P&L={pnl:+7.2f}'


def main():
    sheet_id = load_env().get('SHEET_ID')
    if not sheet_id:
        sys.exit('SHEET_ID یافت نشد')
    gc = gspread.service_account(filename='service_account.json')
    sh = gc.open_by_key(sheet_id)

    buys = []
    for r in sh.worksheet('سفارشات').get_all_values()[3:]:
        if len(r) < 12 or str(r[2]).strip() != 'خرید':
            continue
        if str(r[11]).strip() not in EXECUTED:
            continue
        t, sig, sl, tp = _t(r[0]), _f(r[5]), _f(r[8]), _f(r[9])
        if t and sig and sl:
            buys.append((t, str(r[1]).strip().upper(), sig, sl, tp))
    buys.sort(key=lambda x: x[0])

    trades, skipped = [], 0
    for r in sh.worksheet('اتمام معاملات').get_all_values()[1:]:
        if len(r) < 8:
            continue
        sym = str(r[1]).strip().upper()
        xt = _t(r[0])
        entry, exitp, pnl = _f(r[3]), _f(r[4]), _f(r[6])
        if not (xt and sym and entry):
            continue
        if len(r) > 10 and str(r[10]).strip() == 'شبیه‌سازی':
            continue
        cand = None
        for b in buys:
            if b[1] == sym and b[0] <= xt:
                cand = b
        if cand is None:
            skipped += 1
            continue
        _, _, sig, sl, tp = cand
        fill_gap = (entry / sig - 1) * 100.0
        sl_buf = (entry - sl) / entry * 100.0
        tp_buf = ((tp - entry) / entry * 100.0) if (tp and entry) else None
        stopped = exitp is not None and exitp <= sl * 1.002
        trades.append({'sym': sym, 'xt': xt, 'fill_gap': fill_gap, 'sl_buf': sl_buf,
                       'tp_buf': tp_buf, 'pnl': pnl, 'stopped': stopped,
                       'reason': str(r[8]).strip()[:34],
                       'dur': _dur_h(r[9]) if len(r) > 9 else None})

    print(f'معاملات تحلیل‌شده: {len(trades)} | بدون تطبیق: {skipped} | خریدهای اجراشده: {len(buys)}')

    pull = [t for t in trades if t['fill_gap'] <= -0.5]
    near = [t for t in trades if t['fill_gap'] > -0.5]
    print('=== رژیم ورود (fill_gap) ===')
    print(f'  پولبکی (fill ≤ −0.5٪):  {stats(pull)}')
    print(f'  نزدیک/مارکت:            {stats(near)}')

    print('=== بافر SL نسبت به ورود واقعی (٪) ===')
    for lo, hi in ((0.0, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 5.0), (5.0, 999.0)):
        sub = [t for t in trades if lo <= t['sl_buf'] < hi]
        if not sub:
            continue
        st = sum(1 for t in sub if t['stopped'])
        qk = sum(1 for t in sub if t['dur'] is not None and t['dur'] < 1)
        print(f'  [{lo:4.1f}–{hi:5.1f}): {stats(sub)} | استاپ={st} | خروج<1h={qk}')

    tiny = [t for t in trades if t['sl_buf'] < 0.5]
    print(f'=== الگوی XRP (بافر SL < 0.5٪): {stats(tiny)} ===')

    print('=== ۴۰ معاملهٔ آخر ===')
    for t in trades[-40:]:
        dur = f"{t['dur']:.1f}" if t['dur'] is not None else '  —'
        print(f"{t['sym']:6} | {t['xt']} | fill={t['fill_gap']:+5.2f}% | "
              f"SLbuf={t['sl_buf']:5.2f}% | TPbuf={(t['tp_buf'] or 0):6.2f}% | "
              f"P&L={(t['pnl'] or 0):+6.2f} | {'STOP' if t['stopped'] else '    '} | "
              f"{dur:>5}h | {t['reason']}")
    print('تحفظ‌ها: entry بسته‌ها پر-N7 (دورهٔ جدید)؛ خروج‌های جزئی چندردیفی به یک خرید map می‌شوند؛ '
          'ستون مدت مبنای زمان ثبت است نه fill.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
