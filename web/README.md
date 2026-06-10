# Archer Site

Archer 官网静态站点维护目录（已并入主仓库 `Archer/web/`，不再使用独立 git 子仓库）。

## Status

- Production: https://www.yivxer.com
- Server alias: `archer`
- Web root: `/var/www/archer/`
- Nginx config: `/etc/nginx/conf.d/archer.conf`
- SSL: Let's Encrypt / Certbot

## Pages

| File | URL | Purpose |
|---|---|---|
| `public/index.html` | `/` | 首页 |
| `public/archer.html` | `/archer.html` | Archer 入口原型：十问建档 + 首次回应 |
| `public/soul.html` | `/soul.html` | 灵魂四层模型 |
| `public/login.html` | `/login.html` | Magic Link 登录 / 注册 |
| `public/auth.html` | `/auth.html` | 登录回调与 Token 复制 |
| `public/privacy.html` | `/privacy.html` | 隐私政策 |
| `public/terms.html` | `/terms.html` | 用户协议 |

## Workflow

1. Pull or copy the latest production files into `public/`.
2. Preview changes locally.
3. Run `./deploy.sh`.
4. Check all production URLs after deployment.

## Rules

- Do not store server passwords in this repo.
- Use `ssh archer` and SSH key authentication.
- Back up production before each deploy.
- Run `nginx -t` before reloading Nginx.
