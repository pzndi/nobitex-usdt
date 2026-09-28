#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_sheets.py — ساخت تب‌های «تنظیمات»، «استراتژی»، «معاملات» و «کیف پول»
اجرا:
    venv/bin/python setup_sheets.py           # تب موجود را دست نمی‌زند
    venv/bin/python setup_sheets.py --force   # تب‌های موجود را پاک و با پیش‌فرض‌ها از نو می‌سازد
"""
import sys
from datetime import datetime

import gspread

try:
    import jdatetime
    def now_str():
        return jdatetime.datetime.now().strftime('%Y/%m/%d %H:%M')
except ImportError:
    def now_str():
        return datetime.now().strftime('%Y-%m-%d %H:%M')


def load_env(path='.env'):
    vals = {}
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                vals[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return vals


FORCE = '--force' in sys.argv
SHEET_ID = load_env().get('SHEET_ID', '12jH8m1RhENtFmJszzHjKAu79oYizA-NfTmBmDDBt0eM')

# ---------------- محتوای تب «تنظیمات» ----------------
# ساختار: کلید | مقدار (تنها ستون قابل ویرایش ✏️) | جزئیات | توضیح

INDICATORS = [
    ('SMA',   'بله', 'fast=20;slow=50', 'میانگین متحرک ساده — جهت روند'),
    ('EMA',   'بله', 'fast=9;slow=21', 'میانگین متحرکی نمایی — سیگنال سریع‌تر'),
    ('RSI',   'بله', 'period=14;oversold=30;overbought=70', 'قدرت نسبی — اشباع خرید/فروش'),
    ('MACD',  'بله', 'fast=12;slow=26;signal=9', 'مومنتوم — همگرایی/واگرایی'),
    ('BB',    'بله', 'period=20;std=2.0', 'باندهای بولینگر — بازگشت از باند'),
    ('STOCH', 'خیر', 'k=14;d=3;smooth=3', 'استوکاستیک — اشباع خرید/فروش'),
    ('OBV',   'خیر', 'period=20', 'حجم روی تعادل — تأیید روند با حجم'),
    ('CCI',   'خیر', 'period=20', 'شاخص کانال کالا'),
    ('WPR',   'خیر', 'period=14', 'درصد ویلیامز'),
    ('ATR',   'بله', 'period=14', 'زیرساخت حد ضرر/سود — همیشه محاسبه می‌شود (رأی ندارد)'),
]

TIMEFRAMES = [
    ('1m',  'خیر', '1',   ''),
    ('5m',  'خیر', '5',   ''),
    ('15m', 'بله', '15',  'پیش‌فرض فعال'),
    ('30m', 'خیر', '30',  ''),
    ('1h',  'بله', '60',  'پیش‌فرض فعال'),
    ('3h',  'خیر', '180', ''),
    ('4h',  'بله', '240', 'پیش‌فرض فعال'),
    ('6h',  'خیر', '360', ''),
    ('12h', 'خیر', '720', ''),
    ('1D',  'بله', '1D',  'پیش‌فرض فعال'),
    ('2D',  'خیر', '2D',  ''),
    ('3D',  'خیر', '3D',  ''),
]

TRADING = [
    ('TRADING_ENABLED',    'خیر',   'معاملات فعال',           'کلید اصلی — تا «بله» نشود، هیچ سفارشی ثبت نمی‌شود و فقط سیگنال تولید می‌گردد'),
    ('DRY_RUN',            'بله',   'حالت آزمایشی',           'بله = سفارش فقط در تب «معاملات» ثبت می‌شود بدون ارسال به صرافی. برای معامله واقعی «خیر» کنید'),
    ('MAX_DAILY_TRADES',   '10',    'حداکثر معاملات روزانه',  'سقف سفارش جدید در هر روز شمسی — شمارش از تاریخچه واقعی API نوبیتکس'),
    ('ORDER_TYPE',         'market','نوع سفارش',              'market = با قیمت لحظه‌ای و فوری | limit = با قیمت مشخص'),
    ('ORDER_SIZE_USDT',    '50',    'مبلغ هر خرید (USDT)',    'مبلغ ثابت هر سفارش خرید'),
    ('MAX_OPEN_POSITIONS', '3',     'حداکثر پوزیشن باز',      'پس از رسیدن به این تعداد، سیگنال خرید جدید نادیده گرفته می‌شود'),
    ('MIN_USDT_BALANCE',   '20',    'حداقل باقی‌مانده (USDT)', 'خرید جدید انجام نمی‌شود اگر موجودی USDT به زیر این عدد برسد'),
    ('SL_ATR_MULT',        '2.0',   'ضریب حد ضرر (×ATR)',     'حد ضرر = قیمت ورود − این عدد × ATR'),
    ('TP_ATR_MULT',        '3.0',   'ضریب حد سود (×ATR)',     'حد سود = قیمت ورود + این عدد × ATR'),
]

GENERAL = [
    ('TOP_N',                '10',     'تعداد نماد برتر',            'تعداد نماد در تب dynamic universe'),
    ('MIN_VOLUME_USDT',      '100000', 'حداقل حجم ۲۴ ساعته (USDT)', 'فیلتر نقدشوندگی بازارها'),
    ('SIGNAL_THRESHOLD_PCT', '70',     'آستانه صدور سیگنال (٪)',    'حداقل درصد آرای هم‌جهت بین اندیکاتورهای فعالِ رأی‌دهنده'),
    ('CANDLE_LOOKBACK',      '300',    'تعداد کندل تحلیل',           'سقف API نوبیتکس: ۵۰۰ کندل در هر درخواست'),
]

STRAT_HEADERS  = ['نماد', 'تایم‌فریم', 'قیمت', 'روند', 'سیگنال', 'قدرت٪', 'موافق', 'مخالف', 'خنثی', 'حد ضرر', 'حد سود', 'توضیح']
TRADE_HEADERS  = ['زمان', 'نماد', 'عملیات', 'تایم‌فریم', 'دلیل', 'قیمت', 'مقدار', 'مبلغ USDT', 'حد ضرر', 'حد سود', 'شناسه سفارش', 'وضعیت', 'پیام']
WALLET_HEADERS = ['کیف پول', 'موجودی کل', 'بلوکه', 'قابل استفاده', 'ارزش (USDT)', 'آخرین به‌روزرسانی']

# ---------------- ساخت ردیف‌ها ----------------
ROWS, SECTION_ROWS, HEADER_ROWS = [], [], []

def add_section(title):
    ROWS.append([title, '', '', ''])
    SECTION_ROWS.append(len(ROWS))

def add_headers():
    ROWS.append(['کلید', 'مقدار ✏️', 'جزئیات', 'توضیح'])
    HEADER_ROWS.append(len(ROWS))

add_section('📊 اندیکاتورها — فعال/غیرفعال: ستون «مقدار» را بله/خیر کنید (پارامترها در «جزئیات»)')
add_headers()
ROWS.extend(list(r) for r in INDICATORS)
ROWS.append(['', '', '', ''])

add_section('⏱ تایم‌فریم‌ها — فقط موارد «بله» در هر اجرا تحلیل می‌شوند (فهرست رسمی API نوبیتکس)')
add_headers()
ROWS.extend(list(r) for r in TIMEFRAMES)
ROWS.append(['', '', '', ''])

add_section('💰 تنظیمات معاملات — رفتار معاملاتی ربات از این بخش کنترل می‌شود')
add_headers()
ROWS.extend(list(r) for r in TRADING)
ROWS.append(['', '', '', ''])

add_section('⚙️ تنظیمات عمومی — فیلترها و آستانه‌های تحلیل')
add_headers()
ROWS.extend(list(r) for r in GENERAL)
ROWS.append(['', '', '', ''])

ALERT_ROW = len(ROWS) + 1
ROWS.append(['🔐 کلیدهای حساس (API) فقط در فایل .env روی سرور — هرگز در این شیت وارد نشوند', '', '', ''])

# ---------------- فرمت‌ها ----------------
FMT_SECTION = {'backgroundColor': {'red': 0.85, 'green': 0.90, 'blue': 0.98},
               'textFormat': {'bold': True}}
FMT_HEADER  = {'backgroundColor': {'red': 0.25, 'green': 0.44, 'blue': 0.72},
               'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}}}
FMT_EDIT    = {'backgroundColor': {'red': 1.0, 'green': 0.97, 'blue': 0.80}}
FMT_ALERT   = {'backgroundColor': {'red': 0.99, 'green': 0.85, 'blue': 0.85},
               'textFormat': {'bold': True, 'foregroundColor': {'red': 0.6, 'green': 0.1, 'blue': 0.1}}}


def recreate(sh, title, rows, cols):
    if title in [w.title for w in sh.worksheets()]:
        if not FORCE:
            return None
        sh.del_worksheet(sh.worksheet(title))
        print(f'  تب «{title}» موجود بود و با --force حذف شد')
    return sh.add_worksheet(title=title, rows=rows, cols=cols)


gc = gspread.service_account(filename='service_account.json')
sh = gc.open_by_key(SHEET_ID)
print('فایل:', sh.title)

# ۱) تنظیمات
ws = recreate(sh, 'تنظیمات', 60, 5)
if ws:
    ws.update(values=ROWS, range_name=f'A1:D{len(ROWS)}')
    ws.freeze(rows=1)
    ws.format(f'B2:B{len(ROWS)}', FMT_EDIT)
    for r in SECTION_ROWS:
        ws.format(f'A{r}:D{r}', FMT_SECTION)
    for r in HEADER_ROWS:
        ws.format(f'A{r}:D{r}', FMT_HEADER)
    ws.format(f'A{ALERT_ROW}:D{ALERT_ROW}', FMT_ALERT)
    print('✓ تب «تنظیمات» ساخته شد (۱۰ اندیکاتور + ۱۲ تایم‌فریم + ۹ معاملاتی + ۴ عمومی)')
else:
    print('• تب «تنظیمات» موجود است — برای بازسازی با پیش‌فرض‌ها: --force')

# ۲) استراتژی
ws = recreate(sh, 'استراتژی', 200, 13)
if ws:
    ws.update(values=[['🎯 سیگنال‌ها برای نمادهای dynamic universe', 'آخرین به‌روزرسانی:', now_str()]],
              range_name='A1:C1')
    ws.update(values=[STRAT_HEADERS], range_name='A3:L3')
    ws.freeze(rows=3)
    ws.format('A3:L3', FMT_HEADER)
    print('✓ تب «استراتژی» ساخته شد')
else:
    print('• تب «استراتژی» موجود است')

# ۳) معاملات — دفتر سفارش‌ها؛ ستون «وضعیت» هر اجرا از API نوبیتکس تازه‌سازی می‌شود
ws = recreate(sh, 'معاملات', 1000, 14)
if ws:
    ws.update(values=[['📒 دفتر سفارش‌ها — وضعیت هر سفارش به‌صورت خودکار از API نوبیتکس به‌روزرسانی می‌شود', 'آخرین به‌روزرسانی:', now_str()]],
              range_name='A1:C1')
    ws.update(values=[TRADE_HEADERS], range_name='A3:M3')
    ws.freeze(rows=3)
    ws.format('A3:M3', FMT_HEADER)
    print('✓ تب «معاملات» ساخته شد')
else:
    print('• تب «معاملات» موجود است')

# ۴) کیف پول — داده‌ها مستقیماً از API صرافی
ws = recreate(sh, 'کیف پول', 50, 7)
if ws:
    ws.update(values=[['💼 کیف پول‌های نوبیتکس — مستقیم از API صرافی', 'آخرین به‌روزرسانی:', now_str()]],
              range_name='A1:C1')
    ws.update(values=[WALLET_HEADERS], range_name='A3:F3')
    ws.freeze(rows=3)
    ws.format('A3:F3', FMT_HEADER)
    ws.update(values=[['کلید API تنظیم نشده — پس از پر کردن .env روی سرور، موجودی‌ها اینجا نمایش داده می‌شوند', '', '', '', '', '']],
              range_name='A4:F4')
    print('✓ تب «کیف پول» ساخته شد')
else:
    print('• تب «کیف پول» موجود است')

print()
print('تب‌های نهایی:', [w.title for w in sh.worksheets()])
