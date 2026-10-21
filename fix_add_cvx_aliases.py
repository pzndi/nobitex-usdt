#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_add_cvx_aliases.py - اضافه کردن CVX و چند نماد دیگر به SYMBOL_ALIASES"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """    'GALA': 'Gala',"""

T_NEW = """    'GALA': 'Gala',
    'CVX': 'ConvexFinance',
    'AAVE': 'Aave',
    'MKR': 'Maker',
    'COMP': 'Compound',
    'SUSHI': 'SushiSwap',
    'CRV': 'CurveDao',
    '1INCH': 'OneInch',
    'BAT': 'BasicAttentionToken',
    'ZIL': 'Zilliqa',
    'KNC': 'KyberNetwork',
    'BUSD': 'BinanceUSD',
    'USDC': 'USDCCoin',
    'TUSD': 'TrueUSD',
    'DAI': 'Dai',
    'PAXG': 'PaxosGold',
    'OCEAN': 'OceanProtocol',
    'FET': 'FetchAI',
    'GRT': 'TheGraph',"""


def main():
    print('=' * 70)
    print('fix_add_cvx_aliases.py - اضافه کردن CVX و نمادهای دیگر به SYMBOL_ALIASES')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN"}')
    print('=' * 70)
    
    with open('trader.py', 'r', encoding='utf-8') as f:
        trader_src = f.read()
    
    if T_OLD not in trader_src:
        print('! T_OLD pattern not found - already patched?')
        return 1
    
    if "'CVX': 'ConvexFinance'" in trader_src:
        print('! CVX already in aliases')
        return 1
    
    new_src = trader_src.replace(T_OLD, T_NEW)
    
    try:
        compile(new_src, 'trader.py', 'exec')
        print('+ trader.py: اضافه شدن CVX و 17 نماد دیگر به SYMBOL_ALIASES')
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
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python fix_add_cvx_aliases.py --deploy')
    print('=' * 70)
    return 0

if __name__ == '__main__':
    sys.exit(main())
