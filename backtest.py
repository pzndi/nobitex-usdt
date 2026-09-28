#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest.py — چرخه بک‌تست (هر INTERVAL_BACKTEST_MIN دقیقه)
برای هر نماد تاپ‌۱۰، تاریخچه نوبیتکس (تا ۴۸۰ کندل) گرفته می‌شود؛
شبیه‌سازی ورود/خروج روی گرید پارامترها انجام و بهترین ترکیب
(آستانه سیگنال × ضریب SL × ضریب TP) برای هر نماد انتخاب می‌شود.
خروجی: تب «بک تست» + دیکشنری پارامترها که چرخه سیگنال برای همان نماد اعمال می‌کند.
"""
import logging
import time

import gspread

import strategy_engine as se

log = logging.getLogger('nobitex-bot')

BT_TAB = 'بک تست'
THRESHOLDS = [50, 60, 70, 80]      # آستانه درصد آرای خرید/فروش
SL_MULTS = [1.5, 2.0, 2.5]         # ضریب حد ضرر × ATR
TP_MULTS = [2.0, 3.0, 4.0]         # ضریب حد سود × ATR
MIN_TRADES = 2
WARMUP = 60
LOOKBACK = 480                      # سقف API نوبیتکس: ۵۰۰ کندل

try:
    import datetime as _dt
    import jdatetime
    _TEHRAN = _dt.timedelta(hours=3, minutes=30)

    def jnow():
        g = (_dt.datetime.now(_dt.timezone.utc) + _TEHRAN).replace(tzinfo=None)
        return jdatetime.datetime.fromgregorian(datetime=g).strftime('%Y/%m/%d %H:%M')
except ImportError:
    from datetime import datetime, timedelta, timezone

    def jnow():
        return (datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)).strftime('%Y-%m-%d %H:%M')


def simulate(v, c, thr, slm, tpm):
    """شبیه‌سازی: ورود با آستانه آرای خرید، خروج با TP/SL یا سیگنال فروش معکوس"""
    closes, highs, lows = c['c'], c['h'], c['l']
    n = len(closes)
    trades = []
    in_pos = False
    entry = sl = tp = 0.0
    for i in range(WARMUP, n):
        p = closes[i]
        tot = v['buy'][i] + v['sell'][i] + v['neutral'][i]
        if not in_pos:
            if tot and v['buy'][i] / tot * 100.0 >= thr and v['atr'][i]:
                entry, sl, tp = p, p - slm * v['atr'][i], p + tpm * v['atr'][i]
                in_pos = True
        else:
            if highs[i] >= tp:
                trades.append((tp - entry) / entry)
                in_pos = False
            elif lows[i] <= sl:
                trades.append((sl - entry) / entry)
                in_pos = False
            elif tot and v['sell'][i] / tot * 100.0 >= thr:
                trades.append((p - entry) / entry)
                in_pos = False
    if in_pos and n > WARMUP:
        trades.append((closes[-1] - entry) / entry)
    return trades


def backtest_symbol(st, sym):
    c = se.fetch_candles(sym + 'USDT', st.backtest_timeframe, LOOKBACK)
    if not c or len(c['c']) < WARMUP + 20:
        return None
    v = se.prepare_votes(c, st)
    best = None
    for thr in THRESHOLDS:
        for slm in SL_MULTS:
            for tpm in TP_MULTS:
                tr = simulate(v, c, thr, slm, tpm)
                if len(tr) < MIN_TRADES:
                    continue
                pnl = sum(tr) * 100.0
                if best is None or pnl > best['pnl']:
                    best = {'thr': thr, 'slm': slm, 'tpm': tpm,
                            'trades': len(tr),
                            'wins': sum(1 for t in tr if t > 0),
                            'pnl': pnl}
    return best


def run(sh, st, symbols):
    """اجرای کامل بک‌تست؛ خروجی: {نماد: بهترین پارامترها}"""
    results = {}
    rows = []
    for sym in symbols:
        best = backtest_symbol(st, sym)
        if best:
            results[sym] = best
            rows.append([sym, st.backtest_timeframe, best['trades'], best['wins'],
                         round(best['wins'] * 100 / best['trades']),
                         round(best['pnl'], 2),
                         best['thr'], best['slm'], best['tpm'], '✓', ''])
        else:
            rows.append([sym, st.backtest_timeframe, '', '', '', '',
                         '', '', '', 'داده کافی نیست', ''])
        time.sleep(0.2)

    try:
        ws = sh.worksheet(BT_TAB)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=BT_TAB, rows=60, cols=12)
        ws.update(values=[['نماد', 'تایم‌فریم', 'تعداد معامله', 'بردها', 'نرخ برد ٪',
                           'بازده کل ٪', 'آستانه بهینه', 'SL×ATR', 'TP×ATR',
                           'وضعیت', 'به‌روزرسانی']], range_name='A3:K3')
        ws.freeze(rows=3)

    n = max(20, len(rows) + 4)
    data = [r + [''] * (11 - len(r)) for r in rows] + [[''] * 11] * (n - len(rows))
    ws.update(values=[['🧪 بک‌تست — بهترین استراتژی هر نماد از تاریخچه نوبیتکس '
                       '(پارامترها در چرخه سیگنال همان نماد اعمال می‌شود)',
                       'به‌روزرسانی:', jnow()]], range_name='A1:C1')
    ws.update(values=data, range_name=f'A4:K{3 + n}')
    log.info('تب «بک تست» به‌روزرسانی شد — %d نماد', len(results))
    return results
