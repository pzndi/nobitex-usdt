#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""apply_win_combo.py v3 — G-wincombo: تب «ترکیب برنده» (هندسهٔ per-symbol داینامیک)

v2 (r25): رفع باگ دادهٔ تست HIGHN (n=4→6)؛ فیلانکور با regex تورفتگی‌آگنوستیک
(دو کپی با تورفتگی متفاوت)؛ گارد بافر SL/RR در هوک buy_one؛ تست‌های مستقل از
ترتیب؛ چک سورس-محور پس از دیپلوی + import واقعی trader با rollback خودکار.
بدون --deploy: فقط win_combo.py + تست‌ها + پیش‌نمایش (trader.py دست‌نخورده).
"""
import os, sys, re, py_compile, shutil, subprocess

os.chdir(os.path.expanduser('~/nobitex-usdt'))
DEPLOY = '--deploy' in sys.argv

WIN_COMBO_SRC = '''# -*- coding: utf-8 -*-
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
'''

# ---------------- انکرهای trader.py (هر سه یکتا — r23 تأیید شد) ----------------
OLD1 = "    row = a['best'][1]\n    tf, sl, tp = row[1], row[9], row[10]\n"
NEW1 = OLD1 + """    # G-wincombo: هندسهٔ per-symbol از تب «ترکیب برنده» — نماد حاضر → override
    # گارد: بافر SL نسبت به fill تخمینی + حداقل RR؛ رد → هندسهٔ ردیف حفظ می‌شود.
    # row[9]/row[10] هم به‌روز می‌شوند تا G-volsize/برچسب باند سازگار بمانند.
    try:
        import win_combo
        _wcp = win_combo.get_params(ws_t, st)
        if sym in _wcp:
            _pull_e = _eff_pullback_pct(row, st) / 100.0
            _buf_e = getattr(st, 'slbuf_min_pct', 0.5) / 100.0
            _slp_e = _wcp[sym]['sl_pct'] / 100.0
            _tpp_e = _wcp[sym]['tp_pct'] / 100.0
            if _slp_e >= _pull_e + _buf_e and _tpp_e >= 1.2 * _slp_e:
                sl = fmt_price(price * (1 - _slp_e))
                tp = fmt_price(price * (1 + _tpp_e))
                row[9], row[10] = sl, tp
                log.info('G-wincombo %s: SL%%=%.2f TP%%=%.2f از تب ترکیب برنده', sym,
                         _wcp[sym]['sl_pct'], _wcp[sym]['tp_pct'])
            else:
                log.info('G-wincombo %s: override رد شد (بافر SL یا RR) — هندسهٔ ردیف', sym)
    except Exception:
        pass
"""

OLD2 = "            if _atr:\n                new_sl = price - st.trail_atr_mult * _atr\n"
NEW2 = """            if _atr:
                # G-wincombo: ضریب تریلینگ per-symbol (نمادِ فاقد تب → ضریب جهانی)
                _tm_eff = st.trail_atr_mult
                try:
                    import win_combo
                    _wct = win_combo.get_params(ws_t, st)
                    _wcv = (_wct.get(sym) or {}).get('trail_mult')
                    if _wcv:
                        _tm_eff = _wcv
                except Exception:
                    pass
                new_sl = price - _tm_eff * _atr
"""

OLD3 = "        log.info('تحلیل معامله %s ثبت شد: %s', sym, analysis)\n"
NEW3 = OLD3 + """        # G-wincombo: بازمحاسبهٔ تب «ترکیب برنده» پس از هر خروج تازه
        try:
            import win_combo
            win_combo.refresh_after_close(ws_t, st)
        except Exception:
            pass
