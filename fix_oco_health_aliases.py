#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_oco_health_aliases.py - رفع G-oco-health برای نمادهای با نام متفاوت
- اضافه کردن SYMBOL_ALIASES برای تطبیق ADA<->Cardano, S<->Sonic, ...
- افزایش tolerance تطبیق مقدار از 1% به 3% (برای کارمزد)
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

# بخش ۱: اضافه کردن SYMBOL_ALIASES قبل از _match_sym_orders
T_OLD_1 = """def _match_sym_orders(ex_orders, sym, sym_vol):
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
    return matched"""

T_NEW_1 = """# G-oco-health: نمادهای کوتاه ربات به نام‌های کامل صرافی نوبیتکس
# اگر نماد در open_orders با نام کامل (Cardano) بیاید اما ربات نام کوتاه (ADA) را داشته باشد
SYMBOL_ALIASES = {
    'ADA': 'Cardano',
    'S': 'Sonic',
    'NEAR': 'NEARProtocol',
    'DOGE': 'Dogecoin',
    'XRP': 'Ripple',
    'SOL': 'Solana',
    'BTC': 'Bitcoin',
    'ETH': 'Ethereum',
    'WLD': 'Worldcoin',
    'ZEC': 'Zcash',
    'XAUT': 'TetherGold',
    'PEPE': 'Pepe',
    '1MPEPE': '1MPEPE',
    'SHIB': 'ShibaInu',
    'TRX': 'Tron',
    'LTC': 'Litecoin',
    'BNB': 'BNB',
    'AVAX': 'Avalanche',
    'MATIC': 'MaticNetwork',
    'DOT': 'Polkadot',
    'LINK': 'ChainLink',
    'UNI': 'Uniswap',
    'ATOM': 'Cosmos',
    'FTM': 'Fantom',
    'ALGO': 'Algorand',
    'MANA': 'Decentraland',
    'SAND': 'TheSandbox',
    'AXS': 'AxieInfinity',
    'CHZ': 'Chiliz',
    'GALA': 'Gala',
    'ENS': 'EthereumNameService',
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
    'GRT': 'TheGraph',
    '1ART': 'OneArt',
    'AVAX': 'Avalanche',
}


def _match_sym_orders(ex_orders, sym, sym_vol):
    \"\"\"G-oco-health: Match exchange sell orders by name (in-check) or amount.
    Handles Nobitex full names (Cardano, Sonic, NEARProtocol) via SYMBOL_ALIASES.\"\"\"
    sym_lower = sym.lower()
    # پیدا کردن نام کامل صرافی از aliases
    alias_full = SYMBOL_ALIASES.get(sym.upper(), sym).lower()
    matched = []
    for o in ex_orders:
        if str(o.get('type')) != 'sell':
            continue
        src = str(o.get('srcCurrency', '')).lower()
        # Match by name: short or full alias
        if (sym_lower in src or src in sym_lower
                or alias_full in src or src in alias_full
                or alias_full == src):
            matched.append(o)
            continue
        # Fallback: match by amount (within 3% tolerance - covers exchange fees)
        try:
            amt = float(o.get('amount', 0) or 0)
            if sym_vol > 0 and abs(amt - sym_vol) / sym_vol < 0.03:
                matched.append(o)
        except (TypeError, ValueError):
            pass
    return matched"""


def main():
    print('=' * 70)
    print('fix_oco_health_aliases.py - رفع G-oco-health برای نمادهای با نام متفاوت')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN (preview only)"}')
    print('=' * 70)

    with open('trader.py', 'r', encoding='utf-8') as f:
        trader_src = f.read()

    if T_OLD_1 not in trader_src:
        print('! trader.py: T_OLD_1 pattern not found - already patched?')
        return 1

    new_src = trader_src.replace(T_OLD_1, T_NEW_1)

    # Syntax check
    try:
        compile(new_src, 'trader.py', 'exec')
        print('+ trader.py: SYMBOL_ALIASES + tolerance 3% + name matching fix')
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
        print('  (dry-run: candidate saved as trader_candidate.py)')

    print()
    print('=' * 70)
    if DEPLOY:
        print('Deploy complete.')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python fix_oco_health_aliases.py --deploy')
    print('=' * 70)
    return 0

if __name__ == '__main__':
    sys.exit(main())
