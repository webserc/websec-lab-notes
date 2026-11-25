# day2 认证机制深度资料（补充篇）

> 用法：这份比昨天那份深一层，讲的是「为什么」。
> 看不懂的地方先跳过，把能看懂的看完就行，不用一口气吃下。

---

## 第 0 章：先补一个底层——HTTP 请求长什么样

你每天敲的 `curl`，本质是把下面这段文本发出去：

```
POST /login HTTP/1.1                 ← 请求行：方法 路径 协议版本
Host: 192.168.36.129:5000            ← 以下都是头（Header）
User-Agent: curl/8.5.0
Accept: */*
Content-Type: application/x-www-form-urlencoded
Content-Length: 32
                                     ← 空行：头和体之间必须空一行
username=alice&password=alice123     ← 请求体（Body）
```

服务器回的：

```
HTTP/1.1 200 OK                      ← 状态行
Server: Werkzeug/3.1.9
Content-Type: application/json
Set-Cookie: session_id=87dd...
Set-Cookie: session=eyJuYW1l...
                                     ← 空行
{"ok": true, "msg": "登录成功"}       ← 响应体
```

**记住三件事：**

1. `Set-Cookie` 只能出现在**响应**里，服务器用它「下发」票据。
2. `Cookie` 只能出现在**请求**里，浏览器用它「带上」票据。
3. 头（Header）是 `名字: 值` 的形式，一个请求可以有多个同名头。

**为什么这重要：** 你后面打的所有认证绕过，改的都是这几行 Text。所谓「伪造 cookie」，就是在 `Cookie:` 那一行后面改几个字符。

---

## 第 1 章：Cookie 到底是什么

### 1.1 不是「文件」，是一条规则

浏览器内部有一张表，长这样：

| 域名 | 路径 | 名字 | 值 | 过期时间 | 标记 |
|---|---|---|---|---|---|
| 192.168.36.129 | / | session | eyJuYW1l... | 会话结束 | HttpOnly |

每次你请求这个域名，浏览器就去表里翻，把所有**匹配域名和路径**的行拼成：

```
Cookie: session=eyJuYW1l...; session_id=87dd...
```

塞进请求头。

### 1.2 服务端怎么「种」下这个 cookie

看源码里这行：

```python
resp = make_response(jsonify(...))
resp.set_cookie("session_id", sid, httponly=True, samesite="Lax")
```

或者 Flask 的 session 机制（自动的）：

```python
session["uid"] = 1
# Flask 在返回响应时，自动把 session 序列化 + 签名，塞进 Set-Cookie
```

### 1.3 为什么它「自动」

浏览器收到 `Set-Cookie` 就存，之后每次请求自动带。

**这既是便利也是漏洞来源：**

- 便利：你写前端不用管 cookie
- 漏洞：CSRF。别的网站也能让你的浏览器自动带上 cookie，去请求你的银行

防护手段就是 `SameSite`：

| 值 | 行为 |
|---|---|
| `Strict` | 从别的站跳过来，一律不带 |
| `Lax` | GET 导航带，POST 不带（默认值） |
| `None` | 一律带，但必须配 `Secure`（只能 HTTPS） |

---

## 第 2 章：Base64 不是加密

### 2.1 它只是「换一种写法」

Base64 把任意字节流，每 3 个字节（24 bit）切成 4 个 6-bit，每个 6-bit 映射成 64 个可打印字符之一：

```
ABC 字符表：A-Z a-z 0-9 + /
```

于是任意二进制都能变成「纯文本」，方便塞进 cookie、URL、JSON 里。

### 2.2 手算一个

原文：`{"name":"alice","uid":1}`

编码后：`eyJuYW1lIjoiYWxpY2UiLCJ1aWQiOjF9`

第一个字符 `{` = 0x7B = `01111011`，前 6 位 `011110` = 30 → 字符表第 30 位 = `e`

所以 `{` 变成了 `e`。就是这么机械。

### 2.3 为什么它能当 cookie 的值

原始 JSON 里有 `{` `}` `"` `:` 这些字符。HTTP 头里带这些容易出问题（引号、冒号都是分隔符）。

Base64 之后只剩字母数字和 `+ /`，安全。

URL 里还要再换一次：`+` → `-`，`/` → `_`，去掉 `=` 填充。这就是 **base64url**，JWT 用的那个。

### 2.4 关键结论

**Base64 可逆，谁都能解。** 所以 cookie 里的内容对攻击者是透明的。

