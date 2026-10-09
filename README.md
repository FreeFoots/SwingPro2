# SwingPro - 高尔夫挥杆分析平台

SwingPro 是一个专注于高尔夫挥杆分析的综合平台，提供用户管理、视频上传与处理等功能。本项目包含高性能的后端 API 服务以及基础的 Web 前端管理界面。

## 🎯 核心功能

- **用户系统**
  - 多角色支持：普通用户、管理员等
  - 完整的认证流程：密码登录、验证码登录、Token 刷新。
  - 邀请码注册机制。
- **视频管理**
  - 视频上传、存储与元数据管理。
  - 自动提取缩略图与视频分析结果。
  - 连接微信生态：支持绑定微信
- **球员管理 (Players)**
  - 系统用户可管理“常用打球人”。
  - 绑定微信用户信息，支持多对多关系。
- **后台管理**
  - 完善的权限控制系统。
  - 业务行为审计日志 。
  - 系统资源与业务数据统计大屏接口。

## 🛠 技术栈

### 后端
- **框架**: [FastAPI](https://fastapi.tiangolo.com/) - 高性能 Python Web 框架
- **数据库**: PostgreSQL (驱动: psycopg2-binary, ORM: SQLAlchemy 2.0)
- **任务队列**: Celery + Redis - 处理视频分析等耗时任务
- **认证**: OAuth2 + JWT (python-jose, passlib)

### 前端
- 原生 HTML/CSS/JavaScript
- 位于 `web/` 目录，通过后端静态资源挂载服务

### 其他配置
- **Nginx**: 反向代理 (配置在 `reverse-proxy/`)
- **Docker** (推荐用于部署数据库和 Redis)

## 📂 项目结构

```text
SwingPro/
├── app/                    # 核心后端代码
│   ├── api/                # API 路由定义 (Endpoint)
│   ├── core/               # 核心配置 (Config, Security, Logging)
│   ├── db/                 # 数据库模型与会话管理
│   ├── schemas/            # Pydantic 数据验证模型
│   ├── services/           # 复杂业务逻辑层
│   └── main.py             # 应用入口
├── web/                    # 前端静态资源
├── scripts/                # 运维与初始化脚本
├── docs/                   # 项目文档
├── files/ & video/         # 媒体文件存储目录
└── requirements.txt        # Python 依赖清单
```

## 🚀 快速开始指南

### 1. 环境准备
确保本地安装 Python 3.10+、PostgreSQL 和 Redis。
```bash
conda create -n swingpro python=3.11 -y
conda activate swingpro
```
安装PostgreSQL与redis并将其启动，版本要求如下：
(PostgreSQL) 16.13
Redis server v=7.0.15+

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置环境
创建新数据库：
```sql
CREATE DATABASE swingpro_db;
```
项目使用 `app/core/config.py` 管理配置，建议创建 `.env` 文件或设置环境变量来配置数据库连接，请注意修改路径配置：
```bash
# 示例配置
# PostgreSQL
export PG_HOST=localhost
export PG_PORT=5432
export PG_USER=postgres
export PG_PASSWORD=yourpassword
export PG_DB=swingpro_db
export REDIS_URL=redis://localhost:6379/0
# Redis（可为空；为空则自动用内存存 OTP）
REDIS_URL=redis://localhost:6379/1
# Celery 任务队列（NEW）
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/1
CELERY_DEFAULT_QUEUE=swingpro
CELERY_TIMEZONE=Asia/Shanghai
CELERY_TASK_ALWAYS_EAGER=True  # 设置 True 时可在本地同步执行任务（调试用）
# 存储目录配置（统一放在 files 目录下）
VIDEO_ROOT=/Users/swh/PythonProjects/SwingPro/files/video
THUMB_ROOT=/Users/swh/PythonProjects/SwingPro/files/thumbs
VIDEO_TMP_ROOT=/Users/swh/PythonProjects/SwingPro/files/tmp
# 日志配置
LOG_LEVEL=INFO
LOG_DIR=/Users/swh/PythonProjects/SwingPro/logs
LOG_JSON_FORMAT=True
```

### 4. 初始化数据库
使用提供的脚本初始化表结构并导入基础数据：
```bash
python -m scripts.init_db
```

*注：可通过 `python -m scripts.seed_users` 创建测试系统管理员用户。（目前版本的角色有user、business、admin、super_admin、system_admin）*

### 5. 启动服务

**启动 Web 服务器**
```bash
# 开发模式
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
# 生产模式（使用 Gunicorn）
gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app --bind 127.0.0.1:8000
```

**启动 Celery Worker (用于处理视频任务)**
```bash
celery -A app.core.celery_app worker --loglevel=info
```

本地使用 http://127.0.0.1:8000/docs 访问 Swagger UI 进行 API 测试。
本地使用 http://127.0.0.1:8000/platform.html 或 http://127.0.0.1:8000/users/login/index.html 访问用户登录页面。

## 📝 开发指南

- **API 文档**: 启动服务后访问 `http://localhost:8000/docs` 查看 Swagger UI。
- **代码规范**: 请遵循 PEP 8 规范，业务逻辑尽量下沉至 `app/services/` 层，保持 API 层轻量。
- **数据库迁移**: 修改模型后，请确保同步更新数据库 Schema
- **日志**: 使用 `app/core/logging.py` 定义的日志系统，日志文件存储在 `logs/` 目录。
- **错误处理**: 统一使用 FastAPI 的异常处理机制，确保 API 返回一致的错误格式。

## 📂 文件存储
- 视频文件存储在 `files/video/` 目录。
- 缩略图存储在 `files/thumbs/` 目录。
- 临时文件存储在 `files/tmp/` 目录。
请注意修改env文件中的路径配置以适应您的环境，并确保这些目录存在并具有适当的读写权限。
请确保这些目录存在并具有适当的读写权限。
