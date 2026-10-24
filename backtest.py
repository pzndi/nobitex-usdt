#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest.py — چرخه بک‌تست (هر INTERVAL_BACKTEST_MIN دقیقه)
فاز ۳ — سخت‌گیری بک‌تست:
  - مدل هزینه واقعی (اندازه‌گیری‌شده از fillهای واقعی): کارمزد رفت‌وبرگشت
    روی همه معاملات + اسلپیج استاپ‌لیمیتی فقط روی خروج‌های استاپ
  - داخل کندل محافظه‌کارانه: اگر SL و TP هر دو در بازه کندل باشند، SL اول
  - MIN_TRADES آماری معنادار + اعتبارسنجی روی ۳۰٪ آخر داده (unseen):
    پارامتر فقط وقتی پذیرفته می‌شود که روی داده آموزش بهترین باشد «و»
    روی holdout هم سود خالص بدهد؛ در غیر این صورت نماد بدون پارامتر
    می‌ماند و چرخه سیگنال از پیش‌فرض شیت استفاده می‌کند.
  - آستانه سیگنال: پیش‌فرض = مقدار شیت (SIGNAL_THRESHOLD_PCT) برای همه
    نمادها (OPTIMIZE_THRESHOLD=False). تحمیل per-symbol با True فعال می‌شود.
"""
import logging
import time

import gspread

import strategy_engine as se

log = logging.getLogger('nobitex-bot')

BT_TAB = 'بک تست'
# P2: پارامترهای بک‌تست از تب تنظیمات (BT_*) — پیش‌فرض‌ها = مقادیر قبلی کد
FEE_RT_PCT_DEFAULT = 0.25    # فقط پیش‌فرضِ امضای simulate برای فراخوانی مستقیم
SL_SLIP_PCT_DEFAULT = 0.35

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


def simulate(v, c, thr, slm, tpm, i0, i1,
             fee_pct=FEE_RT_PCT_DEFAULT, slip_pct=SL_SLIP_PCT_DEFAULT):
    """شبیه‌سازی روی کندل‌های [i0, i1) با مدل هزینه — خروجی: PnL خالص هر معامله"""
    closes, highs, lows = c['c'], c['h'], c['l']
    trades = []
    in_pos = False
    entry = sl = tp = 0.0
    fee = fee_pct / 100.0
    slip = slip_pct / 100.0
    for i in range(i0, i1):
        p = closes[i]
        tot = v['buy'][i] + v['sell'][i] + v['neutral'][i]
        if not in_pos:
            if tot and v['buy'][i] / tot * 100.0 >= thr and v['atr'][i]:
                entry, sl, tp = p, p - slm * v['atr'][i], p + tpm * v['atr'][i]
                in_pos = True
        else:
            # محافظه‌کارانه: کندلی که هر دو بازه SL و TP را دارد → SL اول
            if lows[i] <= sl:
                trades.append((sl * (1 - slip) - entry) / entry - fee)
                in_pos = False
            elif highs[i] >= tp:
                trades.append((tp - entry) / entry - fee)
                in_pos = False
            elif tot and v['sell'][i] / tot * 100.0 >= thr:
                trades.append((p - entry) / entry - fee)
                in_pos = False
    if in_pos and i1 > i0:
        trades.append((closes[i1 - 1] - entry) / entry - fee)
    return trades


def backtest_symbol(st, sym):
    lookback, warmup = st.bt_lookback, st.bt_warmup
    c = se.fetch_candles(sym + 'USDT', st.backtest_timeframe, lookback)
    if not c or len(c['c']) < warmup + 60:
        return None
    v = se.prepare_votes(c, st)
    n = len(c['c'])
    split = int(n * (1 - st.bt_holdout))
    thr_grid = st.bt_threshold_grid if st.bt_optimize_threshold else [st.threshold_pct]
    best = None
    for thr in thr_grid:
        for slm in st.bt_sl_mults:
            for tpm in st.bt_tp_mults:
                tr_train = simulate(v, c, thr, slm, tpm, warmup, split,
                                    fee_pct=st.bt_fee_rt_pct, slip_pct=st.bt_sl_slip_pct)
                if len(tr_train) < st.bt_min_trades:
                    continue
                pnl_train = sum(tr_train) * 100.0
                if best is None or pnl_train > best['pnl_train']:
                    best = {'thr': thr, 'slm': slm, 'tpm': tpm,
                            'trades': len(tr_train),
                            'wins': sum(1 for t in tr_train if t > 0),
                            'pnl_train': pnl_train}
    if best is None:
        return None
    # اعتبارسنجی روی داده unseen — همان پارامترها باید آنجا هم سود خالص بدهند
    tr_test = simulate(v, c, best['thr'], best['slm'], best['tpm'], split, n,
                       fee_pct=st.bt_fee_rt_pct, slip_pct=st.bt_sl_slip_pct)
    best['pnl_test'] = sum(tr_test) * 100.0
    if len(tr_test) < st.bt_min_test_trades or best['pnl_test'] <= 0:
        return None
    best['pnl'] = best['pnl_train']   # سازگاری با ستون «بازده کل ٪» شیت
    return best


def run(sh, st, symbols):
    """اجرای کامل بک‌تست؛ خروجی: {نماد: پارامترهای معتبر} — نماد بدون لبه در خروجی نیست"""
    results = {}
    rows = []
    for sym in symbols:
        best = backtest_symbol(st, sym)
        if best:
            results[sym] = best
            rows.append([sym, st.backtest_timeframe, best['trades'], best['wins'],
                         round(best['wins'] * 100 / best['trades']),
                         round(best['pnl'], 2),
                         best['thr'], best['slm'], best['tpm'],
                         '✓ آزمون %+.1f٪' % best['pnl_test'], ''])
        else:
            rows.append([sym, st.backtest_timeframe, '', '', '', '',
                         st.threshold_pct, '', '',
                         'بدون لبه معتبر — پیش‌فرض شیت', ''])
        time.sleep(0.2)

    try:
        ws = sh.worksheet(BT_TAB)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=BT_TAB, rows=60, cols=12)
        ws.update(values=[['نماد', 'تایم‌فریم', 'تعداد معامله', 'بردها', 'نرخ برد ٪',
                           'بازده خالص ٪', 'آستانه', 'SL×ATR', 'TP×ATR',
                           'وضعیت', 'به‌روزرسانی']], range_name='A3:K3')
        ws.freeze(rows=3)

    n = max(20, len(rows) + 4)
    data = [r + [''] * (11 - len(r)) for r in rows] + [[''] * 11] * (n - len(rows))
    ws.update(values=[['🧪 بک‌تست با مدل هزینه واقعی (کارمزد+اسلپیج) و اعتبارسنجی holdout — '
                       'پارامتر فقط با سود خالص روی داده unseen پذیرفته می‌شود',
                       'به‌روزرسانی:', jnow()]], range_name='A1:C1')
    ws.update(values=data, range_name=f'A4:K{3 + n}')
    log.info('تب «بک تست» به‌روزرسانی شد — %d نماد با لبه معتبر', len(results))
    return results