"""

TRADER_PATCHES = [(OLD1, NEW1, 1, 'buy_one'), (OLD2, NEW2, 1, 'apply_trailing'),
                  (OLD3, NEW3, 1, '_record_analysis')]

# ---------------- فیلانکور: regex تورفتگی‌آگنوستیک (دو کپی، تورفتگی متفاوت) ----------------
FA_SL_RE = re.compile(r'^(?P<ind>[ ]+)_sl_new = _fill_px - _slm \* _atr[ \t]*$', re.M)
FA_TP_RE = re.compile(r'^(?P<ind>[ ]+)_tp_new = _fill_px \+ _tpm \* _atr[ \t]*$', re.M)


def patch_fillanchor(tsrc):
    """G-wincombo-fa: حفظ فاصلهٔ مطلق SL/TP نسبت به سیگنال پس از fill —
    درصدهای per-symbol زنده می‌مانند؛ برای ردیف‌های هندسهٔ جهانی نتیجه یکسان.
    دو رخداد با تورفتگی متفاوت → regex؛ بافتار هر رخداد راستی‌آزمایی می‌شود."""
    sl_ms = list(FA_SL_RE.finditer(tsrc))
    tp_ms = list(FA_TP_RE.finditer(tsrc))
    print('fillanchor: رخداد SL=%d | TP=%d (انتظار 2 و 2)' % (len(sl_ms), len(tp_ms)))
    if len(sl_ms) != 2 or len(tp_ms) != 2:
        print('⛔ تعداد رخدادهای fillanchor مطابق انتظار نیست — سورس تغییر کرده')
        for m in sl_ms + tp_ms:
            print('--- رخداد @%d ---' % m.start())
            print(tsrc[max(0, m.start() - 400):m.end() + 150])
        return None
    for m in sl_ms + tp_ms:
        ctx = tsrc[max(0, m.start() - 1200):m.start()]
        for var in ('_fill_px', '_p_sig', '_sl_old', '_tp_old'):
            if var not in ctx:
                print('⛔ متغیر %s در بافتار رخداد fillanchor نیست — سورس متفاوت' % var)
                return None
    out = FA_SL_RE.sub(r'\g<ind>_sl_new = _fill_px - (_p_sig - _sl_old)', tsrc)
    out = FA_TP_RE.sub(r'\g<ind>_tp_new = _fill_px + (_tp_old - _p_sig)', out)
    return out

# ---------------- انکرهای settings.py ----------------
OLD5 = "'MIN_TFS_SELL', 'LEG1_MARKET'}"
NEW5 = "'MIN_TFS_SELL', 'LEG1_MARKET', 'WIN_COMBO_ENABLED'}"
OLD6 = "'MIN_TFS': '3', 'MIN_TFS_SELL': '3'}"
NEW6 = "'MIN_TFS': '3', 'MIN_TFS_SELL': '3', 'WIN_COMBO_ENABLED': 'بله'}"
OLD7 = """    @property
    def leg1_market(self):
        \"\"\"G-mhalf: پایهٔ اول Scale به‌صورت مارکت (بله/خیر) — پایهٔ دوم limit نیم‌درصد پایین‌تر\"\"\"
        return truthy(self.trading.get('LEG1_MARKET', 'خیر'))
"""
NEW7 = OLD7 + """
    @property
    def win_combo_enabled(self):
        \"\"\"G-wincombo: هندسهٔ per-symbol از تب «ترکیب برنده» (بله/خیر)\"\"\"
        return truthy(self.trading.get('WIN_COMBO_ENABLED', 'بله'))
