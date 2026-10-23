# CreatorHub 服务器部署（PM2）

这套配置面向已有 Nginx、Certbot 和 PM2 的 Linux 服务器。
应用固定监听 `127.0.0.1:18000`，不会占用常见的 `8000` 端口；域名由 Nginx 负责 HTTPS 和反向代理。

## 1. 安装与首次启动

```bash
sudo mkdir -p /opt/creatorhub
sudo chown -R "$USER":"$USER" /opt/creatorhub
git clone https://github.com/george-dccy/xuanti.git /opt/creatorhub
cd /opt/creatorhub

# Python 3.10+；首次执行会创建 .venv、安装依赖和 Patchright Chromium
python3 creatorhub.py install --skip-node
cp config.example.yaml config.yaml
```

2 核 2G 服务器建议先把 `config.yaml` 的运行规模调小：

```yaml
engine:
  worker_pool_size: 1
  scan_concurrency: 1
  max_live_contexts: 1
  active_accounts: 1
```

知乎和淘宝可以使用 Cookie 登录，适合没有桌面环境的服务器。需要二维码或人工处理验证页时，可先建立 SSH 隧道：

```bash
ssh -N -L 18000:127.0.0.1:18000 user@your-server
```

然后在本地浏览器打开 `http://127.0.0.1:18000`。Cookie、数据库、媒体和浏览器 Profile 都保存在服务器的 `data/` 目录，升级或迁移前需要备份它。

## 2. 用 PM2 托管

仓库已提供 `deploy/pm2/ecosystem.config.cjs`：

```bash
cd /opt/creatorhub
pm2 start deploy/pm2/ecosystem.config.cjs
pm2 save
pm2 startup
```

`pm2 startup` 会输出一条需要复制执行的系统启动命令。执行完成后再运行一次 `pm2 save`。

常用操作：

```bash
pm2 status
pm2 logs creatorhub
pm2 restart creatorhub
pm2 stop creatorhub
```

更新代码时：

```bash
cd /opt/creatorhub
git pull --ff-only
python3 creatorhub.py install --skip-node
pm2 restart creatorhub --update-env
pm2 save
```

## 3. 配置 Nginx 和域名

先确认：

```bash
dig +short xuanti.boluomi.ren
```

应返回服务器公网 IP。然后复制示例配置：

```bash
sudo cp deploy/nginx/xuanti.boluomi.ren.conf.example \
  /etc/nginx/sites-available/xuanti.boluomi.ren
sudo ln -s /etc/nginx/sites-available/xuanti.boluomi.ren \
  /etc/nginx/sites-enabled/xuanti.boluomi.ren
sudo nginx -t
sudo systemctl reload nginx
```

如果证书尚未存在，先按服务器现有 Certbot 流程申请：

```bash
sudo certbot --nginx -d xuanti.boluomi.ren
```

证书路径应为：

```text
/etc/letsencrypt/live/xuanti.boluomi.ren/fullchain.pem
/etc/letsencrypt/live/xuanti.boluomi.ren/privkey.pem
```

## 4. 公网安全边界

CreatorHub 当前是个人工作台，本身没有独立的 Web 登录鉴权。它会管理账号 Cookie、浏览器 Profile、下载文件以及部分平台写操作，不建议在未加保护时直接公开域名。

推荐至少启用 Nginx Basic Auth：

```bash
sudo apt install apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd-creatorhub your-admin-name
```

然后取消 Nginx 配置中 `auth_basic` 和 `auth_basic_user_file` 两行的注释，检查并重载：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

如果只自己使用，也可以不公开 DNS，通过 VPN 或 SSH 隧道访问。
