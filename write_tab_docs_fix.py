#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""write_tab_docs_fix.py — اصلاح نوشتن توضیحات برای تب‌های ناموفق"""
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

TAB_DOCS = {
    'کانفیگ مؤثر': """🎯 هدف: نمایش لحظه‌ای تمام گاردهای فعال و پارامترهای استراتژی
📊 ساختار: ۳ ستون (item | effective | derived)
✍️ نویسنده: تابع write_effective_config در trader.py (خط ۱۷۸۳)
👁️ خواننده: اپراتور (فقط‌خواندنی)
⏰ فرکانس: هر چرخه signals (پیش‌فرض ۳-۵ دقیقه)
📋 دستورالعمل: این تب فقط‌خواندنی است؛ تغییر دستی آن بی‌تأثیر است
🛡️ گاردهای نمایش‌داده‌شده: voting indicators, votes needed, active timeframes, SL/TP band, trailing, band guard, knife guard, momentum guard, caps, bt override, mode, G-volsize, G-bandcap, G-global, G-premium, G-mark-dev
🔍 منبع: trader.py:67 EFFECTIVE_TAB = 'کانفیگ مؤثر'""",

    'آرشیو سفارشات': """🎯 هدف: آرشیو خودکار ردیف‌های قدیمی دفتر سفارشات (G-arch)
📊 ساختار: ۱۴ ستون (مشابه سفارشات: زمان | نماد | عملیات | تایم‌فریم | دلیل | قیمت | مقدار | مبلغ | SL | TP | شناسه | وضعیت | پیام)
✍️ نویسنده: تابع archive_orders در trader.py (خط 1831)
👁️ خواننده: فقط اپراتور برای مرور تاریخی
⏰ فرکانس: هر ۲۴ ساعت (چرخه archive در scheduler.py:149)
📋 دستورالعمل: فقط‌خواندنی — آرشیو خودکار
🔢 قوانین آرشیو: ردیف‌های «اتمام» با سن > ۷ روز یا وقتی دفتر سفارشات > ۳۰۰ ردیف
🛡️ محافظت: پوزیشن‌های باز و pending هرگز آرشیو نمی‌شوند (trader.py:1848)
📊 محتوا: ۱۲۰۴ ردیف آرشیو‌شده از تاریخ ۱۴۰۵/۰۷/۰۸
🔍 منبع: trader.py:1881 ARCH_TAB = 'آرشیو سفارشات'""",
}


def col_to_letter(n):
    """تبدیل شماره ستون به حرف (1=A, 26=Z, 27=AA)"""
    s = ''
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def find_or_expand_free_cell(ws):
    """یافتن اولین ستون خالی در ردیف ۱؛ اگر از محدوده عبور کند، شبکه را گسترش می‌دهد"""
    row1 = ws.row_values(1)
    max_cols = ws.col_count

    # اولین ستون خالی (1-based)
    col = 0
    for i, val in enumerate(row1, 1):
        if not val.strip():
            col = i
            break
    if col == 0:
        col = len(row1) + 1

    # اگر از محدوده شبکه عبور کرد، ستون اضافه کن
    if col > max_cols:
        add = col - max_cols
        ws.add_cols(add)
        print(f'    + شبکه گسترش یافت: +{add} ستون (جدید: {ws.col_count})')

    return f'{col_to_letter(col)}1'


def main():
    e = load_env()
    sid = e.get('SHEET_ID') or e.get('GOOGLE_SHEET_ID')
    gc = gspread.service_account(filename='service_account.json')
    sh = gc.open_by_key(sid) if sid else gc.open('نمادهای معاملاتی')

    print('=' * 72)
    print('اصلاح توضیحات برای تب‌های ناموفق')
    print('=' * 72)

    for ws in sh.worksheets():
        title = ws.title
        if title not in TAB_DOCS:
            continue

        doc = TAB_DOCS[title]
        cell = find_or_expand_free_cell(ws)

        try:
            ws.update(values=[[doc]], range_name=f'{cell}:{cell}')
            print(f'  ✓ {title}: توضیحات در {cell} نوشته شد ({len(doc)} کاراکتر)')
        except Exception as ex:
            print(f'  ✗ {title}: خطا — {ex}')

    print()
    print('=' * 72)
    print('✓ اصلاح تکمیل شد.')
    print('=' * 72)


if __name__ == '__main__':
    main()
