# 部署与评测（Deploy）

本目录提供若干可执行脚本，用于在服务器上完成环境初始化、爬取建索引、服务端配置、评测集抓取与评测执行。

## 0. 前置条件

- 已完成仓库克隆，并位于仓库根目录（例如 `/home/ubuntu/rag-challenge`）
- 服务器已安装 Python 3（建议 3.10）
- 服务器网络允许访问目标站点与（可选）OpenAI
- Nginx 已存在并监听 `8443`（如需对外提供 HTTPS 入口）

## 1. 创建 `.env`

在仓库根目录执行：

```bash
cp .env.example .env
```

至少需要设置：

- `DEMO_USERNAME` / `DEMO_PASSWORD`
- `SESSION_SECRET`
- `SSH_HOST`（用于评测集抓取时拼接 `https://<SSH_HOST>:8443/questions.html`，也用于本地一键部署的 SSH 连接）
- `OPENAI_API_KEY`（可选；仅在向量检索或 LLM 生成开启时需要）

注意：`.env` 不应提交到 Git。

## 2. 部署

部署分为三个脚本，建议按顺序依次执行。

### 2.1 初始化应用环境（setup_app.sh）

在仓库根目录执行：

```bash
chmod +x deploy/setup_app.sh
./deploy/setup_app.sh
```

脚本行为：

- 创建 `.venv` 并安装 `requirements.txt`

### 2.2 全站爬取与建索引（crawl_and_build_index.sh）

在仓库根目录执行：

```bash
chmod +x deploy/crawl_and_build_index.sh
./deploy/crawl_and_build_index.sh
```

常用参数（环境变量）：

- 仅试跑 1 页（验证链路）：`CRAWL_LIMIT=1`
- 跳过全站爬取：`CRAWL_FULL_SITE=0`
- 设置礼貌限速（秒/请求）：`CRAWL_RATE_LIMIT=0.75`
- 指定 SQLite 数据库路径：`DATABASE_PATH=/path/to/rag.sqlite3`
- 指定索引输出目录：`INDEX_DIR=/path/to/index`
- 构建向量索引：`BUILD_VECTOR_INDEX=1`（需要 `OPENAI_API_KEY`）

### 2.3 生成/安装 systemd 与生成 Nginx 片段（configure_server.sh）

在仓库根目录执行：

```bash
chmod +x deploy/configure_server.sh
./deploy/configure_server.sh
```

脚本会生成：

- `deploy/generated/<SERVICE_NAME>.service`
- `deploy/generated/nginx-<SERVICE_NAME>.conf.snippet`

在 Linux/systemd 环境下，若 `INSTALL_SYSTEMD=1`，会自动执行安装与启动；否则只生成预览文件。

将 Nginx 片段合并到你现有的 `8443` 的 `server { ... }` 块中，然后执行：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

常用参数（环境变量）：

- 不安装 systemd（只生成预览）：`INSTALL_SYSTEMD=0`
- 不生成 Nginx 片段：`WRITE_NGINX_SNIPPET=0`

示例（只做最小可执行性验证）：

```bash
./deploy/setup_app.sh
CRAWL_LIMIT=1 ./deploy/crawl_and_build_index.sh
INSTALL_SYSTEMD=0 WRITE_NGINX_SNIPPET=0 ./deploy/configure_server.sh
```

### 2.4 （可选）使用 Docker + Volume 持久化数据到宿主机

如果你希望爬虫数据库与索引不落在仓库目录下，可以使用 Docker 的 named volume 持久化到宿主机（Docker 管理的 volume 路径）。

本仓库提供一个 compose override 文件 `deploy/docker-compose.data.yml`，它会：

- 将数据存放在容器内 `/data`
- 将 `/data` 绑定到 named volume：`rag_data`
- 设置 `DATABASE_PATH=/data/rag.sqlite3`、`INDEX_DIR=/data/index`

启动服务（对外 8000）：

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.data.yml up -d --build
```

在容器内执行全站爬取 + 建索引（数据落在 volume 里）：

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.data.yml run --rm rag-app \
  bash -lc 'python scripts/crawl.py --full-site --limit 850 --rate-limit 0.75 --database "$DATABASE_PATH" && python scripts/build_index.py --database "$DATABASE_PATH" --index-dir "$INDEX_DIR"'
```

### 2.5 （可选）本地一键部署到远端并重启服务

如果你希望把本地工作区（未提交改动也会同步）一键发布到远端服务器，并重启 systemd 服务，可以使用 `deploy/deploy_to_server.sh`。

脚本会：

- 使用 `rsync` 将本地代码同步到远端目录（默认排除 `.git/`、`.venv/`、`data/`、`.env` 等）
- 在远端创建/更新虚拟环境并安装依赖（可开关）
- `sudo systemctl restart <service>` 重启服务（可开关）

示例：

```bash
chmod +x deploy/deploy_to_server.sh

SSH_HOST=<YOUR_SERVER_HOST> \
SSH_USER=ubuntu \
./deploy/deploy_to_server.sh
```

常用参数（环境变量）：

- SSH：`SSH_HOST`（必填）、`SSH_USER`、`SSH_PORT`、`SSH_KEY_PATH`
- 远端路径：`REMOTE_DIR`、`REMOTE_VENV_DIR`
- 服务：`REMOTE_SERVICE_NAME`
- 行为开关：`REMOTE_PIP_INSTALL=0`、`REMOTE_SYSTEMD_RESTART=0`、`RSYNC_DELETE=1`

默认值说明：

- 若未指定 `REMOTE_DIR`/`REMOTE_SERVICE_NAME`，脚本会优先从 `docs/Deployment-Manual.md` 的示例配置中自动推断；推断失败时再使用内置默认值。

## 3. 抓取评测集（questions.html -> CSV）

在仓库根目录执行：

```bash
chmod +x deploy/fetch_eval_dataset.sh
./deploy/fetch_eval_dataset.sh
```

默认会：

- 下载 `https://<SSH_HOST>:8443/questions.html` 到 `data/evaluation_questions.html`
- 解析本地 HTML 并生成 `data/evaluation_questions.csv`

可选参数：

- 指定完整 URL：`EVAL_URL="https://xxx:8443/questions.html"`
- 指定输出路径：`EVAL_HTML_PATH=...`、`EVAL_CSV_PATH=...`

## 4. 运行评测（生成报告）

在仓库根目录执行：

```bash
chmod +x deploy/run_evaluation.sh
./deploy/run_evaluation.sh
```

默认配置：

- `EVAL_METHOD=pipeline`（在进程内直接跑 RAG pipeline）
- `EVAL_LIMIT=50`
- `EVAL_NO_LLM=1`（只评测检索命中与 citation，不调用 OpenAI 生成）
- 输出目录：`data/eval/`

常用参数：

- 跑全量：`EVAL_LIMIT=0`
- 开启向量检索：`EVAL_USE_VECTOR=1`（需要向量索引文件 + `OPENAI_API_KEY`）
- 走 HTTP 模式评测线上服务：
  - `EVAL_METHOD=http`
  - `EVAL_API_URL="https://<SSH_HOST>:8443/api/chat"`（或内网 `http://127.0.0.1:8000/api/chat`）

## 注意事项

- 合规爬取：遵守 `robots.txt`、保持礼貌限速、设置合适的 User-Agent。
- 数据不入库：`data/` 下的数据库、索引、评测产物不应提交到公开仓库。
- 密钥不入库：`OPENAI_API_KEY`、服务器登录信息等不得提交到 Git。
- 评测集抓取失败：优先使用 `curl -k -L <url> | head` 确认实际返回的是题库页而不是 `/chat` 或默认页。