「签名」不是为了藏内容，是为了让你改了就被发现。

---

## 第 3 章：HMAC 签名是怎么算的

### 3.1 一句话

```
签名 = HMAC-SHA256(密钥, 内容)
```

### 3.2 拆开看

`HMAC(K, m)` = `SHA256( (K ⊕ opad) || SHA256( (K ⊕ ipad) || m ) )`

不用背这个公式。你只要知道三件事：

1. 输入是**密钥**和**内容**
2. 输出是**固定 32 字节**，转成 hex 是 **64 个字符**
3. 同样的 K 和 m，永远得到同样的结果；改一个字节，结果天翻地覆

### 3.3 用你的 lab 走一遍

源码：

```python
body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
sig = hmac.new(app.secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()
return f"{body}.{sig}"
```

拆解：

| 步骤 | 代码 | 得到什么 |
|---|---|---|
| 1 | `json.dumps(payload)` | `{"uid": 1, "exp": ..., "nonce": "..."}` |
| 2 | `.encode()` | 上面那个字符串的字节 |
| 3 | `urlsafe_b64encode(...)` | base64url 字符串 |
| 4 | `.decode().rstrip("=")` | 去掉 `=` 填充 |
| 5 | `hmac.new(secret, body, sha256)` | 32 字节签名 |
| 6 | `.hexdigest()` | 64 个字符的十六进制 |
| 7 | `f"{body}.{sig}"` | 两段，用点连接 |

### 3.4 服务端怎么验

```python
body, sig = token.rsplit(".", 1)                    # 从右边切一刀
expect = hmac.new(secret, body, sha256).hexdigest() # 自己算一遍
if not hmac.compare_digest(sig, expect):            # 比一比
    return None, "签名不匹配"
```

**注意 `compare_digest`：** 它比较时**耗时不随差异变化**，防止「时间侧信道攻击」——普通 `==` 比较，第一个字符不同就立刻返回，攻击者可以通过响应时间逐字节猜出签名。

这是个细节，但真实项目里算安全缺陷。

### 3.5 为什么改一个字节就废

SHA-256 是雪崩效应：输入改 1 bit，输出平均变一半位数。

所以你想把 `uid=1` 改成 `uid=2`，签名会完全变样。服务端重算一遍，对不上，直接拒。

---

## 第 4 章：Flask 的 session 比你想的复杂

### 4.1 它用了 itsdangerous 这个库

那条 cookie：

```
eyJuYW1lIjoiYWxpY2UiLCJ1aWQiOjF9.avS0fw.Z4JXoBj...Wss
└────── payload ──────┘ └时间戳┘ └──── 签名 ────┘
```

三段，用点分开。

| 段 | 内容 | 说明 |
|---|---|---|
| 1 | payload | base64url(JSON)，可能还经过 zlib 压缩 |
| 2 | timestamp | 6 个字符，base64 编码的 Unix 时间 |
| 3 | signature | base64url(HMAC-SHA1(key, payload + "." + timestamp)) |

### 4.2 签名不是直接签 payload

注意第 3 段的输入是 `payload + "." + timestamp`，不是单独的 payload。

这样时间戳也被保护了，攻击者不能改过期时间去延长 cookie 寿命。

### 4.3 密钥不是直接用

itsdangerous 会从 `secret_key` 派生一个子密钥，用 `salt="cookie-session"` 做 HMAC 派生。

```python
key = HMAC(secret_key, "cookie-session")
```

**为什么这么做：** 同一个 secret_key 可能被多处用（session、CSRF token、密码重置 token）。加了 salt，一处泄露不会殃及另一处。

### 4.4 为什么 flask-unsign 能伪造

因为它就是拿 Flask 自己的 `SecureCookieSessionInterface` 来序列化：

```python
app = Flask(__name__)
app.secret_key = "123456"
serializer = app.session_interface.get_signing_serializer(app)
cookie = serializer.dumps({"name": "admin", "uid": 0})
```

这段和 `flask_forge.py` 一模一样——因为它就是 Flask 的内部实现。

**所以说：工具没有魔法，它只是把源码抄了一遍。**

---

## 第 5 章：三种机制的完整生命周期

### 5.1 服务端 session

