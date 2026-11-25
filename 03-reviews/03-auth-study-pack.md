# 11/17 白天资料包：三条登录态

> 用法：明天白天看这一份就够，晚上照着敲。
> 目标：晚上能独立填完 A 对照表。

---

## 一、先搞清三种登录态的本质

同一个系统里，同时存在三种「我知道你是谁」的实现方式。它们的区别只有一个问题：

**数据存在哪儿，靠什么防篡改。**

### 1. 服务端 session（session_id）

```
浏览器手里的：  session_id = 87dd648c0e91465bb75362217b7e46c5
服务器手里的：  87dd648c... → {uid: 1, name: alice, ip: ..., ua: ...}
```

- 数据存在**服务器**（内存、Redis、数据库、文件都行）
- 浏览器只拿一个**随机编号**
- 防篡改靠**猜不到**（32 位十六进制 = 128 bit 随机数）
- 伪造不了，只能**偷**

**关键理解：** 它不需要密钥。因为里面没有可改的数据，改了就查不到。

### 2. Flask 签名 cookie（session）

```
浏览器手里的：  eyJuYW1lIjoiYWxpY2UiLCJ1aWQiOjF9.avS0fw.Z4JXoBj...
                └── base64(json) ──┘ └时间戳┘ └── HMAC 签名 ──┘
```

- 数据存在**客户端**（就在 cookie 里，Base64 后可读）
- 防篡改靠**密钥签名**
- 有密钥 = 能伪造任意身份

### 3. 自定义 HMAC token（Authorization: Bearer）

```
浏览器手里的：  eyJ1aWQiOjEsImV4cCI6...}.<sha256签名>
                └── base64url(json) ─┘ └── hex 签名 ──┘
```

- 原理和 JWT 一样：数据明文 + 签名
- 区别是格式自定义（两段，不是 JWT 的三段）
- 所以现成工具（jwt_tool、flask-unsign）全部失效，必须读源码抄算法

---

## 二、A 对照表（晚上填这张）

| 维度 | session_id | Flask session cookie | 自定义 token |
|---|---|---|---|
| 数据存在哪 | | | |
| 客户端拿什么 | | | |
| 防篡改靠什么 | | | |
| 需要密钥吗 | | | |
| 能否伪造 | | | |
| 实测状态码 | | | |
| 实测返回内容 | | | |
| 结论（通/不通/死代码） | | | |

---

## 三、晚上要敲的三条命令

先确认 IP 和端口。你的 lab 昨天是 `192.168.36.129:5000`，如果重启过 IP 可能变，先用 `ifconfig` 看一眼。

### 第一条：用 session_id

```bash
curl -i --cookie "session_id=87dd648c0e91465bb75362217b7e46c5" \
  http://192.168.36.129:5000/home
```

**预期：** 401 + `"error": "未认证"`

**为什么：** 源码里 `login_required` 只检查 `if "uid" in session`，那个 `session` 是 Flask 的签名 cookie，不是 `session_id`。这个 cookie 从来没人读过。

**结论要写：** 「session_id 是死代码，服务端从不校验」。

### 第二条：用伪造的 Flask session

```bash
C=$(python3 flask_forge.py)
curl -i --cookie "session=$C" http://192.168.36.129:5000/home
```

**预期：** 200，页面显示 `欢迎 admin`，`登录方式：cookie-session`

**为什么：** 服务端用 `session["name"]` 当身份，而 name 是你在 cookie 里自己写的。

**结论要写：** 「服务端完全信任客户端传来的身份字段」。

### 第三条：用伪造的 token

```bash
T=$(python3 forge.py)
curl -i -H "Authorization: Bearer $T" http://192.168.36.129:5000/home
```

**预期：** 200，页面显示 `欢迎 token-user`，`登录方式：bearer-token`

**为什么：** 签名验证通过即放行，且服务端没查库还原真实身份。

**结论要写：** 「验签通过 ≠ 身份可信」。

---

## 四、排错对照表

