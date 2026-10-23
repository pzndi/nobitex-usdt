"""اصلاح ردیف ۹ تحلیل معاملات برای 1M_PEPE چرخه B.

باگ: _entry_fill قبلی VWAP همه چرخه‌ها را مخلوط می‌کرد → VWAP=4.9209 → P&L=-1.34%
اصلاح: با patched _entry_fill (G-fix-cycle + G-fix-closed-cycle):
  - VWAP = 4.8078 (فقط چرخه B، ردیف 593)
  - Exit VWAP = 4.8549 (از _exit_fill روی sell oids)
  - P&L USDT و P&L % دوباره محاسبه می‌شوند
  - Result از «باخت» به «برد» تغییر می‌کند"""

import sys
sys.path.insert(0, '.')
import logging
logging.basicConfig(level=logging.WARNING)

from settings import load_env
import gspread
import trader

e = load_env()
gc = gspread.service_account(filename='service_account.json')
sh = gc.open_by_key(e['SHEET_ID'])
ws_ord = sh.worksheet('سفارشات')
ws_an = sh.worksheet('تحلیل معاملات')

# ۱. خواندن led
led = trader.read_ledger(ws_ord)
key = e['NOBITEX_API_KEY']
sec = e['NOBITEX_API_SECRET']
client = trader.NobitexClient(key, sec)

# ۲. محاسبه VWAP ورود (patched)
entry_vwap, buy_fee = trader._entry_fill(client, led, '1M_PEPE')
print(f'VWAP ورود: {entry_vwap}')
print(f'کارمزد خرید (USDT equiv): {buy_fee}')

# ۳. یافتن oids فروش چرخه B (آخرین sell اجراشده 1M_PEPE)
sell_oids = []
for _, rr in reversed(led.get('rows') or []):
    if (str(rr[1]).strip().upper() == '1M_PEPE'
            and str(rr[2]).strip() == 'فروش'
            and str(rr[11]).strip() in trader.EXECUTED):
        for x in str(rr[10]).split('|'):
            c = trader.clean_oid(x)
            if c and c.isdigit():
                sell_oids.append(c)
        sell_vol = float(str(rr[6]).replace(',', '') or 0)
        sell_amt = float(str(rr[7]).replace(',', '') or 0)
        break
print(f'Sell oids چرخه B: {sell_oids}')
print(f'حجم فروش: {sell_vol}, مبلغ فروش: {sell_amt}')

# ۴. محاسبه VWAP خروج و کارمزد فروش
exit_fill = trader._exit_fill(client, sell_oids) if sell_oids else None
exit_vwap = exit_fill[0] if exit_fill else None
exit_amt = exit_fill[1] if exit_fill else None
sell_fee = exit_fill[2] if exit_fill else 0.0
print(f'VWAP خروج: {exit_vwap}')
print(f'حجم فروش (از fills): {exit_amt}')
print(f'کارمزد فروش (USDT): {sell_fee}')

# ۵. محاسبه P&L
vol = exit_amt or sell_vol
pnl_usdt = vol * (exit_vwap - entry_vwap) - buy_fee - sell_fee
pct_gross = (exit_vwap / entry_vwap - 1) * 100
pct_net = pct_gross - 0.18  # 0.18% = کارمزد تقریبی واقعی
print(f'\n--- P&L محاسبه‌شده ---')
print(f'حجم: {vol}')
print(f'P&L USDT: {pnl_usdt:+.4f}')
print(f'P&L % gross: {pct_gross:+.4f}%')
print(f'P&L % net: {pct_net:+.4f}%')

# ۶. نتیجه
result = 'برد' if pnl_usdt > 0.01 else ('باخت' if pnl_usdt < -0.01 else 'سربه‌سر')
print(f'نتیجه: {result}')

# ۷. یافتن ردیف ۱M_PEPE چرخه B در تب تحلیل (آخرین ردیف 1M_PEPE)
an_rows = ws_an.get_all_values()
target_row = None
for i in range(3, len(an_rows)):
    if an_rows[i] and an_rows[i][1].strip().upper() == '1M_PEPE':
        target_row = i + 1  # 1-indexed
print(f'\nردیف هدف در تحلیل: {target_row}')
if target_row:
    print(f'مقادیر فعلی: {an_rows[target_row-1]}')

# ۸. به‌روزرسانی ستون‌های 3 (نتیجه), 5 (P&L USDT), 6 (P&L %), 9 (قیمت ورود)
if target_row:
    updates = [
        ('C' + str(target_row), result),  # ستون 3: نتیجه
        ('F' + str(target_row), round(pnl_usdt, 2)),  # ستون 5: P&L USDT (1-based col 5 → E؟ صبر کن)
    ]
    # ستون‌ها در شیت: A=1, B=2, C=3, D=4, E=5, F=6, ...
    # در شیت تحلیل: ستون 0=زمان خروج(A), 1=نماد(B), 2=نتیجه(C), 3=نوع خروج(D),
    # 4=P&L USDT(E), 5=P&L %(F), 6=مدت(G), 7=قیمت ورود(H), 8=قیمت خروج(I), ...
    ws_an.update('C' + str(target_row), [[result]])
    ws_an.update('E' + str(target_row), [[round(pnl_usdt, 2)]])
    ws_an.update('F' + str(target_row), [[round(pct_net, 2)]])
    ws_an.update('H' + str(target_row), [[trader.fmt_price(entry_vwap)]])
    ws_an.update('I' + str(target_row), [[trader.fmt_price(exit_vwap)]])
    print(f'\n✓ ردیف {target_row} به‌روزرسانی شد:')
    print(f'  C (نتیجه): {result}')
    print(f'  E (P&L USDT): {round(pnl_usdt, 2)}')
    print(f'  F (P&L %): {round(pct_net, 2)}')
    print(f'  H (قیمت ورود): {trader.fmt_price(entry_vwap)}')
    print(f'  I (قیمت خروج): {trader.fmt_price(exit_vwap)}')
