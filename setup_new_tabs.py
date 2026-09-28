#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""setup_new_tabs.py — ساخت «بک‌تست»، «سفارشات»، «اتمام معاملات»
+ مهاجرت دفتر قدیمی «معاملات» به «سفارشات» (بدون از دست رفتن داده)
+ بازسازی «معاملات» به جدول رتبه‌بندی ۵ دقیقه‌ای"""
import gspread
from settings import load_env

try:
    import jdatetime

    def now_str():
        return jdatetime.datetime.now().strftime('%Y/%m/%d %H:%M')
except ImportError:
    from datetime import datetime

    def now_str():
        return datetime.now().strftime('%Y-%m-%d %H:%M')

FMT_HEADER = {'backgroundColor': {'red': 0.25, 'green': 0.44, 'blue': 0.72},
              'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}}}

ORDER_HEADERS  = ['زمان', 'نماد', 'عملیات', 'تایم‌فریم', 'دلیل', 'قیمت', 'مقدار', 'مبلغ USDT',
                  'حد ضرر', 'حد سود', 'شناسه سفارش', 'وضعیت', 'پیام']
CLOSED_HEADERS = ['زمان بسته‌شدن', 'نماد', 'زمان ورود', 'قیمت ورود', 'قیمت خروج', 'مقدار',
                  'سود/زیان (USDT)', 'بازدهی ٪', 'دلیل خروج', 'مدت (ساعت)', 'نوع']
BT_HEADERS     = ['نماد', 'تایم‌فریم', 'تعداد معامله', 'بردها', 'نرخ برد ٪', 'بازده کل ٪',
                  'آستانه بهینه', 'SL×ATR', 'TP×ATR', 'وضعیت', 'به‌روزرسانی']
RANK_HEADERS   = ['رتبه', 'نماد', 'سیگنال', 'قدرت٪', 'موافق', 'مخالف', 'خنثی', 'قیمت',
                  'عدد ورود', 'TP', 'SL', 'R:R', 'استراتژی بک‌تست', 'وضعیت']

gc = gspread.service_account(filename='service_account.json')
sh = gc.open_by_key(load_env()['SHEET_ID'])
titles = [w.title for w in sh.worksheets()]
print('تب‌های فعلی:', titles)


def ensure(title, headers, title_text, ncols):
    if title in titles:
        print(f'• «{title}» موجود است')
        return sh.worksheet(title)
    ws = sh.add_worksheet(title=title, rows=1000, cols=ncols)
    ws.update(values=[[title_text, 'به‌روزرسانی:', now_str()]], range_name='A1:C1')
    col = chr(64 + len(headers))
    ws.update(values=[headers], range_name=f'A3:{col}3')
    ws.freeze(rows=3)
    ws.format(f'A3:{col}3', FMT_HEADER)
    print(f'✓ تب «{title}» ساخته شد')
    return ws


# ۱) سفارشات + مهاجرت
ws_o = ensure('سفارشات', ORDER_HEADERS, '📒 دفتر سفارش‌ها — ثبت، وضعیت خودکار و SL/TP داینامیک', 14)
old = [r for r in sh.worksheet('معاملات').get_all_values()[3:]
       if any(str(c).strip() for c in r)]
existing = {(r[0], r[1], r[2]) for r in ws_o.get_all_values()[3:]
            if any(str(c).strip() for c in r)}
migrated = 0
for r in old:
    r = list(r) + [''] * (13 - len(r))
    if (r[0], r[1], r[2]) in existing:
        continue
    ws_o.append_row(r[:13])
    migrated += 1
print(f'✓ {migrated} ردیف از دفتر قدیمی «معاملات» به «سفارشات» منتقل شد')

# ۲) اتمام معاملات  ۳) بک تست
ensure('اتمام معاملات', CLOSED_HEADERS, '🏁 معاملات بسته‌شده — خروج، سود/زیان و دلیل', 12)
ensure('بک تست', BT_HEADERS, '🧪 بک‌تست — بهترین استراتژی هر نماد از تاریخچه نوبیتکس', 12)

# ۴) بازسازی «معاملات» → رتبه‌بندی
ws_r = sh.worksheet('معاملات')
ws_r.clear()
ws_r.update(values=[['⚡ رتبه‌بندی لحظه‌ای نمادها برای سفارشگزاری — بازه: INTERVAL_SIGNALS_MIN در تب تنظیمات',
                     'به‌روزرسانی:', now_str()]], range_name='A1:C1')
ws_r.update(values=[RANK_HEADERS], range_name='A3:N3')
ws_r.freeze(rows=3)
ws_r.format('A3:N3', FMT_HEADER)
print('✓ تب «معاملات» به جدول رتبه‌بندی بازسازی شد')

print('تب‌های نهایی:', [w.title for w in sh.worksheets()])
