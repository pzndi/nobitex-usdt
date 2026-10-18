#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""به‌روزرسانی توضیحات تب «آرشیو» با هدف واقعی آن"""
import gspread, os

def load_env(path='.env'):
    env = {}
    if not os.path.exists(path):
        return env
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env

NEW_DOC = """🎯 هدف: آرشیو تاریخی معاملات بسته‌شده قدیمی (قبل از بازسازی دفتر)
📊 ساختار: ۱۱ ستون (زمان بسته‌شدن | نماد | زمان ورود | قیمت ورود | قیمت خروج | مقدار | سود/زیان | بازدهی٪ | دلیل خروج | مدت | نوع)
✍️ نویسنده: (تاریخی — دیگر نوشته نمی‌شود)؛ در گذشته از مهاجرت «اتمام معاملات» ساخته شد
👁️ خواننده: فقط اپراتور برای مرور تاریخی + ابزارهای analyze_*.py برای walk-forward
⏰ فرکانس: بدون به‌روزرسانی (فقط‌خواندنی تاریخی)
📋 دستورالعمل: فقط‌خواندنی — نگه‌داری داده‌های تاریخی قدیمی
📊 محتوا: ۱۸۸ ردیف از معاملات بسته‌شده قدیمی (از ۱۴۰۵/۰۷/۰۶)
⚠️ تفاوت با «آرشیو سفارشات»: این تب معاملات بسته‌شده را نگه می‌دارد (با P&L و دلیل خروج)؛ «آرشیو سفارشات» سفارشات را (با شناسه و وضعیت)
🔍 منبع: تاریخی (setup_new_tabs.py قدیمی)"""


def main():
    e = load_env()
    sid = e.get('SHEET_ID') or e.get('GOOGLE_SHEET_ID')
    gc = gspread.service_account(filename='service_account.json')
    sh = gc.open_by_key(sid) if sid else gc.open('نمادهای معاملاتی')

    ws = sh.worksheet('آرشیو')
    # توضیحات در ستون C (۳) نوشته شده بود
    ws.update(values=[[NEW_DOC]], range_name='C1:C1')
    print('✓ توضیحات تب «آرشیو» به‌روزرسانی شد')
    print('  تعداد کاراکتر:', len(NEW_DOC))

if __name__ == '__main__':
    main()
