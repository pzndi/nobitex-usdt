#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# exit_compare.py -- OCO exchange exit vs robot-managed SL
# Method A (OCO): stop-limit on exchange, SL*0.995 fill, TP limit
# Method B (SL-fixed): if SL-first had been used from entry (no trailing)
import gspread
import sys
from collections import defaultdict

FEE_BUY_PCT = 0.0012
FEE_SELL_PCT = 0.0012
OCO_SL_BUFFER = 0.995
SLIP_PCT = 0.0035

def load_env(path='.env'):
    env = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip()
    return env

def to_float(s):
    try:
        v = float(str(s).replace(',', '').strip())
        return v if v > 0 else 0.0
    except (ValueError, TypeError):
        return 0.0

FA_BUY = '\u062e\u0631\u06cc\u062f'
FA_SELL = '\u0641\u0631\u0648\u0637'  # typo-safe: '\u0641\u0631\u0648\u0639 isn't valid
FA_SELL = '\u0641\u0631\u0648\u0638'  # correct: \u0641\u0631\u0648\u0638 = sell
# sell is \u0641\u0631\u0648\u0638 in arabic script farsi: sell
# Farsi "sell" = \u0641\u0631\u0648\u0638 (furu: e)
# Actually "sell" = \u0641\u0631\u0648\u0638 (f-u-r-u-sh)
FA_SELL_WORD = '\u0641\u0631\u0648\u0634'
FA_BUY_WORD = '\u062e\u0631\u06cc\u062f'
FA_FILLED = '\u067e\u0631 \u0634\u062f'
FA_PARTIAL = '\u0628\u062e\u0634\u06cc \u067e\u0631 \u0648 \u0644\u063a\u0648 \u0634\u062f'
FA_FAILED = '\u0646\u0627\u0645\u0648\u0641\u0642'
FA_CANCELLED = '\u0644\u063a\u0648 \u0634\u062f'
FA_OCO = 'OCO'
FA_WALLET = '\u06a9\u06cc\u0641 \u067e\u0648\u0644'
FA_MANUAL_SELL = '\u0641\u0631\u0648\u0634 \u062f\u0633\u062a\u06cc'

def _c(s):
    return str(s).strip()

env = load_env()
gc = gspread.service_account(filename='service_account.json')
sh = gc.open_by_key(env['SHEET_ID'])

ORDERS_TAB = '\u0633\u0641\u0627\u0631\u0634\u0627\u062a'
ws = sh.worksheet(ORDERS_TAB)
rows = ws.get_all_values()

START_J = '1405/07/19'

# ═══ Build positions ═══
positions = []
open_by_sym = {}  # sym -> position dict (currently open)

for i, r in enumerate(rows, 1):
    if i <= 3 or len(r) < 13:
        continue
    t = _c(r[0])
    if not t or t < START_J:
        continue
    sym = _c(r[1]).upper()
    act = _c(r[2])
    status = _c(r[11])
    reason = _c(r[4])
    msg = _c(r[12]) if len(r) > 12 else ''
    px = to_float(r[5])
    vol = to_float(r[6])
    sl = to_float(r[8]) if len(r) > 8 else 0
    tp = to_float(r[9]) if len(r) > 9 else 0

    is_exec = status == FA_FILLED or status == FA_PARTIAL

    if act == FA_BUY_WORD and is_exec:
        if sym in open_by_sym:
            # top-up same open position
            op = open_by_sym[sym]
            op['vol'] += vol
            op['entry'] = px  # use latest entry (simplification)
            if sl > 0:
                op['sl'] = sl
            if tp > 0:
                op['tp'] = tp
        else:
            op = {'sym': sym, 'entry': px, 'vol': vol, 'sl': sl, 'tp': tp,
                  'entry_time': t, 'exits': [], 'exit': None}
            positions.append(op)
            open_by_sym[sym] = op

    elif act == FA_SELL_WORD and is_exec:
        op = open_by_sym.get(sym)
        if op is None:
            continue
        op['exits'].append({'px': px, 'vol': vol, 'reason': reason, 'time': t, 'msg': msg})
        # position is closed only if exit has P&L or is terminal (not "OCO بدون شناسه" pending)
        op['exit'] = op['exits'][-1]
        # check if this is a real terminal exit (has P&L stamp or is a wallet-exit)
        if 'P&L:' in msg or FA_WALLET in reason or 'OCO \u062f\u0633\u062a' not in reason:
            # terminal: position closed
            del open_by_sym[sym]

# Positions still in open_by_sym = currently open (excluded from comparison)
still_open = list(open_by_sym.values())

# ═══ Classify and compare ═══
comparable = []
skipped = defaultdict(int)

