#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
net_timeout.py — timeout پیش‌فرض + retry فقط-GET (F1+F2)
F1 (حادثه ۲۲:۳۴ سپتامبر ۲۹): بلوک ۷ ساعته روی recv گوگل → تزریق timeout=30
F2 (حادثه 1405/08/01): ۳۱ خطای قطع/ریست در چرخه‌ها → retry فقط برای GET
سیاست retry (فقط GET — خواندن شیت/آمار عمومی؛ POST/PUT هرگز، تا سفارش یا
append دفتر دوبله نشود):
  - ConnectionError (قطع/ریست/ConnectTimeout): حداکثر ۲ retry — شکست سریع
  - Timeout خواندن: حداکثر ۱ retry
بدترین حالت هر فراخوانی ~۶۵s — داخل بودجه ۵۷۰s تیک.
"""
import time

import requests

DEFAULT_TIMEOUT = 30  # ثانیه — سخاوتمندانه برای batch آپدیت‌های شیت

_orig_request = requests.sessions.Session.request


def _request_with_default_timeout(self, method, url, **kwargs):
    if not kwargs.get('timeout'):
        kwargs['timeout'] = DEFAULT_TIMEOUT
    is_get = str(method).upper() == 'GET'
    attempt = 0
    while True:
        try:
            return _orig_request(self, method, url, **kwargs)
        except requests.exceptions.ConnectionError:
            if not is_get or attempt >= 2:
                raise
            attempt += 1
            time.sleep(2)
        except requests.exceptions.Timeout:
            if not is_get or attempt >= 1:
                raise
            attempt += 1
            time.sleep(2)


if getattr(_orig_request, '__module__', '') != __name__:
    requests.sessions.Session.request = _request_with_default_timeout