```
① 用户提交账号密码
② 服务端验证通过 → 生成随机 session_id（32 位 hex）
③ 服务端在存储里写：{session_id: {uid, name, ip, ua, time}}
④ 响应下发：Set-Cookie: session_id=xxx
⑤ 用户下次请求 → 浏览器自动带 Cookie: session_id=xxx
⑥ 服务端拿 session_id 去存储里查
   ├─ 查到 → 认你
   └─ 查不到 → 401
⑦ 用户点退出 → 服务端删掉那条记录
```

**攻击面：**
- 步骤 ② 随机数不够随机 → 可预测 → 能猜出别人的 id
- 步骤 ③ 存储泄露（文件可读、Redis 无密码、越权接口）→ 拿到所有人的 id
- 步骤 ⑦ 退出只删客户端 cookie，服务端没删 → 旧 id 还能用（会话固定）

### 5.2 Flask 签名 cookie

```
① 用户提交账号密码
② 服务端验证通过 → session["uid"] = 1
③ Flask 在返回响应前：
   json 序列化 → base64url → 取时间戳 → 算签名 → 拼成 payload.ts.sig
④ 响应下发：Set-Cookie: session=payload.ts.sig
⑤ 用户下次请求 → 浏览器自动带
⑥ Flask 拿密钥重算签名
   ├─ 对得上 → 反序列化 → 认你
   └─ 对不上 → session 变空 → 401
⑦ 用户点退出 → session.clear() → 下发一个空 cookie
```

**攻击面：**
- 密钥弱 → 伪造任意身份（你的 lab 就是这条）
- 密钥泄露 → 同上
- 内容明文 → 泄露信息（比如 cookie 里存了手机号）

### 5.3 自定义 token

```
① 用户提交账号密码
② 服务端验证通过 → 组装 payload = {uid, exp, nonce}
③ base64url(json) → body
④ HMAC(secret, body) → sig
⑤ 返回 JSON：{"token": body + "." + sig}
⑥ 客户端自己保存（localStorage / 内存）
⑦ 下次请求：Authorization: Bearer body.sig
⑧ 服务端验签 + 检查 exp
```

**区别：** 不经过浏览器自动管理，由前端代码手动加头。所以**不受 CSRF 影响**（别的站发不出带自定义头的请求）。

**攻击面：**
- 密钥弱 → 伪造
- 没有防重放 → 偷到就能无限用
- exp 太长 → 偷到能长期用
- nonce 生成了不校验 → 形同虚设

---

## 第 6 章：你这个 lab 的漏洞，逐个拆

### 漏洞 1：硬编码弱密钥（根因）

```python
app.secret_key = "123456"
```

**为什么致命：** 一把密钥同时保护两条路。它泄露 = 整个认证体系失效。

**正确做法：**

```python
import os, secrets
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
```

密钥必须在环境变量里，长度 32 字节以上，随机生成，**永不进代码仓库**。

### 漏洞 2：信任客户端传来的身份

```python
g.user = {"id": session["uid"], "name": session["name"], ...}
```

`name` 是攻击者写在 cookie 里的，服务端直接拿来用。

**正确做法：** cookie 里只存 `uid`，每次请求拿 uid 去数据库查：

```python
row = db.query("SELECT id, name FROM users WHERE id = ?", (session["uid"],))
if not row:
    return 401
g.user = row
```

**原则：客户端只传「标识」，不传「身份」。**

### 漏洞 3：/admin/sessions 越权

任何持有合法 token 的人都能访问，返回所有人的会话。

**正确做法：** 加管理员校验

```python
@app.route("/admin/sessions")
@login_required
def admin_sessions():
    if g.user.get("is_admin") is not True:
        return jsonify({"error": "forbidden"}), 403
    ...
```

**注意 403 和 401 的区别：** 401 是「你没登录」，403 是「你登录了但没权限」。

### 漏洞 4：无防重放

同一个 token 连发两次都成功。

**正确做法：** 记录用过的 nonce（服务端有状态），或者改用一次性 token。

```python
if nonce in used_nonces:
    return None, "token 已使用"
used_nonces.add(nonce)
```

**代价：** 服务端要存东西，就不再是「无状态」了。这是无状态 token 的固有取舍。

### 漏洞 5：nonce 生成但不校验

```python
payload = {..., "nonce": uuid.uuid4().hex}   # 生成了
# verify_token 里从来没看过它              # 没校验
```

**代码审计里的信号：** 看到一个字段存在于生成逻辑，但验证逻辑里没有 → 要么忘了，要么本来就没打算用。

### 漏洞 6：session_id 是死代码