"""
SETTINGS_PATCHES = [(OLD5, NEW5, 1, 'TRADING_KEYS'), (OLD6, NEW6, 1, 'DEFAULT_TRADING'),
                    (OLD7, NEW7, 1, 'property')]


def write_win_combo():
    if os.path.exists('win_combo.py'):
        shutil.copy2('win_combo.py', 'win_combo.py.bak')
        print('= بکاپ: win_combo.py.bak')
    with open('win_combo.py', 'w', encoding='utf-8') as f:
        f.write(WIN_COMBO_SRC)
    py_compile.compile('win_combo.py', doraise=True)
    print('✓ win_combo.py نوشته و کامپایل شد (تا پچ trader بی‌اثر است)')


def run_tests():
    print('---------- تست‌ها (fake — بدون شبکه) ----------')
    import win_combo

    HDR_AN = ['زمان خروج', 'نماد', 'نتیجه', 'نوع خروج', 'P&L USDT', 'P&L %', 'مدت (ساعت)',
              'قیمت ورود', 'قیمت خروج', 'SL تنظیم‌شده', 'TP تنظیم‌شده', 'فاصله SL%',
              'فاصله TP%', 'ATR', 'نوسان 4h%', 'تعداد Scale 1/2', 'تعداد Scale 2/2',
              'Scale-in', 'Trailing فعال', 'Partial فعال', 'علت تحلیل', 'درس‌آموخته']

    def an(t, sym, res, pct, dur, trail, cause):
        return [t, sym, res, 'حد ضرر (SL)' if res == 'باخت' else 'حد سود (TP)',
                0.02, pct, dur, 100, 99, 98.8, 101.6, 1.2, 1.6, 1.0, 2.0, 0, 0,
                'خیر', trail, 'خیر', cause, 'درس']

    rows = [['📊', '', ''], [], HDR_AN]
    rows.append(an('1405/08/01 10:00', 'MEW', 'برد', 1.0, 1.0, 'خیر', 'هدف محقق شد'))
    rows.append(an('1405/08/01 11:00', 'MEW', 'برد', 3.0, 2.0, 'خیر', 'هدف محقق شد'))
    for i, (pct, dur, tr) in enumerate([(2.0, 0.5, 'بله'), (2.0, 0.5, 'بله'),
                                        (1.0, 1.5, 'بله'), (1.0, 2.5, 'خیر')]):
        rows.append(an('1405/08/01 12:0%d' % i, 'MEW', 'باخت', -pct, dur, tr, 'SL اجرا شد'))
    rows.append(an('1405/08/02 11:00', 'HIGHN', 'برد', 1.0, 1.0, 'خیر', 'هدف محقق شد'))
    rows.append(an('1405/08/02 11:30', 'HIGHN', 'برد', 3.0, 2.0, 'خیر', 'هدف محقق شد'))
    for i, (pct, dur) in enumerate([(2.0, 0.5), (2.0, 0.5), (1.0, 1.5), (1.0, 2.5)]):
        rows.append(an('1405/08/02 12:0%d' % i, 'HIGHN', 'باخت', -pct, dur, 'خیر', 'SL اجرا شد'))
    rows.append(an('1405/08/01 13:00', 'LOWN', 'برد', 1.0, 1.0, 'خیر', 'x'))      # n=1
    rows.append(an('1405/07/20 09:00', 'OLD', 'باخت', -2.0, 1.0, 'خیر', 'دوران تست'))

    # --- تست ۱: آمار و واجد شرایطی ---
    st = win_combo._compute_stats(rows)
    assert st['MEW']['eligible'] and st['MEW']['n'] == 6
    assert st['HIGHN']['eligible'] and st['HIGHN']['n'] == 6
    assert not st['LOWN']['eligible'] and 'OLD' not in st
    print('✓ تست ۱: آمار/واجد شرایطی (MEW و HIGHN هر دو n=6 ✓، LOWN n=1 رد ✓، دوران تست مستثنا ✓)')

    # --- تست ۲: فرمول (دست‌حسابی‌شده) ---
    refs = {'slm': 1.5, 'tpm': 3.0, 'tm': 0.5, 'band': 8.0}
    d = win_combo._derive('MEW', st['MEW'], refs)
    # medWin=2.0 medLoss=1.5 medATR=1.0 خارَچ=0.75≥0.5 w=6/14 → SL=1.39 TP=2.40 trail=0.80
    assert abs(d['sl_pct'] - 1.39) < 0.011, d
    assert abs(d['tp_pct'] - 2.40) < 0.011, d
    assert abs(d['trail_mult'] - 0.80) < 0.011, d
    assert d['wr'] == 33.3 and d['scratch'] == 0.75
    d2 = win_combo._derive('HIGHN', st['HIGHN'], refs)
    # خارَچ=0 → SL=max(1.15×1.5, 1.25)=1.725 → شرامپ → 1.60
    assert abs(d2['sl_pct'] - 1.60) < 0.011, d2
    print('✓ تست ۲: فرمول — MEW (SL=1.39 TP=2.40 ضریب=0.80) | HIGHN (SL=1.60، شاخهٔ بدون خارَچ)')

    # --- تست ۳: جریان کامل get_params + نوشتن تب ---
    class FakeAn:
        def __init__(self, rows): self._r = rows
        def get_values(self, value_render_option=None): return [list(x) for x in self._r]
    class FakeCombo:
        def __init__(self, rows=None): self._r = rows or []; self.calls = []
        def get_values(self, value_render_option=None): return [list(x) for x in self._r]
        def update(self, values=None, range_name=None):
            self.calls.append(range_name)
            if range_name and range_name.startswith('A4'):
                self._r = self._r[:3] + [list(v) for v in values]
    class FakeSS:
        def __init__(self, an, combo=None): self._an, self._combo = an, combo
        def worksheet(self, title):
            if title == 'تحلیل معاملات': return self._an
            if title == 'ترکیب برنده':
                if self._combo is None: raise Exception('no tab')
                return self._combo
            raise Exception('no ' + title)
        def add_worksheet(self, title, rows=0, cols=0):
            self._combo = FakeCombo([['x'], [], []]); return self._combo
    class FakeWS_T:
        def __init__(self, ss): self.spreadsheet = ss
    class FakeST:
        win_combo_enabled = True; sl_atr_mult = 1.5; tp_atr_mult = 3.0
        trail_atr_mult = 0.5; max_sl_band_pct = 8.0

    win_combo._CACHE.update({'t': 0, 'params': {}, 'ok': False})
    combo = FakeCombo([['t'], [], []])
    p = win_combo.get_params(FakeWS_T(FakeSS(FakeAn(rows), combo)), FakeST(), ttl=0)
    assert 'MEW' in p and p['MEW']['sl_pct'] == 1.39
    assert any(c.startswith('A4') for c in combo.calls) and 'A3:R3' in combo.calls
    _d = {str(r[0]): r for r in combo._r[3:5] if str(r[0]).strip()}
    assert 'MEW' in _d and 'HIGHN' in _d
    assert _d['MEW'][1] == 1.39 and _d['MEW'][3] == 0.8 and _d['MEW'][17] == 'خیر'
    print('✓ تست ۳: get_params + بازنویسی تب (هدر/گرید، مستقل از ترتیب)')

    # --- تست ۴: قفل دستی اپراتور ---
    win_combo._CACHE.update({'t': 0, 'params': {}, 'ok': False})
    _lk = ['MEW', 2, 3, 0.7] + [''] * 13 + ['بله']     # ۱۸ ستون — قفل در ستون R
    combo2 = FakeCombo([['t'], [], [], _lk])
    p2 = win_combo.get_params(FakeWS_T(FakeSS(FakeAn(rows), combo2)), FakeST(), ttl=0)
    assert p2['MEW'] == {'sl_pct': 2.0, 'tp_pct': 3.0, 'trail_mult': 0.7}, p2
    _d2 = {str(r[0]): r for r in combo2._r[3:5] if str(r[0]).strip()}
    assert _d2['MEW'][1] == 2 and _d2['MEW'][17] == 'بله'
    print('✓ تست ۴: قفل «بله» → مقدار دستی اپراتور حاکم و پارامتر همان است')

    # --- تست ۵: کلید قطع‌کننده ---
    class FakeSTOff(FakeST):
        win_combo_enabled = False
    win_combo._CACHE.update({'t': 0, 'params': {}, 'ok': False})
    assert win_combo.get_params(FakeWS_T(FakeSS(FakeAn(rows), combo)), FakeSTOff(), ttl=0) == {}
    print('✓ تست ۵: WIN_COMBO_ENABLED=خیر → خروجی خالی (رفتار فعلی)')

    # --- تست ۶: ریاضی هوک‌ها ---
    price, sl_pct, tp_pct = 100.0, 1.39, 2.4
    assert abs(price * (1 - sl_pct / 100) - 98.61) < 1e-9
    assert abs(price * (1 + tp_pct / 100) - 102.4) < 1e-9
    sig, sl_old, tp_old, fill = 100.0, 98.8, 102.5, 99.0
    assert abs((fill - (sig - sl_old)) - 97.8) < 1e-9      # فاصلهٔ ۱.۲ حفظ شد
    assert abs((fill + (tp_old - sig)) - 101.5) < 1e-9     # فاصلهٔ ۲.۵ حفظ شد
    print('✓ تست ۶: ریاضی هوک buy_one (درصد→قیمت) + fillanchor (حفظ فاصلهٔ مطلق)')

    # --- تست ۶-ب: regex فیلانکور (تورفتگی‌آگنوستیک) ---
    _fa_src = ('x\n' + ' ' * 20 + '_sl_new = _fill_px - _slm * _atr\n'
               + ' ' * 24 + '_sl_new = _fill_px - _slm * _atr\n')
    assert len(FA_SL_RE.findall(_fa_src)) == 2
    _out = FA_SL_RE.sub(r'\g<ind>_sl_new = _fill_px - (_p_sig - _sl_old)', _fa_src)
    assert _out.count('_fill_px - (_p_sig - _sl_old)') == 2
    assert ' ' * 24 + '_sl_new = _fill_px - (_p_sig - _sl_old)' in _out
    print('✓ تست ۶-ب: regex فیلانکور — دو تورفتگی متفاوت، جایگزینی با حفظ تورفتگی')

    # --- تست ۷: settings — truthy (چک کلید پس از دیپلوی در main) ---
    import settings
    assert settings.truthy('بله') and not settings.truthy('خیر')
    print('✓ تست ۷: settings.truthy')
    print('---------- همهٔ تست‌ها سبز ----------')


def post_deploy_sheet_setup():
    """درج کلید در تب تنظیمات + ساخت اولیهٔ تب «ترکیب برنده» (نمایش فوری)."""
    try:
        import gspread
        from settings import load_env
        import win_combo
        from types import SimpleNamespace
        sh = gspread.service_account(filename='service_account.json').open_by_key(
            load_env().get('SHEET_ID'))
        ws = sh.worksheet('تنظیمات')
        col = [str(x).strip() for x in ws.col_values(1)]
        if 'WIN_COMBO_ENABLED' in col:
            print('= WIN_COMBO_ENABLED از قبل در تب تنظیمات هست')
        else:
            r = len(col) + 1
            ws.update_cell(r, 1, 'WIN_COMBO_ENABLED')
            ws.update_cell(r, 2, 'بله')
            ws.update_cell(r, 3, 'G-wincombo: هندسهٔ per-symbol از تب «ترکیب برنده» (بله/خیر)')
            print('✓ ردیف WIN_COMBO_ENABLED در تب تنظیمات درج شد (ردیف %d) = بله' % r)

        def _val(key, default):
            try:
                c = [str(x).strip() for x in ws.col_values(1)]
                return str(ws.cell(c.index(key) + 1, 2).value or default)
            except Exception:
                return default
        _st = SimpleNamespace(
            win_combo_enabled=True,
            sl_atr_mult=win_combo.fnum(_val('SL_ATR_MULT', '1.5')) or 1.5,
            tp_atr_mult=win_combo.fnum(_val('TP_ATR_MULT', '3')) or 3.0,
            trail_atr_mult=win_combo.fnum(_val('TRAIL_ATR_MULT', '0.5')) or 0.5,
            max_sl_band_pct=win_combo.fnum(_val('MAX_SL_BAND_PCT', '8')) or 8.0)

        class _WS:
            spreadsheet = sh
        params = win_combo.refresh_after_close(_WS(), _st) or {}
        print('✓ تب «ترکیب برنده» ساخته/به‌روز شد — نمادهای واجد شرایط: %d' % len(params))
        for k, v in sorted(params.items())[:10]:
            print('   %s: SL%%=%.2f | TP%%=%.2f | ضریب تریل=%.2f'
                  % (k, v['sl_pct'], v['tp_pct'], v['trail_mult']))
        if not params:
            print('   (هنوز نمادی به n≥6 و ≥2برد و ≥2باخت نرسیده — با هر خروج تازه به‌روز می‌شود)')
    except Exception as e:
        print('⚠️ راه‌اندازی شیت ناموفق (%s) — تیک بعدی کرون خودش تب را می‌سازد' % e)


def main():
    print('========== G-wincombo v3 | deploy=%s ==========' % DEPLOY)
    write_win_combo()
    run_tests()

    with open('trader.py', encoding='utf-8') as f:
        tsrc = f.read()
    with open('settings.py', encoding='utf-8') as f:
        ssrc = f.read()

    print('---------- بررسی انکرها ----------')
    ok = True
    for old, new, cnt, name in TRADER_PATCHES:
        c = tsrc.count(old)
        print('trader.py  | %-18s انتظار %d | پیدا %d %s' % (name, cnt, c, '✓' if c == cnt else '⛔'))
        ok = ok and c == cnt
    for old, new, cnt, name in SETTINGS_PATCHES:
        c = ssrc.count(old)
        print('settings.py| %-18s انتظار %d | پیدا %d %s' % (name, cnt, c, '✓' if c == cnt else '⛔'))
        ok = ok and c == cnt
    fa_new = patch_fillanchor(tsrc)
    ok = ok and (fa_new is not None)
    if not ok:
        print('⛔ انکر ناهمخوان — سورس تغییر کرده (نشست موازی؟). هیچ فایلی پچ نشد.')
        sys.exit(1)

    print('---------- پیش‌نمایش ----------')
    for old, new, cnt, name in TRADER_PATCHES + SETTINGS_PATCHES:
        added = [l for l in new.split('\n') if l and l not in old]
        print('[%s] +%d خط | نمونه: %s' % (name, len(added), (added[0] if added else '')[:80]))
    print('[fillanchor] جایگزینی ۲+۲ خط: new_sl/new_tp = حفظ فاصلهٔ مطلق از سیگنال')

    if not DEPLOY:
        print('\nحالت خشک: trader.py/settings.py دست‌نخورده. برای دیپلوی:')
        print('  timeout 300 venv/bin/python apply_win_combo.py --deploy')
        return

    print('---------- دیپلوی ----------')
    shutil.copy2('trader.py', 'trader.py.bak-wincombo')
    shutil.copy2('settings.py', 'settings.py.bak-wincombo')
    tsrc = fa_new
    for old, new, cnt, name in TRADER_PATCHES:
        tsrc = tsrc.replace(old, new)
    assert tsrc.count('G-wincombo') >= 3, 'هوک‌ها در سورس نهایی نیستند — دیپلوی متوقف (هنوز چیزی نوشته نشده)'
    for old, new, cnt, name in SETTINGS_PATCHES:
        ssrc = ssrc.replace(old, new)
    with open('trader.py', 'w', encoding='utf-8') as f:
        f.write(tsrc)
    with open('settings.py', 'w', encoding='utf-8') as f:
        f.write(ssrc)
    py_compile.compile('trader.py', doraise=True)
    py_compile.compile('settings.py', doraise=True)
    py_compile.compile('win_combo.py', doraise=True)
    print('✓ پچ اعمال + py_compile هر سه فایل سبز (بکاپ: .bak-wincombo)')

    # راستی‌آزمایی فراتر از py_compile: import واقعی کد پچ‌شده
    import importlib
    import settings as _s
    importlib.reload(_s)
    assert _s.DEFAULT_TRADING.get('WIN_COMBO_ENABLED') == 'بله'
    with open('trader.py', encoding='utf-8') as f:
        _tchk = f.read()
    try:
        assert _tchk.count('G-wincombo') >= 3, 'هوک‌های wincombo در trader.py نوشته نشدند'
        assert 'win_combo_enabled' in open('settings.py', encoding='utf-8').read(), 'کلید settings نوشته نشد'
    except AssertionError as _e:
        print('⛔ %s → بازگردانی بکاپ' % _e)
        shutil.copy2('trader.py.bak-wincombo', 'trader.py')
        shutil.copy2('settings.py.bak-wincombo', 'settings.py')
        sys.exit(1)
    try:
        import trader
        print('✓ import trader.py (پچ‌شده) بدون خطا')
    except Exception as e:
        print('⛔ import trader.py پس از پچ شکست خورد: %s → بازگردانی بکاپ' % e)
        shutil.copy2('trader.py.bak-wincombo', 'trader.py')
        shutil.copy2('settings.py.bak-wincombo', 'settings.py')
        sys.exit(1)

    post_deploy_sheet_setup()

    msg = ('G-wincombo: تب «ترکیب برنده» — SL%/TP%/ضریب تریلینگ بهینهٔ per-symbol از تب '
           'تحلیل معاملات (میانه برد/باخت + خارَچ تریل + شرامپ w=n/(n+8))؛ هوک‌های '
           'buy_one/apply_trailing/_record_analysis؛ fillanchor حفظ فاصلهٔ مطلق؛ کلید WIN_COMBO_ENABLED')
    for cmd in (['git', 'add', 'win_combo.py', 'apply_win_combo.py', 'trader.py', 'settings.py'],
                ['git', 'commit', '-m', msg],
                ['git', 'push']):
        r = subprocess.run(cmd, capture_output=True, text=True)
        out = (r.stdout or r.stderr or '').strip().split('\n')
        print('$', ' '.join(cmd[:3]), '→', out[-1][:120] if out else r.returncode)
    print('========== پایان — تیک بعدی کرون (حداکثر ۵ دقیقه) لایو می‌شود ==========')


if __name__ == '__main__':
    main()
