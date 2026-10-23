"""بررسی VWAP هر دو چرخه 1M_PEPE."""
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

led_full = trader.read_ledger(ws)
key = e['NOBITEX_API_KEY']
sec = e['NOBITEX_API_SECRET']
client = trader.NobitexClient(key, sec)

# چرخه A: فقط ردیف‌های قبل از 593 (قبل از buy چرخه B)
led_a = dict(led_full)
led_a['rows'] = [(idx, r) for idx, r in led_full['rows'] if idx < 593]

vwap_a, fee_a = trader._entry_fill(client, led_a, '1M_PEPE')
print(f'چرخه A (ردیف‌های 588,589 خرید + 592 فروش):')
print(f'  VWAP: {vwap_a}, fee: {fee_a}')
exit_a = 4.8600
if vwap_a:
    pct_gross_a = (exit_a / vwap_a - 1) * 100
    pct_net_a = pct_gross_a - 0.18
    print(f'  exit: {exit_a}, P&L% gross: {pct_gross_a:+.4f}%, net: {pct_net_a:+.4f}%')
    print(f'  ثبت‌شده در ردیف ۸ تحلیل: -2.49%')

print()

# چرخه B: full ledger (چرخه آخر)
vwap_b, fee_b = trader._entry_fill(client, led_full, '1M_PEPE')
print(f'چرخه B (ردیف 593 خرید + 595 فروش):')
print(f'  VWAP: {vwap_b}, fee: {fee_b}')
exit_b = 4.8549
if vwap_b:
    pct_gross_b = (exit_b / vwap_b - 1) * 100
    pct_net_b = pct_gross_b - 0.18
    print(f'  exit: {exit_b}, P&L% gross: {pct_gross_b:+.4f}%, net: {pct_net_b:+.4f}%')
    print(f'  ثبت‌شده در ردیف ۹ تحلیل: -1.34%')
