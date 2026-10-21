#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_settings_bandcap.py - Add MAX_SL_BAND_PCT to settings.py"""
import py_compile

src = open('settings.py', encoding='utf-8').read()

# ۱. افزودن به DEFAULTS
old_defaults = "'POSITION_TIMEOUT_MIN_PCT': '0'}"
new_defaults = "'POSITION_TIMEOUT_MIN_PCT': '0', 'MAX_SL_BAND_PCT': '8.0'}"
if 'MAX_SL_BAND_PCT' not in src:
    src = src.replace(old_defaults, new_defaults, 1)
    print('+ settings.py: MAX_SL_BAND_PCT added to DEFAULTS')

# ۲. افزودن به PARAM_RANGES
old_range = "    'PUMP_GUARD_PCT':       (0.0, 50.0),"
new_range = "    'PUMP_GUARD_PCT':       (0.0, 50.0),\n    'MAX_SL_BAND_PCT':      (2.0, 20.0),"
if 'MAX_SL_BAND_PCT' not in src.split('PARAM_RANGES')[1].split('}')[0]:
    src = src.replace(old_range, new_range, 1)
    print('+ settings.py: MAX_SL_BAND_PCT added to PARAM_RANGES')

# ۳. افزودن property
old_prop = "        return max(0.0, self._tnum('MAX_SL_MULT', 1.5))"
new_prop = """        return max(0.0, self._tnum('MAX_SL_MULT', 1.5))

    @property
    def max_sl_band_pct(self):
        \"\"\"G-bandcap: max SL band width (%). Reject entries with wider SL.\"\"\"
        return max(2.0, self._tnum('MAX_SL_BAND_PCT', 8.0))"""
if 'def max_sl_band_pct' not in src:
    src = src.replace(old_prop, new_prop, 1)
    print('+ settings.py: max_sl_band_pct property added')

open('settings.py', 'w', encoding='utf-8').write(src)
py_compile.compile('settings.py', doraise=True)
print('✓ settings.py compiled successfully')
