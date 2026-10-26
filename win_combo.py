# -*- coding: utf-8 -*-
"""win_combo.py — موتور «ترکیب برنده»: SL%/TP%/ضریب تریلینگ بهینهٔ per-symbol
از تب «تحلیل معاملات». قواعد ازپیش‌ثبت‌شدهٔ r23:
  واجد شرایط: n>=6 و برد>=2 و باخت>=2 (خروج >= 1405/07/28؛ سربه‌سر فقط n)
  TP%   = clamp(0.8*medWin, [1.5, 8])
  SL%   = clamp(سهم خارَچ تریل>=0.5 ? 1.25*medATR : max(1.15*medLoss, 1.25*medATR), [1.0, min(band,5)])
  ضریب تریل = clamp(0.6*medWin/medATR%, [0.3, 1.5])
  شرامپ به مرجع جهانی: w = n/(n+8)
همهٔ خطاها fail-open: خروجی خالی = هندسهٔ جهانی ربات (رفتار فعلی)."""
import time
import statistics

TAB = 'ترکیب برنده'
ANALYSIS_TAB = 'تحلیل معاملات'
CUTOFF = '1405/07/28'      # قبل از این = دوران تست — محاسبه نمی‌آید
CACHE_TTL = 300.0
FA = str.maketrans('۰۱۲۳۴۵۶۷۸۹٫', '0123456789.')
HEADER = ['نماد', 'SL%', 'TP%', 'ضریب تریلینگ', 'n', 'برد', 'باخت', 'WR%',
          'medWin%', 'medLoss%', 'medATR%', 'سهم خارَچ تریل', 'مدت برد(ساعت)',
          'مدت باخت(ساعت)', 'علت غالب باخت', 'علت غالب برد', 'یادداشت', 'قفل']

_CACHE = {'t': 0.0, 'params': {}, 'ok': False}


def fnum(x):
    try:
        return float(str(x).replace(',', '').translate(FA))
    except (TypeError, ValueError):
        return None


def _now():
    try:
        import jdatetime
        return jdatetime.datetime.now().strftime('%Y/%m/%d %H:%M')
    except Exception:
        return time.strftime('%Y/%m/%d %H:%M', time.gmtime())


def _enabled(st):
    try:
        return bool(getattr(st, 'win_combo_enabled', True))
    except Exception:
        return True


def _refs(st):
    return {'slm': float(getattr(st, 'sl_atr_mult', 1.5) or 1.5),
            'tpm': float(getattr(st, 'tp_atr_mult', 3.0) or 3.0),
            'tm': float(getattr(st, 'trail_atr_mult', 0.5) or 0.0),
            'band': float(getattr(st, 'max_sl_band_pct', 8.0) or 8.0)}


def _compute_stats(rows):
    """آمار per-symbol از تب تحلیل (هدر = سطری که ستون ۲ = «نماد»)."""
    hdr_i = None
    for i, r in enumerate(rows):
        if r and len(r) > 1 and str(r[1]).strip() == 'نماد':
            hdr_i = i
            break
    if hdr_i is None:
        return {}
    out = {}
    for r in rows[hdr_i + 1:]:
        if not r or len(r) < 6:
            continue
        t = str(r[0]).strip()
        if t < CUTOFF:            # دوران تست — مسموم
            continue
        sym = str(r[1]).strip().upper()
        if not sym:
            continue
        pct, res = fnum(r[5]), str(r[2]).strip()
        a = out.setdefault(sym, {'n': 0, 'win_p': [], 'loss_p': [], 'atr_p': [],
                                 'scratch': 0, 'dur_w': [], 'dur_l': [],
                                 'cause_w': [], 'cause_l': []})
        a['n'] += 1
        dur = fnum(r[6]) if len(r) > 6 else None
        cause = str(r[20]).strip() if len(r) > 20 else ''
        if res == 'سربه‌سر':
            pass                  # خنثی — فقط n
        elif (pct is not None and pct > 0) or (pct is None and res == 'برد'):
            a['win_p'].append(pct if pct is not None else 0.0)
            if dur is not None:
                a['dur_w'].append(dur)
            if cause:
                a['cause_w'].append(cause)
        elif (pct is not None and pct < 0) or (pct is None and res == 'باخت'):
            a['loss_p'].append(abs(pct) if pct is not None else 0.0)
            if dur is not None:
                a['dur_l'].append(dur)
            if cause:
                a['cause_l'].append(cause)
            if len(r) > 18 and str(r[18]).strip() == 'بله':
                a['scratch'] += 1
        ent = fnum(r[7]) if len(r) > 7 else None
        atr = fnum(r[13]) if len(r) > 13 else None
        if ent and atr and ent > 0 and atr > 0:
            a['atr_p'].append(atr / ent * 100.0)
    for a in out.values():
        a['eligible'] = (a['n'] >= 6 and len(a['win_p']) >= 2 and len(a['loss_p']) >= 2)
    return out


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _top(lst):
    return max(set(lst), key=lst.count) if lst else '—'


