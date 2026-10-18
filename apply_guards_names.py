#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_guards_names.py - align guard names with settings keys"""
import os, sys, shutil, py_compile, time

DEPLOY = '--deploy' in sys.argv

# جایگزینی کلیدهای فارسی با کلیدهای انگلیسی متناظر در تب تنظیمات
T_OLD = '''GUARDS_DEFS = [
    ('سقف روزانه معاملات',   'سقف معاملات روزانه',           True),
    ('پوزیشن/سفارش باز',     'پوزیشن یا سفارش باز موجود',     True),
    ('same-cycle',           'خروج در همین چرخه',            True),
    ('کول‌داون ناموفق',       'سفارش ناموفق در',              'order_fail_cooldown_min'),
    ('کول‌داون زیان‌ده',       'خروج زیان‌ده در',              'reentry_cooldown_min'),
    ('سقف پوزیشن باز',       'سقف پوزیشن باز',               True),
    ('باند SL/TP',           'باند SL/TP زیر حداقل',         True),
    ('G-slbuf',              'SL buffer',                    True),
    ('G-bandcap',            'SL band',                       True),
    ('G-global',             'no global mark price',          True),
    ('G-premium',            'local premium',                True),
    ('G-mark-dev',           'above global mark',            True),
    ('مومنتوم 5٪',           'momentum exhaustion',          'pump_guard_pct'),
    ('چاقو (knife)',         'losing exits in last',         'loss_streak_limit'),
    ('روند BTC 4h',          'market regime bearish',        'trend_filter_enabled'),
    ('AUTO_BLOCK',           'symbol blocked',               True),
    ('موجودی USDT',          'موجودی USDT کافی نیست',        True),
    ('limit TTL',            'سفارش ورود کهنه لغو شد',       True),
    ('G-volsize',            'G-volsize',                     True),
    ('G-maxsl (بک‌تست)',      'G-maxsl',                      'use_bt_params'),
]'''

T_NEW = '''GUARDS_DEFS = [
    ('MAX_DAILY_TRADES',     'سقف معاملات روزانه',           True),
    ('MAX_OPEN_POSITIONS',   'پوزیشن یا سفارش باز موجود',     True),
    ('SAME_CYCLE',           'خروج در همین چرخه',            True),
    ('ORDER_FAIL_COOLDOWN_MIN', 'سفارش ناموفق در',            'order_fail_cooldown_min'),
    ('REENTRY_COOLDOWN_MIN', 'خروج زیان‌ده در',              'reentry_cooldown_min'),
    ('MAX_OPEN_POSITIONS',   'سقف پوزیشن باز',               True),
    ('BAND_SL_TP',           'باند SL/TP زیر حداقل',         True),
    ('G_SLBUF',              'SL buffer',                    True),
    ('G_BANDCAP',            'SL band',                       True),
    ('G_GLOBAL',             'no global mark price',          True),
    ('MAX_LOCAL_PREMIUM_PCT','local premium',                True),
    ('MAX_MARK_DEVIATION_PCT','above global mark',            True),
    ('PUMP_GUARD_PCT',       'momentum exhaustion',          'pump_guard_pct'),
    ('LOSS_STREAK_LIMIT',    'losing exits in last',         'loss_streak_limit'),
    ('TREND_FILTER_ENABLED', 'market regime bearish',        'trend_filter_enabled'),
    ('BLOCKED_SYMBOLS',      'symbol blocked',               True),
    ('MIN_USDT_BALANCE',     'موجودی USDT کافی نیست',        True),
    ('ENTRY_TTL_MIN',        'سفارش ورود کهنه لغو شد',       True),
    ('RISK_TARGET_USDT',     'G-volsize',                     True),
    ('MAX_SL_MULT',          'G-maxsl',                      'use_bt_params'),
]'''

# همچنین به‌روزرسانی کلیدهای دیکشنری GUARDS_DUTY
T2_OLD = '''GUARDS_DUTY = {
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
}'''

T2_NEW = '''GUARDS_DUTY = {
    'MAX_DAILY_TRADES': 'جلوگیری از ثبت بیش از حداکثر تعداد معامله در یک روز',
    'MAX_OPEN_POSITIONS': 'جلوگیری از ورود همزمان به نمادی که پوزیشن باز دارد',
    'SAME_CYCLE': 'جلوگیری از خرید مجدد نمادی که در همان چرخه بسته شده',
    'ORDER_FAIL_COOLDOWN_MIN': 'صبر بعد از سفارش ناموفق (UnexpectedMarketPrice و غیره)',
    'REENTRY_COOLDOWN_MIN': 'صبر بعد از خروج زیان‌ده برای جلوگیری از ورود مجدد سریع',
    'BAND_SL_TP': 'رد ورود اگر باند SL/TP زیر حداقل هزینه باشد (TP<1.5٪ یا SL<1.0٪)',
    'G_SLBUF': 'رد ورود اگر بافر SL نسبت به fill تخمینی کمتر از 0.5٪ باشد',
    'G_BANDCAP': 'رد نمادهای پرنوسان (عرض SL > 8٪) مثل STRK و WAL',
    'G_GLOBAL': 'رد نمادهای بدون داده جهانی (mark=0) مثل COPXON و SLVON',
    'MAX_LOCAL_PREMIUM_PCT': 'رد ورود اگر پریمیوم محلی/جهانی > 10٪ (ریسک نوسان تومانی)',
    'MAX_MARK_DEVIATION_PCT': 'رد ورود اگر قیمت محلی > 2٪ بالاتر از جهانی (پامپ محلی بدون پشتوانه)',
    'PUMP_GUARD_PCT': 'رد ورود اگر قیمت بیش از 5٪ بالاتر از SMA20(1h) باشد (اشباع خرید)',
    'LOSS_STREAK_LIMIT': 'صبر بعد از N خروج زیان‌ده در پنجره زمانی (جلوگیری از سقوط روی چاقو)',
    'TREND_FILTER_ENABLED': 'مسدود کردن همه خریدها وقتی BTC نزولی است (SMA20<SMA50)',
    'BLOCKED_SYMBOLS': 'مسدود کردن نمادهای زیان‌ده (هر 48 ساعت چرخه)',
    'MIN_USDT_BALANCE': 'رد ورود اگر موجودی USDT کافی نباشد',
    'ENTRY_TTL_MIN': 'لغو سفارش limit کهنه اگر پس از 60 دقیقه پر نشود',
    'RISK_TARGET_USDT': 'برابرسازی ریسک دلاری هر معامله (cap $0.50)',
    'MAX_SL_MULT': 'محدود کردن ضریب SL از بک‌تست به 1.5× (جلوگیری از زیان شدید)',
}'''

CHANGES = {
    'trader.py': [(T_OLD, T_NEW, 'Update GUARDS_DEFS names to English keys'),
                  (T2_OLD, T2_NEW, 'Update GUARDS_DUTY keys to English')]
}

def main():
    os.chdir(os.path.expanduser('~/nobitex-usdt'))
    print('=' * 72)
    print('apply_guards_names.py - Align guard names with settings keys')
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
        print('  cd ~/nobitex-usdt && venv/bin/python apply_guards_names.py --deploy')
    print('=' * 72)

if __name__ == '__main__':
    main()
