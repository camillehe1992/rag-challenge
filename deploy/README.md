# 部署与评测（Deploy）

本目录提供三个可执行脚本，用于在服务器上完成部署、评测集抓取与评测执行。

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
- `SERVER_HOST`（用于评测集抓取时拼接 `https://<SERVER_HOST>:8443/questions.html`）
- `OPENAI_API_KEY`（可选；仅在向量检索或 LLM 生成开启时需要）

注意：`.env` 不应提交到 Git。

## 2. 部署（爬取 + 建索引 + 生成 systemd/Nginx 片段）

在仓库根目录执行：

```bash
chmod +x deploy/deploy.sh
./deploy/deploy.sh
```

脚本行为：

- 创建 `.venv` 并安装 `requirements.txt`
- 全站爬取（默认 `--limit 850`）
- 构建索引（默认仅 BM25）
- 生成 `systemd` unit 预览文件与 Nginx 反代片段（写入 `deploy/generated/`）

常用可选参数（通过环境变量控制）：

- 仅试跑 1 页（验证链路）：`CRAWL_LIMIT=1`
- 跳过全站爬取：`CRAWL_FULL_SITE=0`
- 构建向量索引：`BUILD_VECTOR_INDEX=1`（需要 `OPENAI_API_KEY`）
- 不安装 systemd（只生成预览）：`INSTALL_SYSTEMD=0`
- 不生成 Nginx 片段：`WRITE_NGINX_SNIPPET=0`

示例（只做最小可执行性验证）：

```bash
INSTALL_SYSTEMD=0 WRITE_NGINX_SNIPPET=0 CRAWL_LIMIT=1 ./deploy/deploy.sh
```

### 2.1 systemd

脚本会生成：

- `deploy/generated/<SERVICE_NAME>.service`

在 Linux/systemd 环境下，若 `INSTALL_SYSTEMD=1`，会自动执行安装与启动；否则只生成预览文件。

### 2.2 Nginx

脚本会生成：

- `deploy/generated/nginx-<SERVICE_NAME>.conf.snippet`

将该片段合并到你现有的 `8443` 的 `server { ... }` 块中，然后执行：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 3. 抓取评测集（questions.html -> CSV）

在仓库根目录执行：

```bash
chmod +x deploy/fetch_eval_dataset.sh
./deploy/fetch_eval_dataset.sh
```

默认会：

- 下载 `https://<SERVER_HOST>:8443/questions.html` 到 `data/evaluation_questions.html`
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
  - `EVAL_API_URL="https://<SERVER_HOST>:8443/api/chat"`（或内网 `http://127.0.0.1:8000/api/chat`）

## 注意事项

- 合规爬取：遵守 `robots.txt`、保持礼貌限速、设置合适的 User-Agent。
- 数据不入库：`data/` 下的数据库、索引、评测产物不应提交到公开仓库。
- 密钥不入库：`OPENAI_API_KEY`、服务器登录信息等不得提交到 Git。
- 评测集抓取失败：优先使用 `curl -k -L <url> | head` 确认实际返回的是题库页而不是 `/chat` 或默认页。
