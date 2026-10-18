#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_guards_duty.py - add duty column to guards tab"""
import os, sys, shutil, py_compile, time

DEPLOY = '--deploy' in sys.argv

# ─── پچ ۱: افزودن GUARDS_DUTY بعد از GUARDS_DEFS ───
T1_OLD = """def _guard_active(st, cond):
    if cond is True:
        return True
    if cond is False:
        return False
    return bool(getattr(st, cond, 0))"""

T1_NEW = '''GUARDS_DUTY = {
    'سقف روزانه معاملات': 'جلوگیری از ثبت بیش از حداکثر تعداد معامله در یک روز',
    'پوزیشن/سفارش باز': 'جلوگیری از ورود همزمان به نمادی که پوزیشن باز دارد',
    'same-cycle': 'جلوگیری از خرید مجدد نمادی که در همان چرخه بسته شده',
    'کول‌داون ناموفق': 'صبر بعد از سفارش ناموفق (UnexpectedMarketPrice و غیره)',
    'کول‌داون زیان‌ده': 'صبر بعد از خروج زیان‌ده برای جلوگیری از ورود مجدد سریع',
    'سقف پوزیشن باز': 'جلوگیری از باز کردن پوزیشن جدید وقتی حداکثر پوزیشن‌های باز تکمیل شده',
    'باند SL/TP': 'رد ورود اگر باند SL/TP زیر حداقل هزینه باشد (TP<1.5٪ یا SL<1.0٪)',
    'G-slbuf': 'رد ورود اگر بافر SL نسبت به fill تخمینی کمتر از 0.5٪ باشد',
    'G-bandcap': 'رد نمادهای پرنوسان (عرض SL > 8٪) مثل STRK و WAL',
    'G-global': 'رد نمادهای بدون داده جهانی (mark=0) مثل COPXON و SLVON',
    'G-premium': 'رد ورود اگر پریمیوم محلی/جهانی > 10٪ (ریسک نوسان تومانی)',
    'G-mark-dev': 'رد ورود اگر قیمت محلی > 2٪ بالاتر از جهانی (پامپ محلی بدون پشتوانه)',
    'مومنتوم 5٪': 'رد ورود اگر قیمت بیش از 5٪ بالاتر از SMA20(1h) باشد (اشباع خرید)',
    'چاقو (knife)': 'صبر بعد از N خروج زیان‌ده در پنجره زمانی (جلوگیری از سقوط روی چاقو)',
    'روند BTC 4h': 'مسدود کردن همه خریدها وقتی BTC نزولی است (SMA20<SMA50)',
    'AUTO_BLOCK': 'مسدود کردن نمادهای زیان‌ده (هر 48 ساعت چرخه)',
    'موجودی USDT': 'رد ورود اگر موجودی USDT کافی نباشد',
    'limit TTL': 'لغو سفارش limit کهنه اگر پس از 60 دقیقه پر نشود',
    'G-volsize': 'برابرسازی ریسک دلاری هر معامله (cap $0.50)',
    'G-maxsl (بک‌تست)': 'محدود کردن ضریب SL از بک‌تست به 1.5× (جلوگیری از زیان شدید)',
}


def _guard_active(st, cond):
    if cond is True:
        return True
    if cond is False:
        return False
    return bool(getattr(st, cond, 0))'''

# ─── پچ ۲: به‌روزرسانی header و row building در write_guards_status ───
# الف) ایجاد تب جدید (cols=8 + header با 8 ستون)
T2_OLD = """            ws = sh.add_worksheet(title=GUARDS_TAB, rows=30, cols=7)
            ws.update(values=[['پایش زنده گاردها', 'به‌روزرسانی:', jnow()]],
                      range_name='A1:C1')
            ws.update(values=[['نام گارد', 'وضعیت', 'آخرین رد', 'نماد', 'علت', 'تعداد امروز', 'یادداشت']],
                      range_name='A3:G3')
            ws.freeze(rows=3)"""

