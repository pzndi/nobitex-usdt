#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_leg1_market.py - G-mhalf: پایهٔ اول مارکت (Scale 1/2) + پایهٔ دوم limit -0.5% (Scale 2/2)
کلید شیت: LEG1_MARKET = بله/خیر (پیش‌فرض خیر — بدون تغییر رفتار)
استفاده:
  python3 apply_leg1_market.py            # BUILD — فقط بررسی انکرها، بدون تغییر
  python3 apply_leg1_market.py --deploy   # DEPLOY — بکاپ + اعمال + py_compile
"""
import os, sys, shutil, py_compile, time

DEPLOY = '--deploy' in sys.argv

TRADER = 'trader.py'
SETTINGS = 'settings.py'

# ─── پچ ۱ (trader.py): فلگ G-mhalf + شاخهٔ قیمت ───
T1_OLD = """    _is_market = (st.order_type == 'market' and st.entry_mode != 'limit_pullback')
    if _is_market:
        _price1, _price2 = price, None
        _size1 = round(_size, 2)
        _size2 = 0
    else:
"""
T1_NEW = """    _is_market = (st.order_type == 'market' and st.entry_mode != 'limit_pullback')
    # G-mhalf: پایهٔ اول مارکت (نصف حجم) + پایهٔ دوم limit نیم‌درصد پایین‌تر — کلید LEG1_MARKET
    _leg1_market = (not _is_market) and bool(getattr(st, 'leg1_market', False))
    if _is_market:
        _price1, _price2 = price, None
        _size1 = round(_size, 2)
        _size2 = 0
    elif _leg1_market:
        _price1, _price2 = price, price * 0.995
        _size1 = round(_size * 0.5, 2)
        _size2 = round(_size - _size1, 2)
    else:
"""

# ─── پچ ۲ (trader.py): برچسب ورود سه‌حالته ───
T2_OLD = "    _entry_tag = 'ورود مارکت' if _is_market else 'Scale 1/2 (Fib 0.618)'\n"
T2_NEW = ("    _entry_tag = ('ورود مارکت' if _is_market else "
          "'Scale 1/2 (مارکت)' if _leg1_market else 'Scale 1/2 (Fib 0.618)')\n")

# ─── پچ ۳ (trader.py): لاگ شفافیت + is_market پایهٔ ۱ ───
T3_OLD = """    # G-scale: Use pre-calculated scaled entry price (market mode: قیمت لحظه‌ای)
    _limit_price = _price1
    code, data = client.place_order('buy', sym, _limit_price, vol, _is_market, client_order_id=coid)
"""
T3_NEW = """    # G-scale: Use pre-calculated scaled entry price (market mode: قیمت لحظه‌ای)
    _limit_price = _price1
    # G-mhalf: شفافیت — نوع هر پایه در لاگ
    log.info('ورود %s | پایهٔ ۱: %s | پایهٔ ۲: %s', sym,
             'مارکت' if (_is_market or _leg1_market) else 'limit',
             'limit -0.5%' if _price2 else '—')
    code, data = client.place_order('buy', sym, _limit_price, vol, _is_market or _leg1_market, client_order_id=coid)
"""

# ─── پچ ۴ (trader.py): برچسب قدیمی Scale 2/2 — دقیقاً ۲ رخداد ───
T4_OLD = "Scale 2/2 (BB/2xATR)"
T4_NEW = "Scale 2/2 (-0.5%)"

# ─── پچ ۵ (trader.py): اصلاح docstring کهنه 0.999→0.995 ───
T5_OLD = "    - Scale 2/2 = Scale 1/2 * 0.999 (همیشه 0.1% پایین‌تر از Scale 1/2)\n"
T5_NEW = "    - Scale 2/2 = Scale 1/2 * 0.995 (همیشه 0.5% پایین‌تر از Scale 1/2)\n"

# ─── پچ ۶ (settings.py): پراپرتی leg1_market ───
S1_OLD = """    @property
    def entry_mode(self):
        \"\"\"G-entry: 'market' or 'limit_pullback'.\"\"\"
        return str(self.trading.get('ENTRY_MODE', 'limit_pullback')).strip().lower()
"""
S1_NEW = S1_OLD + """
    @property
    def leg1_market(self):
        \"\"\"G-mhalf: پایهٔ اول Scale به‌صورت مارکت (بله/خیر) — پایهٔ دوم limit نیم‌درصد پایین‌تر\"\"\"
        return truthy(self.trading.get('LEG1_MARKET', 'خیر'))
"""

CHECKS = [
    (TRADER,  'T1', T1_OLD, T1_NEW, 1),
    (TRADER,  'T2', T2_OLD, T2_NEW, 1),
    (TRADER,  'T3', T3_OLD, T3_NEW, 1),
    (TRADER,  'T4', T4_OLD, T4_NEW, 2),
    (TRADER,  'T5', T5_OLD, T5_NEW, 1),
    (SETTINGS, 'S1', S1_OLD, S1_NEW, 1),
]


def load(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def save(path, text):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def main():
    print('=== G-mhalf BUILD ===')
    ok = True
    for path, name, old, new, cnt in CHECKS:
        try:
            src = load(path)
        except FileNotFoundError:
            print(f'✗ {name}: فایل {path} پیدا نشد')
            ok = False
            continue
        c = src.count(old)
        good = (c == cnt)
        ok = ok and good
        print(f"{'✓' if good else '✗'} {name}: {path} | count={c} (انتظار {cnt})")
    if not ok:
        print('\n✗ BUILD ناموفق — هیچ فایلی تغییر نکرد. خروجی را برای دستیار بفرستید.')
        sys.exit(1)
    print('\n✓ BUILD موفق — همهٔ انکرها دقیقاً مطابق انتظار یافت شد')
    if not DEPLOY:
        print('(حالت BUILD — برای اعمال: python3 apply_leg1_market.py --deploy)')
        return

    print('\n=== G-mhalf DEPLOY ===')
    ts = time.strftime('%Y%m%d-%H%M%S')
    files = sorted({p for p, _, _, _, _ in CHECKS})
    for path in files:
        bak = f'{path}.bak-{ts}'
        shutil.copy2(path, bak)
        print(f'✓ بکاپ: {bak}')
    for path, name, old, new, cnt in CHECKS:
        save(path, load(path).replace(old, new))
        print(f'✓ اعمال {name} → {path}')
    for path in files:
        py_compile.compile(path, doraise=True)
        print(f'✓ py_compile OK: {path}')
    print(f'\n✓ DEPLOY کامل (بکاپ: *.bak-{ts})')
    print('مرحله بعد: SELFTEST → ردیف شیت LEG1_MARKET → git commit+push')


main()
