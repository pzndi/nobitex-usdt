#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_scale2_cid.py - تولید clientOrderId برای Scale 2/2 تا توسط cancel_stale_entries لغو شود

مشکل: Scale 2/2 با coid2=None ثبت می‌شد. در نتیجه:
1. cancel_stale_entries آن را به‌عنوان سفارش غیر رباتی رد می‌کرد
2. این سفارشات هرگز با TTL لغو نمی‌شدند
3. موجودی USDT در سفارشات دور از بازار قفل می‌ماند

راه‌حل: تولید coid2 با epoch متفاوت (یک ثانیه بعد) به فرمت nbx-{sym}-{epoch}
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """                reason2 = f"رأی خرید {a['buys']}/{a['total']} تایم‌فریم | Scale 2/2 (BB/2xATR)" + _band_tag(st, row)
                coid2 = None  # G-scale: let exchange auto-generate clientOrderId for 2nd order
                code2, data2 = client.place_order('buy', sym, _price2, vol2, False, client_order_id=coid2)"""

T_NEW = """                reason2 = f"رأی خرید {a['buys']}/{a['total']} تایم‌فریم | Scale 2/2 (BB/2xATR)" + _band_tag(st, row)
                # G-scale: تولید cid برای Scale 2/2 تا توسط cancel_stale_entries قابل لغو باشد
                # الگو باید ^nbx-{sym}-{epoch9+}$ باشد تا cancel_stale_entries آن را بشناسد
                coid2 = f"nbx-{sym.lower()}-{int(time.time())}"
                code2, data2 = client.place_order('buy', sym, _price2, vol2, False, client_order_id=coid2)"""


def main():
    print('=' * 70)
    print('fix_scale2_cid.py - تولید clientOrderId برای Scale 2/2')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN"}')
    print('=' * 70)
    
    with open('trader.py', 'r', encoding='utf-8') as f:
        trader_src = f.read()
    
    if T_OLD not in trader_src:
        print('! T_OLD pattern not found - already patched?')
        return 1
    
    new_src = trader_src.replace(T_OLD, T_NEW)
    
    try:
        compile(new_src, 'trader.py', 'exec')
        print('+ trader.py: تولید cid برای Scale 2/2 (nbx-{sym}-{epoch})')
        print('  + syntax check: OK')
    except SyntaxError as e:
        print(f'  + syntax check FAILED: {e}')
        return 1
    
    if DEPLOY:
        bak = f'trader.py.bak.{time.strftime("%Y%m%d_%H%M")}'
        shutil.copy('trader.py', bak)
        print(f'  + backup: {bak}')
        with open('trader.py', 'w', encoding='utf-8') as f:
            f.write(new_src)
        print('  + deployed: trader.py')
    else:
        with open('trader_candidate.py', 'w', encoding='utf-8') as f:
            f.write(new_src)
        print('  (dry-run: candidate saved)')
    
    print()
    print('=' * 70)
    if DEPLOY:
        print('Deploy complete.')
        print()
        print('⚠️ توجه: سفارشات Scale 2/2 فعلی (4 سفارش) همچنان بدون cid باقی می‌مانند.')
        print('برای لغو آن‌ها، باید دستی لغو کنید یا منتظر بمانید تا پر شوند.')
        print('سفارشات جدید Scale 2/2 با cid ثبت خواهند شد.')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python fix_scale2_cid.py --deploy')
    print('=' * 70)
    return 0

if __name__ == '__main__':
    sys.exit(main())