T2_NEW = """            ws = sh.add_worksheet(title=GUARDS_TAB, rows=30, cols=8)
            ws.update(values=[['پایش زنده گاردها', 'به‌روزرسانی:', jnow()]],
                      range_name='A1:C1')
            ws.update(values=[['نام گارد', 'وظیفه', 'وضعیت', 'آخرین رد', 'نماد', 'علت', 'تعداد امروز', 'یادداشت']],
                      range_name='A3:H3')
            ws.freeze(rows=3)"""

# ب) row building (افزودن duty به هر ردیف)
T3_OLD = """            rows.append([name, status, last_time, last_sym, last_reason, count, note])"""

T3_NEW = """            duty = GUARDS_DUTY.get(name, '')
            rows.append([name, duty, status, last_time, last_sym, last_reason, count, note])"""

# ج) به‌روزرسانی header در هر اجرا (cols=8)
T4_OLD = """        ws.update(values=[['پایش زنده گاردها', 'به‌روزرسانی:', jnow()]],
                  range_name='A1:C1')
        ws.update(values=[['نام گارد', 'وضعیت', 'آخرین رد', 'نماد', 'علت', 'تعداد امروز', 'یادداشت']],
                  range_name='A3:G3')
        data = rows + [[''] * 7] * max(0, 25 - len(rows))
        ws.update(values=data, range_name='A4:G%d' % (4 + len(data) - 1))"""

T4_NEW = """        # گسترش ستون‌ها اگر تب قدیمی با 7 ستون ساخته شده بود
        if ws.col_count < 8:
            ws.add_cols(8 - ws.col_count)
        ws.update(values=[['پایش زنده گاردها', 'به‌روزرسانی:', jnow()]],
                  range_name='A1:C1')
        ws.update(values=[['نام گارد', 'وظیفه', 'وضعیت', 'آخرین رد', 'نماد', 'علت', 'تعداد امروز', 'یادداشت']],
                  range_name='A3:H3')
        data = rows + [[''] * 8] * max(0, 25 - len(rows))
        ws.update(values=data, range_name='A4:H%d' % (4 + len(data) - 1))"""

CHANGES = {
    'trader.py': [(T1_OLD, T1_NEW, 'GUARDS_DUTY dictionary'),
                  (T2_OLD, T2_NEW, 'header with duty column (new tab)'),
                  (T3_OLD, T3_NEW, 'row building with duty'),
                  (T4_OLD, T4_NEW, 'header refresh + cols expand (existing tab)')],
}


def main():
    os.chdir(os.path.expanduser('~/nobitex-usdt'))
    print('=' * 72)
    print('apply_guards_duty.py - add duty column to guards tab')
    print('mode: DEPLOY' if DEPLOY else 'mode: DRY-RUN (preview only)')
    print('=' * 72)
    all_ok = True
    applied = []
    fname = 'trader.py'
    if not os.path.exists(fname):
        print('X %s not found' % fname)
        sys.exit(1)
    src = open(fname, encoding='utf-8').read()
    cand = src
    file_ok = True
    for old, new, desc in CHANGES[fname]:
        if old in cand:
            cand = cand.replace(old, new, 1)
            print('+ %s: %s' % (fname, desc))
            applied.append((fname, desc))
        else:
            print('X %s: pattern not found: %s' % (fname, desc))
            print('  expected: %s...' % old[:80])
            file_ok = False
            all_ok = False
    if not file_ok:
        sys.exit(1)
    cand_name = 'trader_candidate.py'
    with open(cand_name, 'w', encoding='utf-8') as f:
        f.write(cand)
    try:
        py_compile.compile(cand_name, doraise=True)
        print('  + py_compile: OK')
    except py_compile.PyCompileError as e:
        print('  X py_compile FAILED: %s' % e)
        sys.exit(1)
    if DEPLOY:
        bak = '%s.bak.%s' % (fname, time.strftime('%Y%m%d_%H%M'))
        shutil.copy2(fname, bak)
        print('  + backup: %s' % bak)
        shutil.move(cand_name, fname)
        print('  + deployed: %s' % fname)
    else:
        print('  (dry-run: candidate saved as %s)' % cand_name)
    print()
    print('=' * 72)
    print('+ %d patches ready' % len(applied))
    if DEPLOY:
        print('Deploy complete. Wait 5 min, then check tab.')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python apply_guards_duty.py --deploy')
    print('=' * 72)


if __name__ == '__main__':
    main()
