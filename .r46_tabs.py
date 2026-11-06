import sys, re
from collections import Counter
sys.path.insert(0, '.')
import net_timeout  # noqa: F401 — گارد ۳۰ث
import gspread
from settings import load_env

src = open('trader.py', encoding='utf-8').read()
orders_tab = re.search(r"^ORDERS_TAB\s*=\s*'([^']+)'", src, re.M).group(1)
print('ORDERS_TAB =', repr(orders_tab))

env = load_env()
sh = gspread.service_account(filename='service_account.json').open_by_key(env.get('SHEET_ID'))
for t in ('معاملات', 'اتمام معاملات', 'آرشیو سفارشات', orders_tab):
    try:
        print('تب «%s»: %d ردیف' % (t, len(sh.worksheet(t).get_all_values())))
    except Exception as e:
        print('تب «%s»: خطا %s' % (t, e))

ws = sh.worksheet(orders_tab)
rows = ws.get_all_values()
dated = Counter()
other = 0
for r in rows:
    t0 = str(r[0]).strip() if r else ''
    if re.match(r'^14\d\d/\d\d/\d\d', t0):
        dated[t0[:10]] += 1
    else:
        other += 1
print('\n— ردیف‌های بدون تاریخ معتبر (سربرگ/doc/شبح؟): %d' % other)
print('— گروه‌بندی تاریخ (۶ روز آخر):')
for d in sorted(dated)[-6:]:
    print('  %s : %d' % (d, dated[d]))

print('\n— ۱۲ ردیف آخر دفتر (زمان|نماد|قیمت|عملیات|وضعیت|پیام):')
for r in rows[-12:]:
    def g(i, n=22):
        return str(r[i])[:n] if len(r) > i else ''
    print('  %s | %s | %s | %s | st=%s | %s' % (g(0,17), g(1,8), g(2,10), g(3,10), g(11,14), g(12,20)))
