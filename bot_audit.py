#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bot_audit.py — ممیزی جامع عملکرد ربات نوبیتکس (اصلاح شده)"""
import os, sys, re, gspread
from datetime import datetime
sys.path.insert(0, os.path.expanduser('~/nobitex-usdt'))

def load_env(path='.env'):
    env = {}
    if not os.path.exists(path): return env
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line: continue
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def main():
    import trader
    from settings import Settings
    
    print("╔════════════════════════════════════════════════════════════╗")
    print("║   📊 ممیزی جامع ربات معاملات اسپات نوبیتکس                ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print(f"زمان تولید: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    e = load_env()
    sid = e.get('SHEET_ID')
    gc = gspread.service_account(filename='service_account.json')
    sh = gc.open_by_key(sid)
    st = Settings.from_sheet(sh.worksheet('تنظیمات'))
    
    # 1. مالی و پوزیشن‌ها
    print("━━━ ۱) وضعیت مالی و پوزیشن‌های باز ━━━")
    try:
        client = trader.make_client()
        code, data = client.wallets()  # استفاده از تابع صحیح
        wl = data.get('wallets') if isinstance(data, dict) else None
        balances = {}
        if wl:
            for w in wl:
                currency = w.get('currency', '').upper()
                balance = float(w.get('balance', 0) or 0)
                if balance > 0:
                    balances[currency] = balance
        
        usdt = balances.get('USDT', 0.0)
        print(f"  💵 موجودی USDT: {usdt:.2f}")
        print(f"  💼 سایر دارایی‌ها: {len([k for k in balances if k != 'USDT'])} مورد")
        
        code, od = client._sc.get('/market/orders/list')
        open_orders = od.get('orders', []) or []
        print(f"  📌 سفارش‌های باز (OCO): {len(open_orders)}")
        for o in open_orders[:5]:
            sym = o.get('srcCurrency', '').upper()
            tp = float(o.get('price', 0))
            print(f"    - {sym}: قیمت TP={tp}")
    except Exception as ex:
        print(f"  ✗ خطا در دریافت اطلاعات صرافی: {ex}")

    # 2. معاملات بسته‌شده اخیر
    print("\n━━━ ۲) ۵ معامله بسته‌شده اخیر ━━━")
    try:
        ws = sh.worksheet('اتمام معاملات')
        vals = ws.get_all_values()[1:]
        for r in vals[-5:]:
            if len(r) >= 7:
                print(f"  {r[0][:10]} | {r[1]:<6} | P&L: {r[6]:<8} | {r[8][:30]}")
    except Exception as ex:
        print(f"  ✗ خطا در خواندن اتمام معاملات: {ex}")

    # 3. عملکرد گاردها (آمار ۲۴ ساعت گذشته)
    print("\n━━━ ۳) آمار گاردها (۲۴ ساعت اخیر) ━━━")
    try:
        log_path = os.path.expanduser('~/nobitex-usdt/update.log')
        with open(log_path, encoding='utf-8') as f:
            lines = f.readlines()[-500:]
        
        guards_stats = {}
        for line in lines:
            if 'skip buy' in line or 'انجام نشد' in line:
                m = re.search(r'(?:skip buy|خرید)\s+(\w+)', line)
                sym = m.group(1) if m else '—'
                reason = line.split(':', 2)[-1].strip()[:40] if ':' in line else '—'
                
                if 'momentum' in reason: g = 'PUMP_GUARD_PCT'
                elif 'SL band' in reason: g = 'G_BANDCAP'
                elif 'no global mark' in reason: g = 'G_GLOBAL'
                elif 'local premium' in reason: g = 'G_PREMIUM'
                elif 'above global mark' in reason: g = 'G_MARK_DEV'
                elif 'symbol blocked' in reason: g = 'BLOCKED_SYMBOLS'
                elif 'bearish' in reason: g = 'TREND_FILTER'
                elif 'knife' in reason or 'losing exits' in reason: g = 'LOSS_STREAK_LIMIT'
                elif 'TTL' in line or 'کهنه' in reason: g = 'ENTRY_TTL_MIN'
                elif 'سقف پوزیشن' in reason: g = 'MAX_OPEN_POSITIONS'
                elif 'کول‌داون' in reason or 'خروج زیان‌ده' in reason: g = 'REENTRY_COOLDOWN'
                else: g = 'OTHER'
                
                if g not in guards_stats:
                    guards_stats[g] = {'count': 0, 'last_sym': sym, 'last_reason': reason}
                guards_stats[g]['count'] += 1
                guards_stats[g]['last_sym'] = sym
                guards_stats[g]['last_reason'] = reason

        if not guards_stats:
            print("  ✓ هیچ گاردی در ۲۴ ساعت گذشته ورودی را رد نکرده است (بازار رنج)")
        else:
            for g, stats in guards_stats.items():
                print(f"  {g:<25} | رد: {stats['count']} بار | آخرین نماد: {stats['last_sym']}")
    except Exception as ex:
        print(f"  ✗ خطا در تحلیل لاگ: {ex}")

    # 4. خریدهای ثبت‌شده اخیر
    print("\n━━━ ۴) ۵ خرید ثبت‌شده اخیر ━━━")
    try:
        buys = [l.strip() for l in lines if 'ثبت شد: خرید' in l][-5:]
        for b in buys:
            m = re.search(r'ثبت شد: خرید (\w+)', b)
            sym = m.group(1) if m else '—'
            print(f"  {b[:19]} | {sym}")
        if not buys:
            print("  هیچ خریدی در ۲۴ ساعت اخیر ثبت نشده است.")
    except Exception:
        pass

    # 5. وضعیت بک‌تست و universe
    print("\n━━━ ۵) وضعیت استراتژی (اخیر) ━━━")
    try:
        bt_logs = [l.strip() for l in lines if 'بک تست' in l and 'لبه معتبر' in l][-1:]
        if bt_logs:
            print(f"  بک‌تست: {bt_logs[0].split('—')[-1].strip()}")
            
        univ_logs = [l.strip() for l in lines if 'چرخه universe' in l][-1:]
        if univ_logs:
            print(f"  Universe: {univ_logs[0].split(':')[-1].strip()[:80]}")
    except Exception:
        pass

    print("\n════════════════════════════════════════════════════════════")
    print("پایان گزارش ممیزی")

if __name__ == '__main__':
    main()