| 现象 | 可能原因 | 怎么办 |
|---|---|---|
| `connection refused` | 服务没起 / IP 变了 | `ifconfig` 看 IP，`python3 app.py` 重启 |
| 401 且 `error: 未认证` | cookie 名写错 / 签名不对 / 字段不存在 | 确认 cookie 名是 `session`；换 `flask_forge.py` 重新签 |
| 401 且 `error: token 已过期` | ttl 太小，签完放太久 | 改 `ttl=3600` 重新签 |
| 401 且 `签名不匹配` | 算法与源码不一致 | 回去对照 `verify_token` 逐行看 |
| 500 Internal Server Error | 服务端代码抛异常 | 看服务端终端里的 traceback |
| 302 跳回 /login | 没带凭证或凭证无效 | 加 `-L` 看跳转目标，或检查头名 |
| `dquote>` | 引号没闭合 | `Ctrl + C`，整行重新粘 |
| `URL rejected: Malformed` | URL 里有空格/引号 | 用变量存起来，或 `--data-urlencode` |

---

## 五、必须搞懂的四组概念

### 1. 签名 vs 加密

| | 加密 | 签名 |
|---|---|---|
| 目的 | 让人看不见内容 | 让人改不了内容 |
| 内容 | 密文 | **明文** |
| 密钥泄露 | 可解密 | **可伪造** |

Flask cookie 和 token 都是**签名**，所以 Base64 一解就是明文。

### 2. 认证 vs 授权

- **认证（Authentication）**：你是谁
- **授权（Authorization）**：你能干什么

这个 lab 的漏洞在于：认证做了一半（验签），授权完全没做（不查 uid 是谁）。

### 3. Cookie 的五个属性

| 属性 | 作用 |
|---|---|
| `HttpOnly` | JS 读不到，防 XSS 偷 cookie |
| `Secure` | 只在 HTTPS 下发送 |
| `SameSite` | 跨站请求是否带 cookie（Lax/Strict/None） |
| `Path` | 哪些路径带这个 cookie |
| `Expires` / `Max-Age` | 什么时候失效 |

`SameSite=None` 必须配 `Secure`，否则浏览器拒收。

### 4. 三者的失败模式

| 机制 | 被攻破的方式 | 后果 |
|---|---|---|
| session_id | 偷到编号（XSS、日志泄露、越权接口） | 直接冒用，无需密钥 |
| Flask cookie | 拿到 secret_key | 伪造任意身份 |
| 自定义 token | 拿到密钥 或 算法实现有缺陷 | 伪造任意身份 |

---

## 六、生词表（抄在代码旁边）

| 单词 | 意思 |
|---|---|
| `session` | 会话 |
| `token` | 令牌 |
| `signature` / `sig` | 签名 |
| `secret` | 密钥 |
| `verify` | 验证 |
| `forge` | 伪造 |
| `serialize` | 序列化（把对象变成字符串） |
| `payload` | 载荷（真正要传的数据部分） |
| `nonce` | 一次性随机数 |
| `expire` / `exp` | 过期 |
| `bearer` | 持有者（Bearer token = 谁持有谁通行） |
| `authorization` | 授权 |
| `authentication` | 认证 |
| `tamper` | 篡改 |
| `traverse` | 遍历/穿越 |

---

## 七、晚上自测（五道题，做完再睡）

1. `session_id` 为什么不需要密钥？
2. Flask cookie 里的数据是加密的还是明文的？怎么验证？
3. `/home` 显示 `欢迎 admin`，这个 admin 是从哪儿来的？
4. `token` 那条路为什么显示 `token-user` 而不是 `alice`？
5. 如果让你修这个系统，你先修哪一处？为什么？

---

## 八、白天的碎片时间怎么用

| 时段 | 任务 |
|---|---|
| 上午班中 | 把「一、三种登录态的本质」读两遍，能用自己的话讲出来 |
| 午饭前后 | 把「二、A 对照表」抄到本子上（表格留空） |
| 下午班中 | 把「三、三条命令」抄下来，一条一行 |
| 下班前 | 把「四、排错对照表」扫一眼，记住最常见的两个 |

晚上坐下就不用想，照着抄好的敲。
