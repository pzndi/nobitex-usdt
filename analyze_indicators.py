#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_indicators.py — عملکرد همهٔ اندیکاتورها (فقط-خواندن)
لایه ۱: پیکربندی فعال از «تنظیمات» | لایه ۲: snapshot «استراتژی»
لایه ۳: رأی هر اندیکاتور در لحظهٔ تصمیمِ هر پوزیشن بسته (آخرین کندلِ بستهٔ قبل از
         زمان ثبت سفارش — ضد look-ahead؛ dedup فرگمنت‌ها به پوزیشن)
لایه ۴: WR/P&L per رأیِ اندیکاتور + اکثریت TF (متغیر تصمیم) + ATR٪ زمینه
رأی‌دهنده‌های پشتیبانی‌شده: SMA, EMA, RSI, MACD, BB (فعال‌های شیت) + ATR زیرساخت.
"""
import calendar
import re
import sys

import net_timeout  # noqa: F401

import gspread
import jdatetime
from settings import Settings, load_env
import strategy_engine as se
from indicators import atr, bollinger, ema, macd, rsi, sma

EXECUTED = {'پر شد', 'بخشی پر و لغو شد'}
TEH = 12600  # UTC+3:30


def _f(v):
    try:
        return float(str(v).replace(',', ''))
    except (TypeError, ValueError):
        return None


def _pi(v, d):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return d


def _pf(v, d):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _epoch(tstr):
    try:
        g = jdatetime.datetime.strptime(str(tstr).strip(), '%Y/%m/%d %H:%M').togregorian()
    except (ValueError, TypeError):
        return None
    return calendar.timegm(g.timetuple()) - TEH


def _fill_epoch(msg):
    s = str(msg or '')
    if 'fill@' not in s:
        return None
    return _epoch(s.split('fill@', 1)[1][:16])


_VCACHE = {}


def votes_for(sym, res, ind):
    """سری رأی اندیکاتورهای فعال برای (نماد، TF) — کش‌شده؛ سازگار با prepare_votes"""
    key = (sym, res)
    if key in _VCACHE:
        return _VCACHE[key]
    c = se.fetch_candles(sym + 'USDT', res, 500)
    if c:
        print(f'  [کندل {sym} {res}: {len(c["c"])}]')
    out = None
    if c and len(c.get('c') or ()) >= 60:
        closes, highs, lows = c['c'], c['h'], c['l']
        n = len(closes)
        v = {'t': c['t'], 'close': closes, 'votes': {}}
        tr_f = tr_s = None
        if ind.get('SMA', {}).get('enabled'):
            p = ind['SMA'].get('params', {})
            f_, s_ = _pi(p.get('fast'), 20), _pi(p.get('slow'), 50)
            tr_f, tr_s = sma(closes, f_), sma(closes, s_)
            v['votes']['SMA'] = [(1 if tr_f[i] > tr_s[i] else -1)
                                 if (tr_f[i] is not None and tr_s[i] is not None) else 0
                                 for i in range(n)]
        if ind.get('EMA', {}).get('enabled'):
            p = ind['EMA'].get('params', {})
            f_, s_ = _pi(p.get('fast'), 9), _pi(p.get('slow'), 21)
            ef, es = ema(closes, f_), ema(closes, s_)
            v['votes']['EMA'] = [(1 if ef[i] > es[i] else -1)
                                 if (ef[i] is not None and es[i] is not None) else 0
                                 for i in range(n)]
        if tr_f is None and ind.get('EMA', {}).get('enabled'):
            p = ind['EMA'].get('params', {})
            tr_f, tr_s = ema(closes, _pi(p.get('fast'), 9)), ema(closes, _pi(p.get('slow'), 21))
        if ind.get('RSI', {}).get('enabled'):
            p = ind['RSI'].get('params', {})
            p_, os_, ob_ = (_pi(p.get('period'), 14), _pf(p.get('oversold'), 30),
                            _pf(p.get('overbought'), 70))
            rr = rsi(closes, p_)
            col = []
            for i in range(n):
                vote = 0
                if rr[i] is not None:
                    vote = 1 if rr[i] < os_ else (-1 if rr[i] > ob_ else 0)
                if (vote != 0 and tr_f is not None and tr_s is not None
                        and tr_f[i] is not None and tr_s[i] is not None):
                    trend_up = tr_f[i] > tr_s[i]
                    if (vote == -1 and trend_up) or (vote == 1 and not trend_up):
                        vote = 0  # تصحیح RSI خلاف روند — مطابق prepare_votes
                col.append(vote)
            v['votes']['RSI'] = col
        if ind.get('MACD', {}).get('enabled'):
            p = ind['MACD'].get('params', {})
            f_, s_, g_ = _pi(p.get('fast'), 12), _pi(p.get('slow'), 26), _pi(p.get('signal'), 9)
            line, sig, _ = macd(closes, f_, s_, g_)
            v['votes']['MACD'] = [(1 if line[i] > sig[i] else -1)
                                  if (line[i] is not None and sig[i] is not None) else 0
                                  for i in range(n)]
        if ind.get('BB', {}).get('enabled'):
            p = ind['BB'].get('params', {})
            p_, sd_ = _pi(p.get('period'), 20), _pf(p.get('std'), 2.0)
            mid, up, lo = bollinger(closes, p_, sd_)
            col = []
            for i in range(n):
                if lo[i] is None:
                    col.append(0)
                elif closes[i] < lo[i]:
                    col.append(1)
                elif closes[i] > up[i]:
                    col.append(-1)
                else:
                    col.append(0)
            v['votes']['BB'] = col
        v['atr'] = atr(highs, lows, closes,
                       _pi(ind.get('ATR', {}).get('params', {}).get('period'), 14))
        out = v
    _VCACHE[key] = out
    return out


def last_closed(v, res_min, epoch):
    best = -1
    for i, ts in enumerate(v['t']):
        if ts + res_min * 60 <= epoch:
            best = i
    return best


def main():
    sheet_id = load_env().get('SHEET_ID')
    if not sheet_id:
        sys.exit('SHEET_ID یافت نشد')
    gc = gspread.service_account(filename='service_account.json')
    sh = gc.open_by_key(sheet_id)
    st = Settings.from_sheet(sh.worksheet('تنظیمات'))
    tfs = st.active_timeframes or []
    if not tfs:
        sys.exit('هیچ تایم‌فریمی فعال نیست')
    ind = st.indicators
    voters = [k for k in ('SMA', 'EMA', 'RSI', 'MACD', 'BB')
              if ind.get(k, {}).get('enabled')]

    print('=== لایه ۱: پیکربندی فعال ===')
    print('رأی‌دهنده‌ها:', '، '.join(voters) or 'هیچ', '| ATR: زیرساخت (بدون رأی)')
    print('تایم‌فریم‌ها:', '، '.join(l for l, _ in tfs), f'| آستانه: {st.threshold_pct:.0f}٪')

    sig_counts = {'خرید': 0, 'فروش': 0, 'خنثی': 0}
    mentions = {k: 0 for k in voters}
    for r in sh.worksheet('استراتژی').get_all_values():
        if len(r) > 11 and str(r[4]).strip() in sig_counts:
            sig_counts[str(r[4]).strip()] += 1
            note = str(r[11])
            for k in voters:
                if (k == 'BB' and 'باند' in note) or (k != 'BB' and k in note):
                    mentions[k] += 1
    print('=== لایه ۲: رأی لحظه‌ای (snapshot استراتژی) ===')
    print(f"ردیف‌ها: خرید {sig_counts['خرید']} | فروش {sig_counts['فروش']} | خنثی {sig_counts['خنثی']}")
    print('ذکر در noteها:', '، '.join(f'{k}={mentions[k]}' for k in voters))

    buys = []
    for r in sh.worksheet('سفارشات').get_all_values()[3:]:
        if len(r) < 12 or str(r[2]).strip() != 'خرید':
            continue
        if str(r[11]).strip() not in EXECUTED:
            continue
        e = _epoch(r[0])
        if e is None:
            continue
        buys.append({'epoch': e, 't': str(r[0]).strip(),
                     'sym': str(r[1]).strip().upper(), 'signal': _f(r[5]),
                     'reason': str(r[4]),
                     'fill': _fill_epoch(r[12]) if len(r) > 12 else None})
    buys.sort(key=lambda b: b['epoch'])

    positions, skipped, frag = {}, 0, 0
    for r in sh.worksheet('اتمام معاملات').get_all_values()[1:]:
        if len(r) < 8:
            continue
        sym = str(r[1]).strip().upper()
        xt = _epoch(r[0])
        pnl = _f(r[6])
        if not (sym and xt is not None):
            continue
        if len(r) > 10 and str(r[10]).strip() == 'شبیه‌سازی':
            continue
        cand = None
        for b in buys:
            if b['sym'] == sym and b['epoch'] <= xt:
                cand = b
        if cand is None:
            skipped += 1
            continue
        frag += 1
        pos = positions.setdefault(id(cand), {'sym': sym, 'place': cand['epoch'],
                                              't': cand['t'], 'signal': cand['signal'],
                                              'reason': cand['reason'], 'fill': cand['fill'],
                                              'pnl': 0.0, 'n': 0})
        pos['pnl'] += pnl or 0.0
        pos['n'] += 1

    pos_list = sorted(positions.values(), key=lambda p: p['place'])
    n_pos = len(pos_list)
    wins = [p for p in pos_list if p['pnl'] > 0]
    print('=== لایه ۳: پوزیشن‌ها ===')
    print(f'پوزیشن: {n_pos} (از {frag} رویداد خروج؛ بدون تطبیق: {skipped}) | '
          f'WR کل: {100.0 * len(wins) / n_pos if n_pos else 0:.1f}٪ | '
          f'P&L کل: {sum(p["pnl"] for p in pos_list):+.2f}')

    evals, tf_cov = [], {l: 0 for l, _ in tfs}
    tf_div, atr_pct = {l: [] for l, _ in tfs}, {}
    print('  [دریافت کندل‌ها…]')
    for pos in pos_list:
        for label, res in tfs:
            res_min = se.RES_MINUTES[res]
            v = votes_for(pos['sym'], res, ind)
            if v is None:
                continue
            i = last_closed(v, res_min, pos['place'])
            if i < 0:
                continue
            tf_cov[label] += 1
            if pos['signal']:
                tf_div[label].append(abs(v['close'][i] - pos['signal']) / pos['signal'] * 100.0)
            evals.append({'pos': pos, 'tf': label,
                          'votes': {k: col[i] for k, col in v['votes'].items()}})
            if res == '60' and v['atr'][i] and v['close'][i]:
                atr_pct[id(pos)] = v['atr'][i] / v['close'][i] * 100.0
    print('پوشش per TF:', ' | '.join(f'{l}: {tf_cov[l]}/{n_pos}' for l, _ in tfs))
    print('میانهٔ واگرایی کندلِ تصمیم از قیمت سیگنال:',
          ' | '.join(f"{l}: {(sorted(tf_div[l])[len(tf_div[l]) // 2] if tf_div[l] else 0):.2f}٪"
                     for l, _ in tfs))

    print('=== لایه ۴-الف: per اندیکاتور (ارزیابی = پوزیشن×TF؛ همبسته) ===')
    for k in voters:
        parts = []
        for lbl, val in (('خرید', 1), ('فروش', -1)):
            sub = [e for e in evals if e['votes'].get(k) == val]
            if sub:
                w = sum(1 for e in sub if e['pos']['pnl'] > 0)
                parts.append(f'{lbl}: n={len(sub)} WR={100.0 * w / len(sub):.0f}٪ '
                             f'میانگین={sum(e["pos"]["pnl"] for e in sub) / len(sub):+.3f}')
            else:
                parts.append(f'{lbl}: n=0')
        print(f'  {k:5}| ' + ' | '.join(parts))
    edges = []
    for k in voters:
        b = [e for e in evals if e['votes'].get(k) == 1]
        s = [e for e in evals if e['votes'].get(k) == -1]
        if b and s:
            wrb = 100.0 * sum(1 for e in b if e['pos']['pnl'] > 0) / len(b)
            wrs = 100.0 * sum(1 for e in s if e['pos']['pnl'] > 0) / len(s)
            edges.append(f'{k}: {wrb - wrs:+.1f}pp')
    print('  edge (WR رأی‌خرید − WR رأی‌فروش):', '، '.join(edges) or '—')

    print('=== لایه ۴-ب: per اندیکاتور × تایم‌فریم (WR خرید/WR فروش (nخرید/nفروش)) ===')
    for k in voters:
        cells = []
        for label, _ in tfs:
            b = [e for e in evals if e['tf'] == label and e['votes'].get(k) == 1]
            s = [e for e in evals if e['tf'] == label and e['votes'].get(k) == -1]
            wb = (100.0 * sum(1 for e in b if e['pos']['pnl'] > 0) / len(b)) if b else None
            ws = (100.0 * sum(1 for e in s if e['pos']['pnl'] > 0) / len(s)) if s else None
            if wb is None and ws is None:
                cells.append('—')
            else:
                cells.append(f'{(wb or 0):.0f}/{(ws or 0):.0f} ({len(b)}/{len(s)})')
        print(f'  {k:5}| ' + ' | '.join(cells))

    print('=== لایه ۴-ج: اکثریت TF در reason (متغیر تصمیم واقعی) ===')
    maj = {}
    for p in pos_list:
        m = re.search(r'رأی خرید (\d+)/(\d+)', p['reason'])
        if m:
            maj.setdefault(f'{m.group(1)}/{m.group(2)}', []).append(p)
    for key in sorted(maj, key=lambda x: int(x.split('/')[0])):
        sub = maj[key]
        w = sum(1 for p in sub if p['pnl'] > 0)
        print(f'  {key}: n={len(sub)} | WR={100.0 * w / len(sub):.0f}٪ | '
              f'P&L کل={sum(p["pnl"] for p in sub):+.2f}')

    print('=== زمینه: ATR(1h)٪ در لحظهٔ تصمیم ===')
    w_a = sorted(a for p in wins if id(p) in atr_pct for a in [atr_pct[id(p)]])
    l_a = sorted(a for p in pos_list if p['pnl'] <= 0 and id(p) in atr_pct
                 for a in [atr_pct[id(p)]])
    if w_a and l_a:
        print(f'  میانهٔ برنده‌ها: {w_a[len(w_a) // 2]:.2f}٪ | '
              f'میانهٔ بازنده‌ها: {l_a[len(l_a) // 2]:.2f}٪')

    print('=== جزئیات (۲۰ پوزیشن آخر) ===')
    for p in pos_list[-20:]:
        m = re.search(r'رأی خرید (\d+)/(\d+)', p['reason'])
        maj_s = f'{m.group(1)}/{m.group(2)}' if m else '—'
        print(f"  {p['sym']:6} | {p['t']} | اکثریت={maj_s:5} | frag={p['n']} | P&L={p['pnl']:+.2f}")

    print('=== تحفظ‌ها (بند ۸) ===')
    print('۱) ارزیابی‌ها همبسته‌اند (تا ۴ ارزیابی per پوزیشن) — n مؤثر کمتر از شمار ارزیابی‌هاست.')
    print('۲) رأی بازمحاسبه‌شده روی آخرین کندلِ بستهٔ قبل از تصمیم است؛ ربات زنده روی کندل در حال')
    print('   شکل‌گیری رأی می‌دهد — واگرایی بالا گزارش شد (برای 4h/1D بزرگ‌تر است).')
    print('۳) سیگنال‌های بازمحاسبه‌شده با آستانهٔ «فعلی» سنجیده می‌شوند (آستانهٔ تاریخی تغییر کرده).')
    print('۴) عمق کندل 15m محدود (~۵ روز) — پوزیشن‌های قدیمی‌تر از پوشش 15m خارج‌اند.')
    print('۵) انکر زمانی = زمان ثبت سفارش (لحظهٔ تصمیم)؛ fill پولبکی تا ۶۰ دقیقه بعدتر رخ می‌دهد.')
    print('۶) P&L از «اتمام معاملات» (N7، شامل کارمزد)؛ فرگمنت‌ها به پوزیشن dedup شدند.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
