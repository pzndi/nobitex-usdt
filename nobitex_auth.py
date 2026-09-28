#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nobitex_auth.py — کلاینت امضاشده نوبیتکس apiv2 (طبق مستندات رسمی apidocs.nobitex.ir)

روش احراز هویت کلید API (جایگزین کامل Authorization):
  Nobitex-Key       = کلید عمومی (فیلد key هنگام ساخت کلید API)
  Nobitex-Signature = امضای Ed25519 به صورت URL-safe Base64
  Nobitex-Timestamp = زمان Unix بر حسب ثانیه (UTC) — اختلاف مجاز با سرور: ۳۰ ثانیه

متن امضا:  timestamp + METHOD + full_path + raw_body
  raw_body دقیقاً همان بایت‌های ارسالی است (JSON فشرده با separators=(",", ":"))
نکته: برای GET، raw_body خالی است. full_path با / شروع می‌شود و بدون دامنه.
"""
import base64
import email.utils
import json
import time

import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

BASE = 'https://apiv2.nobitex.ir'
USER_AGENT = 'TraderBot/NobitexSheetBot-2.0'


class SignedClient:
    """کلاینت امضاشده — thread-unsafe؛ برای هر مصرف یک نمونه بسازید"""

    def __init__(self, public_key, private_key_b64, timeout=60):
        self.pub = str(public_key).strip()
        raw = base64.urlsafe_b64decode(str(private_key_b64).strip())
        if len(raw) == 64:                     # seed + public concatenation
            raw = raw[:32]
        self.priv = Ed25519PrivateKey.from_private_bytes(raw)
        self.timeout = timeout
        self._clock_offset = 0.0
        self._clock_synced = False

    def sync_clock(self):
        """اختلاف ساعت سرور از هدر Date (امضا حداکثر ±۳۰ ثانیه خطا دارد)"""
        try:
            r = requests.get(f'{BASE}/market/stats', timeout=15)
            server = email.utils.parsedate_to_datetime(r.headers['Date']).timestamp()
            self._clock_offset = server - time.time()
            self._clock_synced = True
        except Exception:
            self._clock_offset = 0.0
        return self._clock_offset

    def request(self, method, path, payload=None, retries=2):
        if not self._clock_synced:
            self.sync_clock()
        method = method.upper()
        body = json.dumps(payload, separators=(',', ':')) if payload else ''
        for attempt in range(retries + 1):
            ts = str(int(time.time() + self._clock_offset))
            msg = f'{ts}{method}{path}{body}'.encode()
            sig = base64.urlsafe_b64encode(self.priv.sign(msg)).decode()
            headers = {'Nobitex-Key': self.pub,
                       'Nobitex-Signature': sig,
                       'Nobitex-Timestamp': ts,
                       'User-Agent': USER_AGENT}
            if method != 'GET':
                headers['Content-Type'] = 'application/json'
            try:
                r = requests.request(method, f'{BASE}{path}',
                                     data=body.encode() if (body and method != 'GET') else None,
                                     headers=headers, timeout=self.timeout)
            except requests.RequestException:
                if attempt < retries:
                    time.sleep(3)
                    continue
                raise
            if r.status_code == 429:            # محدودیت نرخ — طبق مستندات backOff دارد
                wait = 15
                try:
                    wait = int(r.json().get('backOff', 15)) + 1
                except Exception:
                    pass
                time.sleep(min(wait, 60))
                continue
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, {'raw': r.text[:200]}
        return 520, {'raw': 'rate-limited after retries'}

    def get(self, path):
        return self.request('GET', path)

    def post(self, path, payload=None):
        return self.request('POST', path, payload if payload is not None else {})
