# -*- coding: utf-8 -*-
"""apply_v4.py — G-wincombo v4 «حاکمیت تب» (اجازهٔ اپراتور 1405/08/04).
دو جراحی در trader.py (کپ G-cap2 سایت تک‌fill و سایت VWAP) + رفع مهر تهران در win_combo._now.
بدون --deploy = خشک: assert + کامپایل روی فایل موقت + پیش‌نمایش (هیچ فایلی دست نمی‌خورد).
با --deploy = نوشتن + py_compile + import تست + git commit/push + rollback خودکار."""
import io, os, py_compile, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))

SITE1_OLD = '''                    _tp_max = _fill_px * (1 + 0.80 / 100.0)
                    _sl_min = _fill_px * (1 - 1.00 / 100.0)
                    if _tp_new > _tp_max:
                        _tp_new = _tp_max
                    if _sl_new < _sl_min:
                        _sl_new = _sl_min
'''
SITE1_NEW = '''                    # G-wincombo v4 (حاکمیت تب — اجازهٔ اپراتور 1405/08/04): نماد داخل
                    # تب «ترکیب برنده» از کپ G-cap2 عبور می‌کند؛ شیفت لنگر می‌ماند و
                    # باند تب حول fill حفظ می‌شود. خطا/خالی → کپ (fail-open به رفتار فعلی).
                    _wc_skip_cap = False
                    try:
                        import win_combo as _wc_m
                        _wc_p = _wc_m.get_params(ws_t, st)
                        _wc_skip_cap = bool(_wc_p and sym_c in _wc_p)
                    except Exception:
                        _wc_skip_cap = False
                    if _wc_skip_cap:
                        log.info('G-wincombo v4 %s: عبور از کپ — باند تب حول fill حفظ شد (SL=%s | TP=%s)',
                                 sym_c, fmt_price(_sl_new), fmt_price(_tp_new))
                    if not _wc_skip_cap:
                        _tp_max = _fill_px * (1 + 0.80 / 100.0)
                        _sl_min = _fill_px * (1 - 1.00 / 100.0)
                        if _tp_new > _tp_max:
                            _tp_new = _tp_max
                        if _sl_new < _sl_min:
                            _sl_new = _sl_min
'''
SITE2_OLD = '''                        _tp_max = _fill_px * (1 + 0.88 / 100.0)
                        _sl_min = _fill_px * (1 - 1.10 / 100.0)
                        if _tp_new > _tp_max:
                            _tp_new = _tp_max
                        if _sl_new < _sl_min:
                            _sl_new = _sl_min
'''
SITE2_NEW = '''                        # G-wincombo v4 (حاکمیت تب — اجازهٔ اپراتور 1405/08/04): گارد
                        # عبور از کپ برای نمادهای تب — همان قاعدهٔ سایت ۱ (VWAP scale-in).
                        _wc_skip_cap = False
                        try:
                            import win_combo as _wc_m
                            _wc_p = _wc_m.get_params(ws_t, st)
                            _wc_skip_cap = bool(_wc_p and sym_c in _wc_p)
                        except Exception:
                            _wc_skip_cap = False
                        if _wc_skip_cap:
                            log.info('G-wincombo v4 %s: عبور از کپ (VWAP) — باند تب حفظ شد (SL=%s | TP=%s)',
                                     sym_c, fmt_price(_sl_new), fmt_price(_tp_new))
                        if not _wc_skip_cap:
                            _tp_max = _fill_px * (1 + 0.88 / 100.0)
                            _sl_min = _fill_px * (1 - 1.10 / 100.0)
                            if _tp_new > _tp_max:
                                _tp_new = _tp_max
                            if _sl_new < _sl_min:
                                _sl_new = _sl_min
'''
NOW_OLD = '''def _now():
    try:
        import jdatetime
        return jdatetime.datetime.now().strftime('%Y/%m/%d %H:%M')
    except Exception:
        return time.strftime('%Y/%m/%d %H:%M', time.gmtime())
'''
NOW_NEW = '''def _now():
    """مهر تهران (G-wincombo v4): قبلاً ساعت میزبان (EDT) به‌جای تهران نوشته می‌شد."""
    try:
        import jdatetime
        import datetime as _dt
        try:
            from zoneinfo import ZoneInfo
            _teh = _dt.datetime.now(ZoneInfo('Asia/Tehran')).replace(tzinfo=None)
        except Exception:
            _teh = _dt.datetime.utcnow() + _dt.timedelta(hours=3, minutes=30)
        return jdatetime.datetime.fromgregorian(datetime=_teh).strftime('%Y/%m/%d %H:%M')
    except Exception:
        return time.strftime('%Y/%m/%d %H:%M', time.gmtime())
'''