for p in positions:
    if not p['exit']:
        skipped['no_exit'] += 1
        continue
    if not p['sl']:
        skipped['no_sl'] += 1
        continue

    reason = p['exit']['reason']
    if FA_MANUAL_SELL in reason:
        skipped['manual'] += 1
        continue

    if FA_OCO in reason or FA_WALLET in reason:
        exit_type = 'OCO exchange'
    else:
        exit_type = 'robot-managed'

    # P&L real: from stamp, else calculate
    pnl_real = None
    msg = p['exit'].get('msg', '')
    if 'P&L:' in msg:
        try:
            pnl_real = float(msg.split('P&L:')[1].split()[0])
        except (ValueError, IndexError):
            pass
    if pnl_real is None:
        exit_vol = p['exit']['vol'] if p['exit']['vol'] > 0 else p['vol']
        pnl_real = exit_vol * (p['exit']['px'] - p['entry'])

    # P&L if SL-first (conservative, with fee+slip)
    exit_vol = p['exit']['vol'] if p['exit']['vol'] > 0 else p['vol']
    pnl_if_sl = exit_vol * (p['sl'] * OCO_SL_BUFFER - p['entry'])
    pnl_if_sl -= exit_vol * p['sl'] * (FEE_SELL_PCT + SLIP_PCT)

    comparable.append({
        'sym': p['sym'], 'type': exit_type,
        'entry': p['entry'], 'exit': p['exit']['px'],
        'sl': p['sl'], 'tp': p['tp'], 'vol': exit_vol,
        'pnl_real': pnl_real, 'pnl_if_sl': pnl_if_sl,
        'exit_reason': reason[:30],
    })

print('=' * 90)
print('  exit_compare.py -- OCO exchange vs robot-managed SL (fixed)')
print('  range: %s to now' % START_J)
print('=' * 90)
print()
print('  total positions: %d' % len(positions))
print('  currently open: %d (excluded)' % len(still_open))
print('  comparable: %d' % len(comparable))
print('  skipped: %s' % dict(skipped))
print()

if not comparable:
    print('No comparable positions.')
    sys.exit(0)

print('── per-position ──')
print('sym    | type          | entry       | exit(real)  | SL init    | >SL? | P&L real | if_SL | delta')
print('-' * 110)

sum_real = 0
sum_if = 0
by_type = defaultdict(lambda: {'n': 0, 'real': 0, 'if': 0, 'wins': 0})

for c in comparable:
    above = 'Y' if c['exit'] > c['sl'] else ('N=SL' if c['exit'] < c['sl'] else '=')
    delta = c['pnl_real'] - c['pnl_if_sl']
    print('%-6s | %-13s | %11.6g | %11.6g | %10.6g | %-4s | %+8.3f | %+8.3f | %+8.3f' % (
        c['sym'], c['type'][:13], c['entry'], c['exit'], c['sl'], above,
        c['pnl_real'], c['pnl_if_sl'], delta))
    sum_real += c['pnl_real']
    sum_if += c['pnl_if_sl']
    by_type[c['type']]['n'] += 1
    by_type[c['type']]['real'] += c['pnl_real']
    by_type[c['type']]['if'] += c['pnl_if_sl']
    if c['pnl_real'] > 0:
        by_type[c['type']]['wins'] += 1

print('-' * 110)
print('TOTAL real: %+.3f | TOTAL if_SL: %+.3f | delta: %+.3f' % (sum_real, sum_if, sum_real - sum_if))
print()

for typ in ('OCO exchange', 'robot-managed'):
    s = by_type.get(typ)
    if not s or not s['n']:
        continue
    wr = s['wins'] * 100 // s['n']
    print('  %-15s | n=%2d | WR=%3d%% | real=%+8.3f | if_SL=%+8.3f | delta=%+8.3f' % (
        typ, s['n'], wr, s['real'], s['if'], s['real'] - s['if']))
    better = sum(1 for c in comparable if c['type'] == typ and c['exit'] > c['sl'])
    worse = sum(1 for c in comparable if c['type'] == typ and c['exit'] < c['sl'])
    print('    exit better than SL: %d | worse(=SL): %d' % (better, worse))
print()

print('── per-symbol ──')
by_sym_agg = defaultdict(lambda: {'n': 0, 'real': 0, 'if': 0})
for c in comparable:
    by_sym_agg[c['sym']]['n'] += 1
    by_sym_agg[c['sym']]['real'] += c['pnl_real']
    by_sym_agg[c['sym']]['if'] += c['pnl_if_sl']
for sym in sorted(by_sym_agg, key=lambda s: -by_sym_agg[s]['real']):
    s = by_sym_agg[sym]
    print('  %-6s | n=%2d | real=%+8.3f | if_SL=%+8.3f | delta=%+8.3f' % (
        sym, s['n'], s['real'], s['if'], s['real'] - s['if']))
print()

print('── assumptions ──')
print('  1. SL fill = SL x 0.995 (StopLimit buffer)')
print('  2. Sell fee = 0.12%, slippage = 0.35% (measured from real fills)')
print('  3. SL-first when SL+TP in same candle (conservative)')
print('  4. P&L_real from N7 stamp or vol*(exit-entry)')
print('  5. Buy price = order price (not fill) -- G-entry limit at -1% from signal')
print('  6. Top-up buys merge into existing position (latest SL/TP wins)')
print('  7. Currently open positions excluded')
print('  8. Manual sells excluded')
print()

d = sum_real - sum_if
if d > 0:
    print('  CONCLUSION: current system better by %+.3f USDT' % d)
elif d < 0:
    print('  CONCLUSION: fixed SL would be better by %+.3f USDT' % -d)
else:
    print('  CONCLUSION: identical')
print()
print('end')
