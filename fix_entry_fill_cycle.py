"""G-fix-cycle: _entry_fill فقط fillهای چرخه جاری را برای VWAP محاسبه کند.

باگ: وقتی چندین چرخه معامله برای یک نماد در ledger وجود دارد (مثلاً 1M_PEPE
چرخه A در 1405/08/01 17 بسته شد، چرخه B در 18 شروع شد)، _entry_fill همه
fillهای اجراشده نماد را در VWAP مخلوط می‌کرد. این باعث می‌شد entry_price چرخه
B با fillهای چرخه A مخلوط شود و P&L اشتباه محاسبه شود.

مثال 1M_PEPE:
- چرخه A: Scale 1/2 @ 4.9917 + Scale 2/2 @ 4.9668 → VWAP_A ≈ 4.979 (بسته در SL=4.86)
- چرخه B: Scale 1/2 @ 4.8078 (تنها این پر شد) → VWAP_B = 4.8078 (بسته در TP=4.8549)
- VWAP اشتباه: 4.9209 → P&L = -1.34% (ثبت‌شده در ردیف ۹ تحلیل)
- VWAP درست: 4.8078 → P&L = +0.98% (پس از کارمزد ~+0.80% = سقف هدف)

راه‌حل: در پیمایش ledger، هر بار که به ردیف «فروش» با status اجراشده می‌رسیم،
لیست buy oids جمع‌آوری‌شده را پاک می‌کنیم و last_px را هم reset می‌کنیم.
فقط buyهای بعد از آخرین sell به عنوان چرخه جاری در نظر گرفته می‌شوند."""

import re
from pathlib import Path

TRADER = Path('trader.py')
src = TRADER.read_text(encoding='utf-8')

OLD = '''def _entry_fill(client, led, sym):
    """N7: (vwap, fee_usdt_equiv) of ALL executed buys of sym from real
    fills; fallback to ledger row price with zero fee. Buy fee is charged in
    the coin itself -> converted at fill price.
    G-fix: محاسبه VWAP وزنی همه خریدها (Scale 1/2 + Scale 2/2)، نه فقط آخرین."""
    all_oids = []
    last_px = None
    for _, rr in (led.get('rows') or []):
        if (rr[1].strip().upper() == sym and rr[2].strip() == 'خرید'
                and rr[11].strip() in EXECUTED):
            v = parse_price(rr[5])
            if v:
                last_px = v
            fo = clean_oid(str(rr[10]).split('|')[0])
            if fo and fo != '—':
                all_oids.append(fo)
    if all_oids and client is not None:
        fills = _fills_for_orders(client, all_oids)
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

if OLD not in src:
    print('ERROR: OLD pattern not found in trader.py')
    raise SystemExit(1)

src2 = src.replace(OLD, NEW, 1)

# Syntax check
try:
    compile(src2, 'trader.py', 'exec')
except SyntaxError as e:
    print(f'SyntaxError: {e}')
    raise SystemExit(1)

TRADER.write_text(src2, encoding='utf-8')
print('✓ _entry_fill patched: cycle-based filtering (G-fix-cycle)')
print('  - iterate ledger, track current-cycle buy oids')
print('  - on each executed sell row of sym: reset cycle_oids + last_px')
print('  - only current-cycle buys contribute to VWAP')
