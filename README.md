# SwingPro2

独立的视频管理代码基础，使用 FastAPI、PostgreSQL、Redis、Celery 和原生 HTML/CSS/JavaScript。

保留用户与角色权限、邀请码、常用打球人、微信绑定、视频上传及元数据处理、封面、机位筛选、收藏、主从视频播放、画线 JSON 保存与下载、批量下载和管理统计。视频所属用户与机位由业务操作维护。

不包含自动人物识别、自动分类、FuseNet 页面、识别标签 API、模型或识别结果导入。仓库只有功能代码和配置示例，不携带历史 Git 记录、服务器配置、业务数据、账号种子、日志或部署凭据。

## 本地运行

需要 Python 3.11、PostgreSQL 16、Redis 7，以及 PATH 中可用的 `ffmpeg` 和 `ffprobe`。使用独立本地数据库。

Apple Silicon 需可执行的 ARM 或通用版本媒体工具，可先运行 `ffmpeg -version`、`ffprobe -version` 检查。旧 Intel 工具在未安装 Rosetta 的机器上无法直接运行。

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`，填写自己的 `PG_PASSWORD`、随机 `JWT_SECRET`（至少32字符），按本地服务修改数据库及 Redis 地址。示例占位值不能启动。可用 `python -c 'import secrets; print(secrets.token_urlsafe(48))'` 生成 JWT 密钥。

已有 PostgreSQL 和 Redis 可直接使用；若通过 Docker 启动独立依赖，先运行 Docker，再执行：

```bash
docker compose --env-file .env -f examples/compose.example.yaml up -d
```

在项目根目录初始化空数据库，创建自己的管理账号。密码通过终端交互输入，没有默认账号。

```bash
python -m scripts.init_db
python -m scripts.create_admin --telephone YOUR_11_DIGIT_NUMBER
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

在另一终端激活同一虚拟环境，启动元数据任务 worker：

```bash
celery -A app.core.celery_app:celery_app worker --loglevel=info --pool=solo
```

macOS 开发使用 `solo`；无需 beat 或 GPU/识别 worker。单进程快速调试可在私有 `.env` 中设置 `CELERY_TASK_ALWAYS_EAGER=true`，同步执行元数据任务。

访问 [登录页](http://127.0.0.1:8000/users/login/)、[视频库](http://127.0.0.1:8000/platform.html)、[API文档](http://127.0.0.1:8000/docs) 或 [健康检查](http://127.0.0.1:8000/health)。Web 管理入口使用管理角色；普通用户 API 保留。

## 配置和存储

- `app/core/config.py` 仅读取根目录 `.env` 和进程环境，进程环境优先；全部字段见 `.env.example`。
- 相对存储路径按项目根目录解析，首次启动创建存储目录；存储、日志、虚拟环境和私有 `.env` 均被 Git 忽略。
- `SMS_PROVIDER=local` 仅供开发，在终端显示验证码，不发送真实短信。短信/微信需填写自己的应用凭据，默认未接入。
- `CORS_ORIGINS` 支持 JSON 数组或逗号分隔地址，同源开发使用空列表。
- `scripts/init_db.py` 用于新数据库；`scripts/init_access_control.py` 初始化权限策略。不附带历史迁移或业务回填脚本。

这是一份独立基础版本；上线前需要自己的媒体访问策略、部署配置和完整业务验收。示例不是生产部署。

保留的框架版本在本地静态媒体服务中返回完整文件（HTTP 200）；生产环境若需要 Range 分段读取，应配置支持该能力的媒体服务。

## 验证

```bash
python -m unittest discover -s tests -v
node --check web/platform.js
node --check web/player.js
node --check web/users/login/auth.js
```

测试使用本地临时配置，不连接远程数据库。维护记录见 `AGNETS.md`。
