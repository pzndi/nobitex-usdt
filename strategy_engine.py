#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
strategy_engine.py — دریافت کندل از نوبیتکس (UDF) + آرای اندیکاتورها
دو کاربرد مشترک:
  analyze()       → تحلیل لحظه‌ای آخرین کندل (با پارامترهای قابل‌تحمیل از بک‌تست)
  prepare_votes() → سری کامل آرای هر کندل — مبنای بک‌تست
حد ضرر/سود = قیمت ± ضریب × ATR
"""
import logging
import time

import requests

from indicators import atr, bollinger, cci, ema, macd, obv, rsi, sma, stoch, wpr

log = logging.getLogger('nobitex-bot')

UDF_URL = 'https://apiv2.nobitex.ir/market/udf/history'
HEADERS = {'User-Agent': 'TraderBot/NobitexSheetBot-2.0'}

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


def prepare_votes(c, st):
    """آرای همه اندیکاتورهای فعال به‌صورت سری زمانی (طول = تعداد کندل)"""
    closes, highs, lows, vols = c['c'], c['h'], c['l'], c['v']
    n = len(closes)
    V = {'buy': [0] * n, 'sell': [0] * n, 'neutral': [0] * n,
         'note': [''] * n, 'trend': ['—'] * n, 'atr': [None] * n}
    ind = st.indicators

    def addf(i, v, note):
        if v == 1:
            V['buy'][i] += 1
        elif v == -1:
            V['sell'][i] += 1
        else:
            V['neutral'][i] += 1
        if v != 0 and note:
            V['note'][i] = (V['note'][i] + '؛ ' + note if V['note'][i] else note)[:250]

    trend_f = trend_s = None

    if ind.get('SMA', {}).get('enabled'):
        pp = ind['SMA'].get('params', {})
        f_, s_ = pint(pp.get('fast'), 20), pint(pp.get('slow'), 50)
        fa, sl2 = sma(closes, f_), sma(closes, s_)
        trend_f, trend_s = fa, sl2
        for i in range(n):
            if fa[i] is not None and sl2[i] is not None:
                up = fa[i] > sl2[i]
                addf(i, 1 if up else -1,
                     f'SMA{f_} {"بالاتر از" if up else "پایین‌تر از"} SMA{s_}')
            else:
                addf(i, 0, '')

    if ind.get('EMA', {}).get('enabled'):
        pp = ind['EMA'].get('params', {})
        f_, s_ = pint(pp.get('fast'), 9), pint(pp.get('slow'), 21)
        fa, sl2 = ema(closes, f_), ema(closes, s_)
        if trend_f is None:
            trend_f, trend_s = fa, sl2
        for i in range(n):
            if fa[i] is not None and sl2[i] is not None:
                up = fa[i] > sl2[i]
                addf(i, 1 if up else -1,
                     f'EMA{f_} {"بالاتر از" if up else "پایین‌تر از"} EMA{s_}')
            else:
                addf(i, 0, '')

    if ind.get('RSI', {}).get('enabled'):
        pp = ind['RSI'].get('params', {})
        p_ = pint(pp.get('period'), 14)
        os_ = pflt(pp.get('oversold'), 30)
        ob_ = pflt(pp.get('overbought'), 70)
        rr = rsi(closes, p_)
        for i in range(n):
            if rr[i] is not None:
                if rr[i] < os_:
                    addf(i, 1, f'RSI={rr[i]:.0f} اشباع فروش')
                elif rr[i] > ob_:
                    addf(i, -1, f'RSI={rr[i]:.0f} اشباع خرید')
                else:
                    addf(i, 0, '')
            else:
                addf(i, 0, '')

    if ind.get('MACD', {}).get('enabled'):
        pp = ind['MACD'].get('params', {})
        f_, s_, g_ = pint(pp.get('fast'), 12), pint(pp.get('slow'), 26), pint(pp.get('signal'), 9)
        line, sig, _ = macd(closes, f_, s_, g_)
        for i in range(n):
            if line[i] is not None and sig[i] is not None:
                up = line[i] > sig[i]
                addf(i, 1 if up else -1,
                     'MACD بالای خط سیگنال' if up else 'MACD زیر خط سیگنال')
            else:
                addf(i, 0, '')

    if ind.get('BB', {}).get('enabled'):
        pp = ind['BB'].get('params', {})
        p_ = pint(pp.get('period'), 20)
        sd_ = pflt(pp.get('std'), 2.0)
        mid, up_b, lo_b = bollinger(closes, p_, sd_)
        for i in range(n):
            if lo_b[i] is not None:
                if closes[i] < lo_b[i]:
                    addf(i, 1, 'قیمت زیر باند پایین بولینگر')
                elif closes[i] > up_b[i]:
                    addf(i, -1, 'قیمت بالای باند بالای بولینگر')
                else:
                    addf(i, 0, '')
            else:
                addf(i, 0, '')

    if ind.get('STOCH', {}).get('enabled'):
        pp = ind['STOCH'].get('params', {})
        k_p, d_p, sm_ = pint(pp.get('k'), 14), pint(pp.get('d'), 3), pint(pp.get('smooth'), 3)
        kk, dd = stoch(highs, lows, closes, k_p, d_p, sm_)
        for i in range(n):
            if kk[i] is not None and dd[i] is not None:
                if kk[i] < 20 and kk[i] > dd[i]:
                    addf(i, 1, f'%K={kk[i]:.0f} اشباع فروش در حال چرخش')
                elif kk[i] > 80 and kk[i] < dd[i]:
                    addf(i, -1, f'%K={kk[i]:.0f} اشباع خرید در حال چرخش')
                else:
                    addf(i, 0, '')
            else:
                addf(i, 0, '')

    if ind.get('OBV', {}).get('enabled'):
        pp = ind['OBV'].get('params', {})
        p_ = pint(pp.get('period'), 20)
        o = obv(closes, vols)
        for i in range(n):
            j = i - p_
            if j >= 0:
                if o[i] > o[j]:
                    addf(i, 1, 'OBV صعودی — حجم تأییدکننده خرید')
                elif o[i] < o[j]:
                    addf(i, -1, 'OBV نزولی — حجم تأییدکننده فروش')
                else:
                    addf(i, 0, '')
            else:
                addf(i, 0, '')

    if ind.get('CCI', {}).get('enabled'):
        pp = ind['CCI'].get('params', {})
        p_ = pint(pp.get('period'), 20)
        cc = cci(highs, lows, closes, p_)
        for i in range(n):
            if cc[i] is not None:
                if cc[i] < -100:
                    addf(i, 1, f'CCI={cc[i]:.0f} اشباع فروش')
                elif cc[i] > 100:
                    addf(i, -1, f'CCI={cc[i]:.0f} اشباع خرید')
                else:
                    addf(i, 0, '')
            else:
                addf(i, 0, '')

    if ind.get('WPR', {}).get('enabled'):
        pp = ind['WPR'].get('params', {})
        p_ = pint(pp.get('period'), 14)
        ww = wpr(highs, lows, closes, p_)
        for i in range(n):
            if ww[i] is not None:
                if ww[i] < -80:
                    addf(i, 1, f'%R={ww[i]:.0f} اشباع فروش')
                elif ww[i] > -20:
                    addf(i, -1, f'%R={ww[i]:.0f} اشباع خرید')
                else:
                    addf(i, 0, '')
            else:
                addf(i, 0, '')

    # ── پاس اصلاحی RSI شرطی ──
    # RSI فقط هم‌جهت روند رأی می‌دهد؛ خلاف روند → خنثی
    trend_ref_f, trend_ref_s = None, None
    if ind.get('SMA', {}).get('enabled'):
        pp = ind['SMA'].get('params', {})
        trend_ref_f = sma(closes, pint(pp.get('fast'), 20))
        trend_ref_s = sma(closes, pint(pp.get('slow'), 50))
    elif ind.get('EMA', {}).get('enabled'):
        pp = ind['EMA'].get('params', {})
        trend_ref_f = ema(closes, pint(pp.get('fast'), 9))
        trend_ref_s = ema(closes, pint(pp.get('slow'), 21))
    if trend_ref_f is not None and ind.get('RSI', {}).get('enabled'):
        pp = ind['RSI'].get('params', {})
        p_ = pint(pp.get('period'), 14)
        os_ = pflt(pp.get('oversold'), 30)
        ob_ = pflt(pp.get('overbought'), 70)
        rr = rsi(closes, p_)
        for i in range(n):
            if rr[i] is None or trend_ref_f[i] is None or trend_ref_s[i] is None:
                continue
            rsi_vote = 1 if rr[i] < os_ else (-1 if rr[i] > ob_ else 0)
            if rsi_vote == 0:
                continue
            trend_up = trend_ref_f[i] > trend_ref_s[i]
            if (rsi_vote == -1 and trend_up) or (rsi_vote == 1 and not trend_up):
                V['sell'][i] -= 1
                V['neutral'][i] += 1
                V['note'][i] = (V['note'][i].replace(f'RSI={rr[i]:.0f} اشباع خرید؛ ', '')
                                .replace(f'RSI={rr[i]:.0f} اشباع خرید', '')
                                .replace(f'RSI={rr[i]:.0f} اشباع فروش؛ ', '')
                                .replace(f'RSI={rr[i]:.0f} اشباع فروش', '')
                                + f'؛ RSI={rr[i]:.0f} خنثی (خلاف روند)').strip('؛ ')

    # ATR — زیرساخت حد ضرر/سود (رأی ندارد)
    p_atr = pint(ind.get('ATR', {}).get('params', {}).get('period'), 14)
    V['atr'] = atr(highs, lows, closes, p_atr)

    for i in range(n):
        if trend_f is not None and trend_f[i] is not None and trend_s[i] is not None:
            V['trend'][i] = 'صعودی' if trend_f[i] > trend_s[i] else 'نزولی'
    return V


def analyze(c, st, thr=None, slm=None, tpm=None, atr_ref=None):
    """تحلیل لحظه‌ای آخرین کندل؛ thr/slm/tpm اختیاری = تحمیل استراتژی بک‌تست همان نماد"""
    closes = c['c']
    n = len(closes)
    price = closes[-1]
    out = {'price': fmt_price(price), 'trend': '—', 'signal': '—', 'strength': 0,
           'buy': 0, 'sell': 0, 'neutral': 0, 'sl': '', 'tp': '', 'note': ''}
    if n < 35:
        out['note'] = f'داده ناکافی ({n} کندل)'
        return out

    v = prepare_votes(c, st)
    i = n - 1
    b, s_, nn = v['buy'][i], v['sell'][i], v['neutral'][i]
    out['buy'], out['sell'], out['neutral'] = b, s_, nn
    out['trend'] = v['trend'][i]
    total = b + s_ + nn
    thr_eff = thr if thr is not None else st.threshold_pct
    if total == 0:
        out['signal'] = 'خنثی'
        out['note'] = 'هیچ اندیکاتور رأی‌دهنده‌ای فعال نیست'
    else:
        bp, sp = b / total * 100.0, s_ / total * 100.0
        if bp >= thr_eff:
            out['signal'], out['strength'] = 'خرید', round(bp)
        elif sp >= thr_eff:
            out['signal'], out['strength'] = 'فروش', round(sp)
        else:
            out['signal'], out['strength'] = 'خنثی', round(max(bp, sp))
        out['note'] = v['note'][i] or 'همه اندیکاتورها خنثی'

    # ATR: مرجع (اگر از بیرون داده شود) یا همان تایم‌فریم تحلیل
    a = atr_ref if atr_ref is not None else v['atr'][i]
    slm_eff = slm if slm is not None else st.sl_atr_mult
    tpm_eff = tpm if tpm is not None else st.tp_atr_mult
    if a is not None:
        out['sl'] = fmt_price(price - slm_eff * a)
        out['tp'] = fmt_price(price + tpm_eff * a)
    return out
