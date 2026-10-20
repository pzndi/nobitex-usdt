#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_oco_health.py - Fix symbol matching + error logging in oco_health_check"""
import os, sys, shutil, py_compile, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """def oco_health_check(sh, st, state=None):
    \"\"\"G-oco-health: Verify OCO legs on exchange every 10 min. Rebuild if broken/missing.\"\"\"
    client = make_client()
    if client is None:
        return
    ws_t = sh.worksheet(ORDERS_TAB)
    led = read_ledger(ws_t)
    
    try:
        code, od = client.open_orders()
        if code != 200:
            log.error('G-oco-health: open_orders failed HTTP %s', code)
            return
        ex_orders = od.get('orders', []) or []
    except Exception:
        log.exception('G-oco-health: open_orders exception')
        return

    for sym, p in led['positions'].items():
        rv = p.get('real_volume') or 0
        if rv <= 1e-12:
            continue
        
        sym_lower = sym.lower()
        sym_sell_orders = [
            o for o in ex_orders 
            if str(o.get('srcCurrency', '')).lower() == sym_lower 
            and str(o.get('type')) == 'sell'
        ]
        
        if len(sym_sell_orders) >= 2:
            continue
        
        log.warning('G-oco-health: %s has %d sell orders (expected 2). Rebuilding...', sym, len(sym_sell_orders))
        
        for o in sym_sell_orders:
            oid = clean_oid(o.get('id') or o.get('pairId'))
            if oid:
                client.cancel_order(oid)
        
        sl_o, tp_o = None, None
        for _, rr in reversed(led['rows']):
            if rr[1].strip().upper() == sym and rr[2].strip() == 'خرید' and rr[11].strip() in EXECUTED:
                sl_o = parse_price(rr[8])
                tp_o = parse_price(rr[9])
                break
        
        if not (sl_o and tp_o and sl_o > 0 and tp_o > 0):
            log.error('G-oco-health: %s cannot rebuild OCO. SL/TP not found.', sym)
            continue
            
        vol_o = currency_available(client, sym)
        if vol_o is None or vol_o <= 1e-12:
            vol_o = rv
            log.warning('G-oco-health: %s active=0, using ledger vol %s', sym, rv)
        
        code2, data2 = client.place_oco_sell(sym, vol_o, tp_o, sl_o)
        ok2 = code2 == 200 and isinstance(data2, dict) and data2.get('status') == 'ok'
        
        if ok2:
            o2 = (data2.get('order') or {}) if isinstance(data2, dict) else {}
            leg_ids = []
            if isinstance(o2, dict):
                for _k in ('id', 'pairId', 'orderId'):
                    if o2.get(_k): leg_ids.append(clean_oid(o2.get(_k)))
            if isinstance(data2, dict) and isinstance(data2.get('orders'), list):
                for _lg in data2['orders']:
                    if isinstance(_lg, dict):
                        for _k in ('id', 'pairId', 'orderId'):
                            if _lg.get(_k): leg_ids.append(clean_oid(_lg.get(_k)))
            oid_oco = '|'.join(dict.fromkeys(leg_ids))
            
            record_trade(ws_t, 'فروش', sym, '', 'OCO تور ایمنی (G-oco-health)',
                         fmt_price(tp_o), vol_o, round(vol_o * tp_o, 2),
                         fmt_price(sl_o), fmt_price(tp_o), oid_oco, ST_PLACED,
                         'OCO rebuilt: TP=' + fmt_price(tp_o) + ' | SL=' + fmt_price(sl_o))
            led.setdefault('pending_sells', set()).add(sym)
            log.info('G-oco-health: OCO rebuilt for %s', sym)
        else:
            log.error('G-oco-health: Failed for %s: HTTP %s', sym, code2)


def backfill_oco(st, ws_t, client, led, prices):"""