def _derive(sym, a, refs):
    """فرمول ازپیش‌ثبت‌شدهٔ r23 — خروجی = یک ردیف کامل تب + پارامترهای مصرفی."""
    if not (a['win_p'] and a['loss_p'] and a['atr_p']):
        return None
    med_w = statistics.median(a['win_p'])
    med_l = statistics.median(a['loss_p'])
    med_a = statistics.median(a['atr_p'])
    if not (med_a > 0):
        return None
    scratch_share = a['scratch'] / max(1, len(a['loss_p']))
    n = a['n']
    w = n / (n + 8.0)                      # شرامپ: n=6→0.43 | n=20→0.71
    tp_raw = _clamp(0.8 * med_w, 1.5, 8.0)
    sl_base = (1.25 * med_a if scratch_share >= 0.5
               else max(1.15 * med_l, 1.25 * med_a))
    sl_raw = _clamp(sl_base, 1.0, min(refs['band'], 5.0))
    tm_raw = _clamp(0.6 * med_w / med_a, 0.3, 1.5)
    sl_pct = _clamp(w * sl_raw + (1 - w) * refs['slm'] * med_a, 1.0, min(refs['band'], 5.0))
    tp_pct = _clamp(w * tp_raw + (1 - w) * refs['tpm'] * med_a, 1.5, 8.0)
    trail = _clamp(w * tm_raw + (1 - w) * refs['tm'], 0.0, 3.0)
    notes = []
    if tp_raw <= 1.5 + 1e-9:
        notes.append('TP به کف رسید (برد معمول کوچک)')
    if tp_pct <= 1.2 * sl_pct:
        notes.append('RR<1.2 — هندسهٔ داده‌محور؛ کیفیت ورود این نماد را بسنجید')
    return {'sl_pct': round(sl_pct, 2), 'tp_pct': round(tp_pct, 2),
            'trail_mult': round(trail, 2), 'n': n,
            'w': len(a['win_p']), 'l': len(a['loss_p']),
            'wr': round(100.0 * len(a['win_p']) / n, 1),
            'med_w': round(med_w, 2), 'med_l': round(med_l, 2), 'med_a': round(med_a, 2),
            'scratch': round(scratch_share, 2),
            'dur_w': round(statistics.median(a['dur_w']), 1) if a['dur_w'] else '—',
            'dur_l': round(statistics.median(a['dur_l']), 1) if a['dur_l'] else '—',
            'cause_l': _top(a['cause_l']), 'cause_w': _top(a['cause_w']),
            'note': '؛ '.join(notes)}


def _recompute(spr, st):
    """بازخوانی تحلیل → بازنویسی تب «ترکیب برنده» → دیکشنری پارامترها."""
    refs = _refs(st)
    ws_an = spr.worksheet(ANALYSIS_TAB)
    stats = _compute_stats(ws_an.get_values(value_render_option='UNFORMATTED_VALUE'))
    try:
        ws_wc = spr.worksheet(TAB)
    except Exception:
        ws_wc = spr.add_worksheet(TAB, rows=300, cols=20)
    prev = ws_wc.get_values(value_render_option='UNFORMATTED_VALUE')
    locked = {}
    for r in prev[3:]:
        if (r and str(r[0]).strip() and len(r) > 17
                and str(r[17]).strip() == 'بله'):
            locked[str(r[0]).strip().upper()] = list(r[:18])
    grid, params = [], {}
    for sym, a in sorted(stats.items(), key=lambda kv: (-kv[1]['n'], kv[0])):
        if not a['eligible']:
            continue
        if sym in locked:                      # قفل دستی اپراتور — مقدار شما حاکم است
            row = locked[sym]
            slp, tpp, tm = fnum(row[1]), fnum(row[2]), fnum(row[3])
            if slp and tpp and tm:
                params[sym] = {'sl_pct': slp, 'tp_pct': tpp, 'trail_mult': tm}
                grid.append(row + [''] * (18 - len(row)))
                continue
        d = _derive(sym, a, refs)
        if not d:
            continue
        params[sym] = {'sl_pct': d['sl_pct'], 'tp_pct': d['tp_pct'],
                       'trail_mult': d['trail_mult']}
        grid.append([sym, d['sl_pct'], d['tp_pct'], d['trail_mult'], d['n'], d['w'],
                     d['l'], d['wr'], d['med_w'], d['med_l'], d['med_a'], d['scratch'],
                     d['dur_w'], d['dur_l'], d['cause_l'], d['cause_w'], d['note'], 'خیر'])
    prev_len = max(0, len(prev) - 3)
    n_write = min(250, max(len(grid), prev_len))
    grid = grid + [[''] * 18] * (n_write - len(grid))
    ws_wc.update(values=[['🏆 ترکیب برنده — هندسهٔ بهینهٔ per-symbol (از تحلیل معاملات)',
                          'به‌روزرسانی:', _now()]], range_name='A1:C1')
    ws_wc.update(values=[HEADER], range_name='A3:R3')
    if n_write:
        ws_wc.update(values=grid, range_name='A4:R%d' % (3 + n_write))
    return params


def get_params(ws_t, st=None, ttl=CACHE_TTL):
    """پارامترهای per-symbol برای هوک‌های trader — کش TTL، fail-open به {}."""
    if st is not None and not _enabled(st):
        return {}
    now = time.time()
    if _CACHE.get('ok') and (now - _CACHE['t']) < ttl:
        return _CACHE['params']
    try:
        params = _recompute(ws_t.spreadsheet, st)
        _CACHE['ok'] = True
    except Exception:
        params = _CACHE['params'] or {}
    _CACHE['t'] = now
    _CACHE['params'] = params
    return params


def refresh_after_close(ws_t, st=None):
    """هوک _record_analysis: بازمحاسبهٔ فوری پس از هر خروج تازه."""
    try:
        params = _recompute(ws_t.spreadsheet, st)
        _CACHE.update({'t': time.time(), 'params': params, 'ok': True})
        return params
    except Exception:
        return None