```python
resp.set_cookie("session_id", sid)   # 下发了
# login_required 里只查 if "uid" in session（Flask 的）
# session_id 从来没被读过
```

**危害：** 虽然没有直接漏洞，但泄露了一个「看起来像凭证」的东西。真实系统里这种会误导后续开发者。

### 漏洞 7：错误信息太细

```python
return jsonify({"error": err}), 401   # err 是 "签名不匹配" 或 "token 已过期"
```

攻击者能区分两种失败，进而判断自己的 payload 是否被正确解析。

**正确做法：** 统一返回 `{"error": "未认证"}`，详细信息写日志。

### 漏洞 8：空 token 未校验

```python
body, sig = token.rsplit(".", 1)   # token 为空时只切出一个元素
# → ValueError: not enough values to unpack
```

**正确做法：** 先判空

```python
if not token or "." not in token:
    return None, "格式错误"
```

---

## 第 7 章：修复清单与复测方法

### 按优先级修

| 优先级 | 修什么 | 怎么验证修好了 |
|---|---|---|
| P0 | 换密钥 | 用旧密钥签的 token 全部失效（401） |
| P0 | session 只存 uid，name 查库 | 伪造 name=admin 的 cookie，显示的还是真实用户 |
| P1 | /admin/sessions 加管理员校验 | 用普通用户 token 访问，返回 403 |
| P1 | 记录 nonce，防重放 | 同一个 token 第二次请求返回 401 |
| P2 | 缩短 TTL 到 60 秒 | 等 70 秒后请求返回 401 |
| P2 | 统一错误信息 | 所有失败都返回 `{"error": "未认证"}` |
| P3 | 空入参校验 | 空 token 返回 401 而不是 500 |

### 复测脚本

修完把 `day2-exploit.py` 重跑一遍：

- 路径 A（伪造 Flask cookie）应该全 401
- 路径 B（伪造 token）应该全 401
- 旧 token 应该 401（密钥换了）

**通了的就是没修好，不通的就是修对了。**

---

## 第 8 章：把这套能力用到别的地方

这套「读源码 → 找密钥 → 复刻算法 → 造凭证」的流程，换成别的框架也一样：

| 框架 | 密钥在哪 | 凭证格式 |
|---|---|---|
| Flask | `app.secret_key` | `payload.ts.sig` |
| Django | `SECRET_KEY` | `payload:timestamp:signature` |
| Express + jsonwebtoken | `jwt.sign(payload, secret)` | `header.payload.sig` |
| Spring Security | `JwtTokenProvider` 的 secret | 标准 JWT |
| PHP | `session_start()` + session 文件 | PHP 自己的格式 |

**共同点：** 都有一个「密钥」，都有一个「签名算法」，都可能被硬编码。

**找法：** 全局搜关键词

```
secret / secret_key / SECRET_KEY / jwt / sign / hmac / token
```

---

## 第 9 章：术语对照总表

| 中文 | 英文 | 一句话 |
|---|---|---|
| 认证 | Authentication | 你是谁 |
| 授权 | Authorization | 你能干什么 |
| 会话 | Session | 一次登录后的持续状态 |
| 令牌 | Token | 证明身份的字符串 |
| 签名 | Signature | 证明内容没被改过 |
| 密钥 | Secret key | 签名的笔 |
| 加密 | Encryption | 让别人看不见内容 |
| 哈希 | Hash | 单向不可逆的指纹 |
| 盐 | Salt | 让相同输入产生不同哈希 |
| 随机数 | Nonce | 一次性使用，防重放 |
| 篡改 | Tamper | 偷偷改动 |
| 重放 | Replay | 把偷到的请求再发一次 |
| 越权 | Privilege escalation | 用低权限干高权限的事 |
| 会话固定 | Session fixation | 让受害者用攻击者知道的会话 id |

---

## 第 10 章：明天之后可以继续追的问题

1. **JWT 和这套自定义 token 到底差在哪？** 只差格式吗？（提示：还差 `alg` 字段、标准库支持、生态）
2. **`alg: none` 攻击是什么？** 为什么 JWT 库会拒绝这种 token？
3. **CSRF 和 token 方案的关系？** 为什么 token 放 Authorization 头就天然免疫 CSRF？
4. **会话固定怎么利用？** 攻击者怎么让受害者用一个已知的 session_id？
5. **`HttpOnly` 能防什么、不能防什么？** XSS 还能不能偷到 cookie？

这五个问题，等你打完 XSS 和越权那块，自然会遇到。
