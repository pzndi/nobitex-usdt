#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
net_timeout.py — تایم‌اوت پیش‌فرض برای درخواست‌های HTTP بدون timeout (F1)
حادثه ۲۲:۳۴ سپتامبر ۲۹: پروسه روی recv سوکت گوگل (فراخوانی gspread بدون
timeout) ۷ ساعت بلوکه شد؛ flockِ زامبی همه تیک‌های کرون را می‌بلعید.
gspread و refresh توکن google-auth خودشان timeout نمی‌گذارند؛ این ماژول با
wrapper روی requests.Session.request مقدار پیش‌فرض تزریق می‌کند. فراخوانی‌هایی
که timeout صریح دارند (نوبیتکس: 60/30s) دست‌نخورده می‌مانند.
import کردن همین ماژول کافی است — در نقاط ورود (scheduler.py, main.py) ایمپورت شده.
"""
import requests

DEFAULT_TIMEOUT = 30  # ثانیه — سخاوتمندانه برای batch آپدیت‌های شیت

_orig_request = requests.sessions.Session.request


def _request_with_default_timeout(self, method, url, **kwargs):
    if not kwargs.get('timeout'):
        kwargs['timeout'] = DEFAULT_TIMEOUT
    return _orig_request(self, method, url, **kwargs)


if getattr(_orig_request, '__module__', '') != __name__:
    requests.sessions.Session.request = _request_with_default_timeout
