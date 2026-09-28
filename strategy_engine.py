#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
strategy_engine.py — دریافت کندل از نوبیتکس (UDF) + محاسبه سیگنال با رأی‌گیری اندیکاتورها
منطق: هر اندیکاتور فعال رأی می‌دهد (+1 خرید / -1 فروش / 0 خنثی)؛
اگر درصد آرای هم‌جهت به آستانه تنظیمات برسد → سیگنال صادر می‌شود.
حد ضرر/سود = قیمت ± ضریب × ATR (نوسان واقعی همان نماد)
"""
import logging
import time

import requests

from indicators import atr, bollinger, cci, ema, macd, obv, rsi, sma, stoch, wpr

log = logging.getLogger('nobitex-bot')

UDF_URL = 'https://apiv2.nobitex.ir/market/udf/history'
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) nobitex-sheet-updater/2.0'}

RES_MINUTES = {'1': 1, '5': 5, '15': 15, '30': 30, '60': 60, '180': 180,
               '240': 240, '360': 360, '720': 720,
               '1D': 1440, '2D': 2880, '3D': 4320}


def pint(v, d):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return d


def pflt(v, d):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def fmt_price(x):
    if x is None:
        return ''
    if x >= 1000:
        return f'{x:,.2f}'
    if x >= 1:
        return f'{x:.4f}'
    return f'{x:.8f}'


def fetch_candles(udf_symbol, resolution, lookback, retries=3):
    """دریافت کندل‌های OHLCV از API نوبیتکس؛ None یعنی شکست/بی‌داده"""
    res_min = RES_MINUTES.get(resolution)
    if res_min is None:
        log.warning('تایم‌فریم ناشناخته: %s', resolution)
        return None
    to = int(time.time())
    frm = to - int((lookback + 40) * res_min * 60)
    params = {'symbol': udf_symbol, 'resolution': resolution, 'from': frm, 'to': to}
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(UDF_URL, params=params, headers=HEADERS, timeout=60)
            d = r.json()
            if d.get('s') == 'ok' and d.get('t'):
                return {'t': d['t'], 'o': d['o'], 'h': d['h'],
                        'l': d['l'], 'c': d['c'], 'v': d['v']}
            if d.get('s') == 'error':
                log.warning('UDF بدون داده برای %s %s: %s',
                            udf_symbol, resolution, d.get('errmsg'))
                return None
            last_err = str(d)[:120]
        except (requests.RequestException, ValueError) as e:
            last_err = str(e)
        if attempt < retries:
            time.sleep(8 * attempt)
    log.error('دریافت کندل %s %s ناموفق: %s', udf_symbol, resolution, last_err)
    return None


def analyze(c, st):
    """محاسبه همه اندیکاتورهای فعال + رأی‌گیری + حد ضرر/سود"""
    closes, highs, lows, vols = c['c'], c['h'], c['l'], c['v']
    n = len(closes)
    price = closes[-1]
    out = {'price': fmt_price(price), 'trend': '—', 'signal': '—', 'strength': 0,
           'buy': 0, 'sell': 0, 'neutral': 0, 'sl': '', 'tp': '', 'note': ''}
    if n < 35:
        out['note'] = f'داده ناکافی ({n} کندل)'
        return out

    ind = st.indicators
    votes = []

    def add(name, v, reason):
        votes.append((name, v, reason))

    # ---------- رأی اندیکاتورها ----------
    if ind.get('SMA', {}).get('enabled'):
        pp = ind['SMA'].get('params', {})
        f_, s_ = pint(pp.get('fast'), 20), pint(pp.get('slow'), 50)
        fa, sl2 = sma(closes, f_), sma(closes, s_)
        if fa[-1] is not None and sl2[-1] is not None:
            up = fa[-1] > sl2[-1]
            add('SMA', 1 if up else -1,
                f'SMA{f_} {"بالاتر از" if up else "پایین‌تر از"} SMA{s_}')
        else:
            add('SMA', 0, 'داده کافی نیست')

    if ind.get('EMA', {}).get('enabled'):
        pp = ind['EMA'].get('params', {})
        f_, s_ = pint(pp.get('fast'), 9), pint(pp.get('slow'), 21)
        fa, sl2 = ema(closes, f_), ema(closes, s_)
        if fa[-1] is not None and sl2[-1] is not None:
            up = fa[-1] > sl2[-1]
            add('EMA', 1 if up else -1,
                f'EMA{f_} {"بالاتر از" if up else "پایین‌تر از"} EMA{s_}')
        else:
            add('EMA', 0, 'داده کافی نیست')

    if ind.get('RSI', {}).get('enabled'):
        pp = ind['RSI'].get('params', {})
        p_ = pint(pp.get('period'), 14)
        os_ = pflt(pp.get('oversold'), 30)
        ob_ = pflt(pp.get('overbought'), 70)
        rr = rsi(closes, p_)
        if rr[-1] is not None:
            v = rr[-1]
            if v < os_:
                add('RSI', 1, f'RSI={v:.0f} اشباع فروش')
            elif v > ob_:
                add('RSI', -1, f'RSI={v:.0f} اشباع خرید')
            else:
                add('RSI', 0, f'RSI={v:.0f}')
        else:
            add('RSI', 0, 'داده کافی نیست')

    if ind.get('MACD', {}).get('enabled'):
        pp = ind['MACD'].get('params', {})
        f_, s_, g_ = pint(pp.get('fast'), 12), pint(pp.get('slow'), 26), pint(pp.get('signal'), 9)
        line, sig, _ = macd(closes, f_, s_, g_)
        if line[-1] is not None and sig[-1] is not None:
            up = line[-1] > sig[-1]
            add('MACD', 1 if up else -1,
                'MACD بالای خط سیگنال' if up else 'MACD زیر خط سیگنال')
        else:
            add('MACD', 0, 'داده کافی نیست')

    if ind.get('BB', {}).get('enabled'):
        pp = ind['BB'].get('params', {})
        p_ = pint(pp.get('period'), 20)
        sd_ = pflt(pp.get('std'), 2.0)
        mid, up_b, lo_b = bollinger(closes, p_, sd_)
        if lo_b[-1] is not None:
            if price < lo_b[-1]:
                add('BB', 1, 'قیمت زیر باند پایین بولینگر')
            elif price > up_b[-1]:
                add('BB', -1, 'قیمت بالای باند بالای بولینگر')
            else:
                add('BB', 0, 'قیمت داخل باندها')
        else:
            add('BB', 0, 'داده کافی نیست')

    if ind.get('STOCH', {}).get('enabled'):
        pp = ind['STOCH'].get('params', {})
        k_p, d_p, sm_ = pint(pp.get('k'), 14), pint(pp.get('d'), 3), pint(pp.get('smooth'), 3)
        kk, dd = stoch(highs, lows, closes, k_p, d_p, sm_)
        if kk[-1] is not None and dd[-1] is not None:
            if kk[-1] < 20 and kk[-1] > dd[-1]:
                add('STOCH', 1, f'%K={kk[-1]:.0f} اشباع فروش در حال چرخش')
            elif kk[-1] > 80 and kk[-1] < dd[-1]:
                add('STOCH', -1, f'%K={kk[-1]:.0f} اشباع خرید در حال چرخش')
            else:
                add('STOCH', 0, f'%K={kk[-1]:.0f}')
        else:
            add('STOCH', 0, 'داده کافی نیست')

    if ind.get('OBV', {}).get('enabled'):
        pp = ind['OBV'].get('params', {})
        p_ = pint(pp.get('period'), 20)
        o = obv(closes, vols)
        if n > p_ and o[-1] is not None and o[-1 - p_] is not None:
            if o[-1] > o[-1 - p_]:
                add('OBV', 1, 'OBV صعودی — حجم تأییدکننده خرید')
            elif o[-1] < o[-1 - p_]:
                add('OBV', -1, 'OBV نزولی — حجم تأییدکننده فروش')
            else:
                add('OBV', 0, 'OBV بدون تغییر')
        else:
            add('OBV', 0, 'داده کافی نیست')

    if ind.get('CCI', {}).get('enabled'):
        pp = ind['CCI'].get('params', {})
        p_ = pint(pp.get('period'), 20)
        cc = cci(highs, lows, closes, p_)
        if cc[-1] is not None:
            if cc[-1] < -100:
                add('CCI', 1, f'CCI={cc[-1]:.0f} اشباع فروش')
            elif cc[-1] > 100:
                add('CCI', -1, f'CCI={cc[-1]:.0f} اشباع خرید')
            else:
                add('CCI', 0, f'CCI={cc[-1]:.0f}')
        else:
            add('CCI', 0, 'داده کافی نیست')

    if ind.get('WPR', {}).get('enabled'):
        pp = ind['WPR'].get('params', {})
        p_ = pint(pp.get('period'), 14)
        ww = wpr(highs, lows, closes, p_)
        if ww[-1] is not None:
            if ww[-1] < -80:
                add('WPR', 1, f'%R={ww[-1]:.0f} اشباع فروش')
            elif ww[-1] > -20:
                add('WPR', -1, f'%R={ww[-1]:.0f} اشباع خرید')
            else:
                add('WPR', 0, f'%R={ww[-1]:.0f}')
        else:
            add('WPR', 0, 'داده کافی نیست')

    # ---------- ATR — همیشه محاسبه می‌شود (زیرساخت حد ضرر/سود) ----------
    p_atr = pint(ind.get('ATR', {}).get('params', {}).get('period'), 14)
    a = atr(highs, lows, closes, p_atr)

    # ---------- روند (نمایشی) ----------
    trend = '—'
    if ind.get('SMA', {}).get('enabled'):
        pp = ind['SMA'].get('params', {})
        f_, s_ = pint(pp.get('fast'), 20), pint(pp.get('slow'), 50)
        fa, sl2 = sma(closes, f_), sma(closes, s_)
        if fa[-1] is not None and sl2[-1] is not None:
            trend = 'صعودی' if fa[-1] > sl2[-1] else 'نزولی'
    elif ind.get('EMA', {}).get('enabled'):
        pp = ind['EMA'].get('params', {})
        f_, s_ = pint(pp.get('fast'), 9), pint(pp.get('slow'), 21)
        fa, sl2 = ema(closes, f_), ema(closes, s_)
        if fa[-1] is not None and sl2[-1] is not None:
            trend = 'صعودی' if fa[-1] > sl2[-1] else 'نزولی'
    else:
        m20 = sma(closes, 20)
        if m20[-1] is not None:
            trend = 'صعودی' if closes[-1] > m20[-1] else 'نزولی'
    out['trend'] = trend

    # ---------- شمارش آرا و صدور سیگنال ----------
    b = sum(1 for _, v, _ in votes if v == 1)
    s_ = sum(1 for _, v, _ in votes if v == -1)
    nn = sum(1 for _, v, _ in votes if v == 0)
    out['buy'], out['sell'], out['neutral'] = b, s_, nn
    total = len(votes)
    if total == 0:
        out['signal'] = 'خنثی'
        out['note'] = 'هیچ اندیکاتور رأی‌دهنده‌ای فعال نیست'
    else:
        bp, sp = b / total * 100.0, s_ / total * 100.0
        thr = st.threshold_pct
        if bp >= thr:
            out['signal'], out['strength'] = 'خرید', round(bp)
        elif sp >= thr:
            out['signal'], out['strength'] = 'فروش', round(sp)
        else:
            out['signal'], out['strength'] = 'خنثی', round(max(bp, sp))
        active = [f'{nm}: {rs}' for nm, v, rs in votes if v != 0]
        out['note'] = ('؛ '.join(active))[:250] if active else 'همه اندیکاتورها خنثی'

    # ---------- حد ضرر / حد سود ----------
    if a[-1] is not None:
        out['sl'] = fmt_price(price - st.sl_atr_mult * a[-1])
        out['tp'] = fmt_price(price + st.tp_atr_mult * a[-1])
    return out
