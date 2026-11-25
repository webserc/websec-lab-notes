# 11/18 复盘：文件上传第一天

---

## 一、今天做成了什么

### 1. 环境终于跑起来了

DVWA 用 compose 版跑在 `127.0.0.1:4280`，容器两个：`dvwa-dvwa-1`（web）+ `dvwa-db-1`（mysql）。

**关键点：** 端口是 4280，不是 80，也不是 8080。`docker compose ps` 里的 `PORTS` 列写得很清楚。

### 2. 上传 → 执行，第一个洞通了

传 `/tmp/shell.php`（内容 `<?php echo "PWNED:" . $_GET["c"]; ?>`），服务器返回：

```
../../hackable/uploads/shell.php succesfully uploaded!
```

访问 `http://127.0.0.1:4280/hackable/uploads/shell.php?c=hello` → 页面显示 **`PWNED:hello`**。

**结论：** 上传目录可执行，PHP 代码被真正执行了。

### 3. 换后缀实验：`.php5` 不执行

传 `shell.php5` → 文件确实落在服务器上（`docker exec ls` 能看到，37 字节）→ 访问返回 **200**，但内容是源码原文：

```
<?php echo "PWNED:" . $_GET["c"]; ?>
```

**结论：** 能上传、能访问，但**不被解析**，当成静态文件原样发出来。

### 4. 挖到了根因（今天最有价值的一步）

```bash
docker exec dvwa-dvwa-1 grep -rn "SetHandler\|AddHandler\|FilesMatch" /etc/apache2/
```

看到 `/etc/apache2/conf-available/docker-php.conf`：

```apache
<FilesMatch \.php$>
  SetHandler application/x-httpd-php
</FilesMatch>
```

`\.php$` 意思是「必须以 `.php` 结尾」。`.php5` 不在里面，所以落到静态文件那条路。

### 5. 改配置，让 `.php5` 执行

```bash
docker exec -i dvwa-dvwa-1 bash -c 'cat > /etc/apache2/conf-available/docker-php.conf' << 'EOF'
<FilesMatch \.php5?$>
  SetHandler application/x-httpd-php
</FilesMatch>
EOF
docker exec dvwa-dvwa-1 apache2ctl -k graceful
```

正则变成 `\.php5?$`（`5?` 表示 5 可有可无）→ `.php` 和 `.php5` 都命中。

访问 `shell.php5?c=working` → **`PWNED:working`**。

**这一条比任何教程都值钱**，因为走的是完整因果链：不执行 → 怀疑解析 → 读配置 → 找到规则 → 改规则 → 验证。

---

## 二、今天失败/卡住的地方

| # | 卡在哪 | 真正原因 | 下次怎么办 |
|---|---|---|---|
| 1 | 浏览器打不开 `127.0.0.1` | 用的是 **Windows 的 Edge**，`127.0.0.1` 指 Windows 自己 | 认准「Kali 里的浏览器」 |
| 2 | 端口全试错 | 80 / 8080 / 4280 三个混了 | 先 `docker compose ps` 看 `PORTS` |
| 3 | 浏览器拒绝连接，curl 却通 | 浏览器挂了系统代理 | `gsettings set org.gnome.system.proxy mode 'none'` |
| 4 | 命令报 `-d: command not found` | 反斜杠续行在粘贴时断了 | 多行命令写成 `.sh` 文件再 `bash` |
| 5 | 上传一直是 `not uploaded` | 浏览器文件选择框没真选中文件 | 选完看 `Browse` 旁边有没有文件名 |
| 6 | 文件在服务器上，浏览器却 404 | 浏览器缓存了之前的 404 | `Ctrl + Shift + R` 强刷 |
| 7 | `docker pull` 卡在 Waiting | 国内拉不动 Docker Hub | 配镜像加速器，或指定镜像源 |

---

## 三、今天提炼出的四条规律

**规律一：curl 通、浏览器不通 → 先查三样**
代理 → 端口 → IP 归属（是本机还是另一台机器）。

**规律二：上传失败，先去服务器上看文件在不在**

```bash
docker exec dvwa-dvwa-1 ls -l /var/www/html/hackable/uploads/
```

别猜，直接看。**文件在 = 上传成功但解析有问题；文件不在 = 上传这一步就没成。**

**规律三：看到 404 先别信，强制刷新一次**
浏览器缓存很容易制造假象。用 `curl -o /dev/null -w "%{http_code}"` 拿真实状态码。

**规律四：多行命令永远存成脚本**

```bash
cat > /tmp/x.sh << 'EOF'
...命令...
EOF
bash /tmp/x.sh
```

反斜杠续行在粘贴时太容易断。

---

## 四、今天还没搞懂、留到明天的

- `FilesMatch`、`SetHandler`、`AddHandler` 这三个词各是什么意思，为什么改的是 `FilesMatch` 而不是别的
- 正则 `\.php$` 里那个 `\.` 和 `$` 分别代表什么
- `apache2ctl -k graceful` 是干什么的
- `.phtml`、`.phar` 这些后缀，在别的环境里为什么有时能执行
- `curl -F` 和 `curl -d` 的区别
- 什么是「二次渲染」，为什么它是最强防护

这些明天专门消化。

---

## 五、明天的三行笔记（今天就记这个）

1. DVWA 的 Apache 配置是 `<FilesMatch \.php$>`，只认 `.php`。
2. `.php5` 能上传、能访问（200），但返回源码不执行。
3. 改成 `\.php5?$` 并 graceful 之后，`.php5` 执行成功，输出 `PWNED:working`。
