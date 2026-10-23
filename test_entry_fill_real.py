"""تست _entry_fill با کلید واقعی نوبیتکس برای 1M_PEPE."""

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

led = trader.read_ledger(ws)
print(f'ردیف‌های ledger: {len(led["rows"])}')
print(f'پوزیشن‌های باز: {list(led["positions"].keys())}')

key = e['NOBITEX_API_KEY']
sec = e['NOBITEX_API_SECRET']
print(f'key={bool(key)}, sec={bool(sec)}')
client = trader.NobitexClient(key, sec)

vwap, fee = trader._entry_fill(client, led, '1M_PEPE')
print(f'\n--- 1M_PEPE _entry_fill نتیجه ---')
print(f'VWAP: {vwap}')
print(f'fee_usdt: {fee}')

exit_px = 4.8549
if vwap:
    pct_gross = (exit_px / vwap - 1) * 100
    # کارمزد واقعی 0.18% (0.09% هر طرف)
    pct_net = pct_gross - 0.18
    print(f'exit: {exit_px}')
    print(f'P&L% gross: {pct_gross:+.4f}%')
    print(f'P&L% net (after 0.18% fee): {pct_net:+.4f}% (هدف: +0.80%)')
