"""تست _entry_fill با داده واقعی ledger برای 1M_PEPE.

هدف: اثبات اینکه پچ فعلی (G-fix-cycle) برای چرخه‌ای که بسته شده
(آخرین ردیف نماد = فروش اجراشده)، مقدار (None, 0.0) برمی‌گرداند که غلط است.

امیدوارانه درست: VWAP باید 4.8078 باشد (فقط ردیف 593، چرخه B)."""

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
ws = sh.worksheet('سفارشات')

# ساخت led واقعی
led = trader.read_ledger(ws)
print(f'ردیف‌های ledger: {len(led["rows"])}')
print(f'پوزیشن‌های باز: {list(led["positions"].keys())}')

# ساخت client واقعی
key = e.get('NOBITEX_KEY') or e.get('NBX_KEY')
sec = e.get('NOBITEX_SECRET') or e.get('NBX_SECRET')
print(f'key={bool(key)}, sec={bool(sec)}')
client = trader.NobitexClient(key, sec) if key and sec else None

# فراخوانی _entry_fill برای 1M_PEPE
vwap, fee = trader._entry_fill(client, led, '1M_PEPE')
print(f'\n--- 1M_PEPE _entry_fill نتیجه ---')
print(f'VWAP: {vwap}')
print(f'fee_usdt: {fee}')

# محاسبه P&L با exit واقعی 4.8549
exit_px = 4.8549
if vwap:
    pct = (exit_px / vwap - 1) * 100
    print(f'exit: {exit_px}, P&L%: {pct:+.2f}% (هدف: ~+0.80% پس از کارمزد)')
else:
    print('exit: 4.8549, P&L%: N/A (VWAP=None)')

# چاپ ردیف‌های 1M_PEPE برای تحلیل
print(f'\n--- ردیف‌های 1M_PEPE در ledger ---')
for idx, r in led['rows']:
    if r[1].strip().upper() == '1M_PEPE':
        status = r[11].strip() if len(r) > 11 else ''
        if status in trader.EXECUTED:
            print(f'  ردیف {idx}: {r[2]:6} status={status:14} price={r[5]:14} oid={str(r[10])[:30]}')
