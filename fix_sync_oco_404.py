#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_sync_oco_404.py - رفع باگ 404 NotFound در sync_order_statuses

مشکل: وقتی یک لگ OCO اجرا می‌شود (Done)، لگ دیگر توسط نوبیتکس حذف می‌شود
و API خطای 404 NotFound برمی‌گرداند.

در کد فعلی، این خطا به‌عنوان status نامشخص (None) تفسیر می‌شود و لگ در
legs ثبت نمی‌شود. اگر هر دو لگ 404 شوند (قبل از اینکه Done ثبت شود)،
legs خالی می‌شود و OCO نادیده گرفته می‌شود. سپس reconcile آن را به‌عنوان
"خروج از کیف پول" می‌بندد.

شاهد: MEW و WLD با "خروج از کیف پول" بسته شدند، اما استعلام نشان داد
یک لگ Done و یک لگ 404 دارند.

راه‌حل: نادیده گرفتن خطای 404 (لگ حذف شده) و بررسی فقط لگ‌های موجود.
اگر لگ دیگر Done باشد، OCO به‌درستی "پر شد" ثبت می‌شود.
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """        for oid in oids:
            code, data = client.order_status(oid)
            o = data.get('order') if isinstance(data, dict) else None
            raw = o.get('status') if isinstance(o, dict) else None
            if raw in api_map:
                legs[oid] = (raw, o)
            else:
                log.warning('order %s: unknown status HTTP %s | %s',
                            oid, code, str(data)[:120])"""

T_NEW = """        for oid in oids:
            code, data = client.order_status(oid)
            # G-fix: وقتی یک لگ OCO اجرا می‌شود، لگ دیگر حذف می‌شود (404)
            # این لگ را نادیده بگیریم - لگ دیگر Done خواهد بود
            if code == 404 or (isinstance(data, dict) and str(data.get('error')) == 'NotFound'):
                continue
            o = data.get('order') if isinstance(data, dict) else None
            raw = o.get('status') if isinstance(o, dict) else None
            if raw in api_map:
                legs[oid] = (raw, o)
            else:
                log.warning('order %s: unknown status HTTP %s | %s',
                            oid, code, str(data)[:120])"""


def main():
    print('=' * 70)
    print('fix_sync_oco_404.py - رفع باگ 404 NotFound در sync_order_statuses')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN"}')
    print('=' * 70)
    
    with open('trader.py', 'r', encoding='utf-8') as f:
        src = f.read()
    
    if T_OLD not in src:
        print('! T_OLD not found - already patched?')
        return 1
    
    new_src = src.replace(T_OLD, T_NEW)
    
    try:
        compile(new_src, 'trader.py', 'exec')
        if DEPLOY:
            bak = f'trader.py.bak.{time.strftime("%Y%m%d_%H%M")}'
            shutil.copy('trader.py', bak)
            with open('trader.py', 'w', encoding='utf-8') as f:
                f.write(new_src)
            print(f'+ trader.py: رفع باگ 404 NotFound در sync_order_statuses')
            print(f'  + backup: {bak}')
        else:
            print('+ trader.py (dry-run): رفع باگ 404 NotFound')
        return 0
    except SyntaxError as e:
        print(f'  + syntax error: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