T_NEW = """def _match_sym_orders(ex_orders, sym, sym_vol):
    \"\"\"G-oco-health: Match exchange sell orders by name (in-check) or amount.\"\"\"
    sym_lower = sym.lower()
    matched = []
    for o in ex_orders:
        if str(o.get('type')) != 'sell':
            continue
        src = str(o.get('srcCurrency', '')).lower()
        # Match by name: symbol in srcCurrency or vice versa
        if sym_lower in src or src in sym_lower:
            matched.append(o)
            continue
        # Fallback: match by amount (within 1% tolerance)
        try:
            amt = float(o.get('amount', 0) or 0)
            if sym_vol > 0 and abs(amt - sym_vol) / sym_vol < 0.01:
                matched.append(o)
        except (TypeError, ValueError):
            pass
    return matched


def oco_health_check(sh, st, state=None):
    \"\"\"G-oco-health: Verify OCO legs on exchange every 10 min. Rebuild if broken/missing.\"\"\"
    client = make_client()
    if client is None:
        return
    ws_t = sh.worksheet(ORDERS_TAB)
    led = read_ledger(ws_t)
    
    try:
        code, od = client.open_orders()
        if code != 200:
            log.error('G-oco-health: open_orders failed HTTP %s', code)
            return
        ex_orders = od.get('orders', []) or []
    except Exception:
        log.exception('G-oco-health: open_orders exception')
        return

    for sym, p in led['positions'].items():
        rv = p.get('real_volume') or 0
        if rv <= 1e-12:
            continue
        
        sym_sell_orders = _match_sym_orders(ex_orders, sym, rv)
        
        if len(sym_sell_orders) >= 2:
            continue
        
        log.warning('G-oco-health: %s has %d sell orders (expected 2). Rebuilding...', sym, len(sym_sell_orders))
        
        for o in sym_sell_orders:
            oid = clean_oid(o.get('id') or o.get('pairId'))
            if oid:
                client.cancel_order(oid)
        
        sl_o, tp_o = None, None
        for _, rr in reversed(led['rows']):
            if rr[1].strip().upper() == sym and rr[2].strip() == 'خرید' and rr[11].strip() in EXECUTED:
                sl_o = parse_price(rr[8])
                tp_o = parse_price(rr[9])
                break
        
        if not (sl_o and tp_o and sl_o > 0 and tp_o > 0):
            log.error('G-oco-health: %s cannot rebuild OCO. SL/TP not found.', sym)
            continue
            
        vol_o = currency_available(client, sym)
        if vol_o is None or vol_o <= 1e-12:
            vol_o = rv
            log.warning('G-oco-health: %s active=0, using ledger vol %s', sym, rv)
        
        code2, data2 = client.place_oco_sell(sym, vol_o, tp_o, sl_o)
        ok2 = code2 == 200 and isinstance(data2, dict) and data2.get('status') == 'ok'
        
        if ok2:
            o2 = (data2.get('order') or {}) if isinstance(data2, dict) else {}
            leg_ids = []
            if isinstance(o2, dict):
                for _k in ('id', 'pairId', 'orderId'):
                    if o2.get(_k): leg_ids.append(clean_oid(o2.get(_k)))
            if isinstance(data2, dict) and isinstance(data2.get('orders'), list):
                for _lg in data2['orders']:
                    if isinstance(_lg, dict):
                        for _k in ('id', 'pairId', 'orderId'):
                            if _lg.get(_k): leg_ids.append(clean_oid(_lg.get(_k)))
            oid_oco = '|'.join(dict.fromkeys(leg_ids))
            
            record_trade(ws_t, 'فروش', sym, '', 'OCO تور ایمنی (G-oco-health)',
                         fmt_price(tp_o), vol_o, round(vol_o * tp_o, 2),
                         fmt_price(sl_o), fmt_price(tp_o), oid_oco, ST_PLACED,
                         'OCO rebuilt: TP=' + fmt_price(tp_o) + ' | SL=' + fmt_price(sl_o))
            led.setdefault('pending_sells', set()).add(sym)
            log.info('G-oco-health: OCO rebuilt for %s', sym)
        else:
            _err_msg = str(data2)[:200] if isinstance(data2, dict) else str(data2)[:200]
            log.error('G-oco-health: Failed for %s: HTTP %s | %s', sym, code2, _err_msg)


def backfill_oco(st, ws_t, client, led, prices):"""

CHANGES = {
    'trader.py': [(T_OLD, T_NEW, 'fix symbol matching + error logging in oco_health_check')]
}

def main():
    os.chdir(os.path.expanduser('~/nobitex-usdt'))
    print('=' * 72)
    print('fix_oco_health.py - Fix OCO health symbol matching + error logging')
    print('mode: DEPLOY' if DEPLOY else 'mode: DRY-RUN (preview only)')
    print('=' * 72)
    all_ok = True
    applied = []
    fname = 'trader.py'
    if not os.path.exists(fname):
        print('X %s not found' % fname)
        sys.exit(1)
    src = open(fname, encoding='utf-8').read()
    cand = src
    file_ok = True
    for old, new, desc in CHANGES[fname]:
        if old in cand:
            cand = cand.replace(old, new, 1)
            print('+ %s: %s' % (fname, desc))
            applied.append((fname, desc))
        else:
            print('X %s: pattern not found: %s' % (fname, desc))
            print('  expected: %s...' % old[:80])
            file_ok = False
            all_ok = False
    if not file_ok:
        sys.exit(1)
    cand_name = 'trader_candidate.py'
    with open(cand_name, 'w', encoding='utf-8') as f:
        f.write(cand)
    try:
        py_compile.compile(cand_name, doraise=True)
        print('  + py_compile: OK')
    except py_compile.PyCompileError as e:
        print('  X py_compile FAILED: %s' % e)
        sys.exit(1)
    if DEPLOY:
        bak = '%s.bak.%s' % (fname, time.strftime('%Y%m%d_%H%M'))
        shutil.copy2(fname, bak)
        print('  + backup: %s' % bak)
        shutil.move(cand_name, fname)
        print('  + deployed: %s' % fname)
    else:
        print('  (dry-run: candidate saved as %s)' % cand_name)
    print()
    print('=' * 72)
    print('+ %d patches ready' % len(applied))
    if DEPLOY:
        print('Deploy complete. Test with oco_health_check().')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python fix_oco_health.py --deploy')
    print('=' * 72)

if __name__ == '__main__':
    main()
