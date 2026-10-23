"""G-fix-closed-cycle: اگر چرخه جاری بسته شده (آخرین ردیف نماد = فروش اجراشده)،
از آخرین چرخه بسته‌شده برای VWAP استفاده شود.

باگ: در پچ قبلی (G-fix-cycle)، در پایان پیمایش ledger، cycle_oids و last_px
reset شده بودند چون آخرین ردیف نماد فروش اجراشده بود. این یعنی _entry_fill
مقدار (None, 0.0) برمی‌گرداند که غلط است.

مثال 1M_PEPE (همه چرخه‌ها بسته شده):
  ردیف 588: خرید @ 4.9917  \
  ردیف 589: خرید @ 4.9668   } چرخه A → save as last_closed → reset
  ردیف 592: فروش @ 4.8600   /
  ردیف 593: خرید @ 4.8078   \
                              } چرخه B → save as last_closed → reset
  ردیف 595: فروش @ 4.8549   /
  پایان: cycle_oids=[], last_px=None → باید از last_closed_oids استفاده کند.
  VWAP درست: 4.8078 (فقط ردیف 593، چرخه B آخر)

رفتار صحیح برای پوزیشن باز (مثلاً ADA):
  چرخه جاری: cycle_oids=[filled_oids] → از همان استفاده می‌شود، last_closed نادیده گرفته می‌شود.
"""

from pathlib import Path

TRADER = Path('trader.py')
src = TRADER.read_text(encoding='utf-8')

OLD = '''def _entry_fill(client, led, sym):
    """N7: (vwap, fee_usdt_equiv) of executed buys in the CURRENT cycle only.
    Cycle boundary = last EXECUTED sell row in ledger (sells mark end of cycle).
    G-fix-cycle: فقط fillهای چرخه جاری برای VWAP استفاده شوند تا با fillهای
    چرخه قبلی مخلوط نشوند. باگ: 1M_PEPE چرخه B با VWAP چرخه A محاسبه می‌شد
    و P&L به جای +0.80% به صورت -1.34% ثبت شد."""
    cycle_oids = []
    last_px = None
    for _, rr in (led.get('rows') or []):
        if rr[1].strip().upper() != sym:
            continue
        rtype = rr[2].strip()
        rstat = rr[11].strip() if len(rr) > 11 else ''
        # Executed sell marks end of cycle - clear collected buys AND fallback
        if rtype == 'فروش' and rstat in EXECUTED:
            cycle_oids = []
            last_px = None
            continue
        if rtype == 'خرید' and rstat in EXECUTED:
            v = parse_price(rr[5])
            if v:
                last_px = v
            fo = clean_oid(str(rr[10]).split('|')[0])
            if fo and fo != '—':
                cycle_oids.append(fo)
    if cycle_oids and client is not None:
        fills = _fills_for_orders(client, cycle_oids)
        if fills:
            total_cost = sum(f['vwap'] * f['amount'] for f in fills.values())
            total_amount = sum(f['amount'] for f in fills.values())
            total_fee_coin = sum(f['fee'] for f in fills.values())
            if total_amount > 0:
                vwap = total_cost / total_amount
                fee_usdt = total_fee_coin * vwap
                return vwap, fee_usdt
    return last_px, 0.0'''

NEW = '''def _entry_fill(client, led, sym):
    """N7: (vwap, fee_usdt_equiv) of executed buys in the CURRENT cycle.
    Cycle boundary = EXECUTED sell row in ledger (sells mark end of cycle).
    G-fix-cycle: فقط fillهای چرخه جاری برای VWAP استفاده شوند تا با fillهای
    چرخه قبلی مخلوط نشوند. باگ: 1M_PEPE چرخه B با VWAP چرخه A محاسبه می‌شد
    و P&L به جای +0.80% به صورت -1.34% ثبت شد.
    G-fix-closed-cycle: اگر پوزیشن بسته شده (cycle_oids خالی در پایان)،
    از آخرین چرخه بسته‌شده استفاده شود. بدون این، _entry_fill برای معامله
    بسته‌شده مقدار (None, 0.0) برمی‌گرداند."""
    cycle_oids = []
    last_px = None
    last_closed_oids = None
    last_closed_px = None
    for _, rr in (led.get('rows') or []):
        if rr[1].strip().upper() != sym:
            continue
        rtype = rr[2].strip()
        rstat = rr[11].strip() if len(rr) > 11 else ''
        # Executed sell marks end of cycle - save as last_closed before reset
        if rtype == 'فروش' and rstat in EXECUTED:
            if cycle_oids:
                last_closed_oids = list(cycle_oids)
                last_closed_px = last_px
            cycle_oids = []
            last_px = None
            continue
        if rtype == 'خرید' and rstat in EXECUTED:
            v = parse_price(rr[5])
            if v:
                last_px = v
            fo = clean_oid(str(rr[10]).split('|')[0])
            if fo and fo != '—':
                cycle_oids.append(fo)
    # اگر چرخه جاری خالی است (پوزیشن بسته‌شده)، از آخرین چرخه بسته‌شده استفاده کن
    if not cycle_oids and last_closed_oids is not None:
        cycle_oids = last_closed_oids
        last_px = last_closed_px
    if cycle_oids and client is not None:
        fills = _fills_for_orders(client, cycle_oids)
        if fills:
            total_cost = sum(f['vwap'] * f['amount'] for f in fills.values())
            total_amount = sum(f['amount'] for f in fills.values())
            total_fee_coin = sum(f['fee'] for f in fills.values())
            if total_amount > 0:
                vwap = total_cost / total_amount
                fee_usdt = total_fee_coin * vwap
                return vwap, fee_usdt
    return last_px, 0.0'''

if OLD not in src:
    print('ERROR: OLD pattern not found in trader.py')
    raise SystemExit(1)

src2 = src.replace(OLD, NEW, 1)

try:
    compile(src2, 'trader.py', 'exec')
except SyntaxError as e:
    print(f'SyntaxError: {e}')
    raise SystemExit(1)

TRADER.write_text(src2, encoding='utf-8')
print('✓ _entry_fill patched: G-fix-closed-cycle (use last_closed when current is empty)')