def load(p):
    with io.open(os.path.join(ROOT, p), encoding='utf-8') as f:
        return f.read()

def main():
    deploy = '--deploy' in sys.argv
    tr, wc = load('trader.py'), load('win_combo.py')

    for name, src, anc in (('trader/سایت۱', tr, SITE1_OLD), ('trader/سایت۲', tr, SITE2_OLD),
                           ('win_combo/_now', wc, NOW_OLD)):
        c = src.count(anc)
        assert c == 1, 'انکر %s تعداد %d بار یافت شد (انتظار: ۱) — لغو' % (name, c)
    assert tr.count('win_combo') == 6, 'ارجاع win_combo قبل از پچ = %d (انتظار ۶)' % tr.count('win_combo')

    tr_new = tr.replace(SITE1_OLD, SITE1_NEW).replace(SITE2_OLD, SITE2_NEW)
    wc_new = wc.replace(NOW_OLD, NOW_NEW)

    assert tr_new.count('win_combo') == 8, 'بعد از پچ باید ۸ ارجاع باشد (۶+۲ import)'
    assert tr_new.count('G-wincombo v4') == 4, 'دو سایت v4 (کامنت+لاگ در هر سایت) باید ثبت شده باشند'
    assert tr_new.count('_wc_skip_cap') == 10, 'دو بلوک گارد باید سالم باشند'
    assert 'fromgregorian' in wc_new, 'رفع مهر تهران ثبت نشد'
    for keep in ('win_combo.refresh_after_close(ws_t, st)',
                 '_wcp = win_combo.get_params(ws_t, st)',
                 '_wct = win_combo.get_params(ws_t, st)'):
        assert keep in tr_new, 'هوک موجود آسیب دیده: %s' % keep
    assert '0.80 / 100.0' in tr_new and '0.88 / 100.0' in tr_new, 'کپ‌ها برای غیرتب باید بمانند'

    d = tempfile.mkdtemp()
    for name, src in (('trader_v4.py', tr_new), ('win_combo_v4.py', wc_new)):
        p = os.path.join(d, name)
        with io.open(p, 'w', encoding='utf-8') as f:
            f.write(src)
        py_compile.compile(p, doraise=True)
    print('OK خشک: انکرها ۱/۱ | گاردها ثبت | هوک‌ها سالم | هر دو فایل کامپایل شدند')

    if not deploy:
        lines = tr_new.splitlines()
        for i, ln in enumerate(lines):
            if 'G-wincombo v4' in ln and 'log.info' not in ln:
                print('--- trader.py:%d ---' % (i + 1))
                print('\n'.join(lines[i - 2:i + 3]))
        print('برای دیپلوی: venv/bin/python apply_v4.py --deploy')
        return

    b1 = os.path.join(ROOT, 'trader.py.bak-v4')
    b2 = os.path.join(ROOT, 'win_combo.py.bak-v4')
    shutil.copy2(os.path.join(ROOT, 'trader.py'), b1)
    shutil.copy2(os.path.join(ROOT, 'win_combo.py'), b2)
    try:
        for p, src in (('trader.py', tr_new), ('win_combo.py', wc_new)):
            with io.open(os.path.join(ROOT, p), 'w', encoding='utf-8') as f:
                f.write(src)
            py_compile.compile(os.path.join(ROOT, p), doraise=True)
        r = subprocess.run([sys.executable, '-c',
                            'import trader, win_combo; print("import ok | TTL =", win_combo.CACHE_TTL)'],
                           cwd=ROOT, capture_output=True, text=True, timeout=60)
        print((r.stdout + r.stderr).strip()[:300])
        assert r.returncode == 0, 'import تست شکست خورد'
        subprocess.run(['git', 'add', 'trader.py', 'win_combo.py', 'apply_v4.py'], cwd=ROOT)
        rc = subprocess.run(['git', 'commit', '-m',
                             'G-wincombo v4: حاکمیت تب — عبور نمادهای تب از کپ G-cap2 (سایت تک‌fill و VWAP) '
                             'با fail-open به کپ؛ شیفت لنگر حفظ؛ رفع مهر تهران در win_combo._now (اجازهٔ اپراتور 1405/08/04)'],
                            cwd=ROOT, capture_output=True, text=True)
        print((rc.stdout + rc.stderr).strip()[:300])
        rp = subprocess.run(['git', 'push'], cwd=ROOT, capture_output=True, text=True)
        print('push:', (rp.stdout + rp.stderr).strip()[:200])
        print('DEPLOY شد ✅')
    except Exception as e:
        shutil.copy2(b1, os.path.join(ROOT, 'trader.py'))
        shutil.copy2(b2, os.path.join(ROOT, 'win_combo.py'))
        print('ROLLBACK انجام شد:', e)
        raise

if __name__ == '__main__':
    main()
