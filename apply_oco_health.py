#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_oco_health.py - G-oco-health: Check OCO status every 10 min"""
import os, sys, shutil, py_compile, time

DEPLOY = '--deploy' in sys.argv

# ═══════════════════════════════════════════════════════════════
# پچ ۱: settings.py — افزودن INTERVAL_OCO_HEALTH_MIN
# ═══════════════════════════════════════════════════════════════
S1_OLD = """                  'INTERVAL_WALLET_MIN', 'INTERVAL_GUARDS_MIN', 'BACKTEST_TIMEFRAME', 'SLTP_TIMEFRAME'}"""
S1_NEW = """                  'INTERVAL_WALLET_MIN', 'INTERVAL_GUARDS_MIN', 'INTERVAL_OCO_HEALTH_MIN', 'BACKTEST_TIMEFRAME', 'SLTP_TIMEFRAME'}"""

S2_OLD = """                  'INTERVAL_GUARDS_MIN': '5',"""
S2_NEW = """                  'INTERVAL_GUARDS_MIN': '5',
                  'INTERVAL_OCO_HEALTH_MIN': '10',"""

S3_OLD = """    'INTERVAL_GUARDS_MIN':     (1, 1440),"""
S3_NEW = """    'INTERVAL_GUARDS_MIN':     (1, 1440),
    'INTERVAL_OCO_HEALTH_MIN': (5, 1440),"""

S4_OLD = """    @property
    def interval_guards_min(self):
        return self._interval('INTERVAL_GUARDS_MIN', 5)"""
S4_NEW = """    @property
    def interval_guards_min(self):
        return self._interval('INTERVAL_GUARDS_MIN', 5)

    @property
    def interval_oco_health_min(self):
        return self._interval('INTERVAL_OCO_HEALTH_MIN', 10)"""

# ═══════════════════════════════════════════════════════════════
# پچ ۲: trader.py — افزودن تابع oco_health_check
# ═══════════════════════════════════════════════════════════════
T1_OLD = """def backfill_oco(st, ws_t, client, led, prices):"""
T1_NEW = """def oco_health_check(sh, st, state=None):
    \"\"\"G-oco-health: Verify OCO legs on exchange every 10 min. Rebuild if broken/missing.\"\"\"
    client = make_client()
    if client is None:
        return
    led = read_ledger(sh)
    ws_t = sh.worksheet(ORDERS_TAB)
    
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

# ═══════════════════════════════════════════════════════════════
# پچ ۳: scheduler.py — افزودن چرخه oco_health
# ═══════════════════════════════════════════════════════════════
SC_OLD = """        ('guards', st.interval_guards_min, lambda: trader.write_guards_status(sh, st, state)),
    ]"""
SC_NEW = """        ('guards', st.interval_guards_min, lambda: trader.write_guards_status(sh, st, state)),
        ('oco_health', st.interval_oco_health_min, lambda: trader.oco_health_check(sh, st, state)),
    ]"""

CHANGES = {
    'settings.py': [(S1_OLD, S1_NEW, 'add INTERVAL_OCO_HEALTH_MIN'),
                    (S2_OLD, S2_NEW, 'default 10'),
                    (S3_OLD, S3_NEW, 'range (5-1440)'),
                    (S4_OLD, S4_NEW, 'property interval_oco_health_min')],
    'trader.py': [(T1_OLD, T1_NEW, 'add oco_health_check function')],
    'scheduler.py': [(SC_OLD, SC_NEW, 'add oco_health task')]
}


def main():
    os.chdir(os.path.expanduser('~/nobitex-usdt'))
    print('=' * 72)
    print('apply_oco_health.py - G-oco-health guard')
    print('mode: DEPLOY' if DEPLOY else 'mode: DRY-RUN (preview only)')
    print('=' * 72)
    all_ok = True
    applied = []
    for fname, patches in CHANGES.items():
        if not os.path.exists(fname):
            print('X %s not found' % fname)
            all_ok = False
            continue
        src = open(fname, encoding='utf-8').read()
        cand = src
        file_ok = True
        for old, new, desc in patches:
            if old in cand:
                cand = cand.replace(old, new, 1)
                print('+ %s: %s' % (fname, desc))
                applied.append((fname, desc))
            else:
                print('X %s: pattern not found: %s' % (fname, desc))
                file_ok = False
                all_ok = False
        if not file_ok:
            continue
        cand_name = fname.replace('.py', '_candidate.py')
        with open(cand_name, 'w', encoding='utf-8') as f:
            f.write(cand)
        try:
            py_compile.compile(cand_name, doraise=True)
            print('  + py_compile: OK')
        except py_compile.PyCompileError as e:
            print('  X py_compile FAILED: %s' % e)
            all_ok = False
            continue
        if DEPLOY:
            bak = '%s.bak.%s' % (fname, time.strftime('%Y%m%d_%H%M'))
            shutil.copy2(fname, bak)
            shutil.move(cand_name, fname)
            print('  + deployed: %s' % fname)
        else:
            print('  (dry-run: %s)' % cand_name)
    print()
    if not all_ok:
        print('X some patches failed')
        sys.exit(1)
    print('+ %d patches ready' % len(applied))
    if DEPLOY:
        print('Deploy complete. Add INTERVAL_OCO_HEALTH_MIN=10 to sheet.')
    else:
        print('dry-run OK. To deploy: python apply_oco_health.py --deploy')
    print('=' * 72)

if __name__ == '__main__':
    main()
