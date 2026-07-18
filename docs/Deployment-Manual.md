# Manual Deployment (Remote Server)

This document describes a manual deployment workflow for the remote server.
It uses a "run scripts on the server" approach instead of a CI/CD pipeline.

It intentionally avoids hardcoding any public IPs, passwords, or secrets in the
repository. Replace placeholders locally.

## Assumptions

- The server already has Nginx installed and reachable over HTTPS.
- You can SSH into the server.
- You will run the application under a non-root user (recommended).

## 1) Clone The Repository

```bash
git clone <YOUR_GITHUB_REPO_URL>
cd rag-challenge
```

## 2) Create `.env` (Secrets Stay On The Server)

```bash
cp .env.example .env
```

Edit `.env` and set at least:

- `DEMO_USERNAME` / `DEMO_PASSWORD`
- `SESSION_SECRET`
- `OPENAI_API_KEY` (optional; required for LLM answers and vector retrieval)
- `SSH_HOST` (IP address or domain name of the server)

## 3) Install Dependencies

Recommended (Python venv):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 4) Fetch Evaluation Dataset (Optional But Recommended)

```bash
python3 scripts/fetch_eval_questions.py \
  --url "https://<SSH_HOST>:8443/questions.html" \
  --output data/evaluation_questions.csv \
  --insecure
```

## 5) Crawl And Build Index

Full-site crawl (recommended):

```bash
python3 scripts/crawl.py --full-site --limit 850
python3 scripts/build_index.py
```

## 6) Run The Service

Use systemd to run the FastAPI service as a background unit.

### 6.1) Create A systemd Unit

Create `/etc/systemd/system/thss-rag.service`:

```bash
sudo tee /etc/systemd/system/thss-rag.service >/dev/null <<'EOF'
[Unit]
Description=THSS RAG Chatbot (FastAPI)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/apps/thss-rag/backend/current
EnvironmentFile=/opt/apps/thss-rag/backend/current/.env
ExecStart=/opt/apps/thss-rag/backend/current/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
```

Adjust `WorkingDirectory` and the Python path to match your deployment layout.

### 6.2) Enable And Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable thss-rag
sudo systemctl start thss-rag
sudo systemctl status thss-rag --no-pager
```

To view logs:

```bash
sudo journalctl -u thss-rag -n 200 --no-pager
```

Then configure Nginx to route `/chat`, `/api`, and `/static` to the local service.

## 7) Configure Nginx

Your server already has Nginx configured. Update the existing `server { ... }`
block (the one that listens on `8443`) by adding the following `location`
snippets, then reload Nginx.

Add routes for the chat UI, API, and static assets:

```nginx
location = / {
    return 302 /chat;
}

location = /chat {
    proxy_pass http://127.0.0.1:8000/chat;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location ^~ /chat/ {
    proxy_pass http://127.0.0.1:8000/chat/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location ^~ /api/ {
    proxy_pass http://127.0.0.1:8000/api/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location ^~ /static/ {
    proxy_pass http://127.0.0.1:8000/static/;
    proxy_set_header Host $host;
}
```

If your server uses the default Ubuntu Nginx layout, the `8443` listener is often
defined in:

```text
/etc/nginx/sites-enabled/default
```

Reload Nginx after updating the config:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### Validate The Effect

- Browser:
  - `https://<SSH_HOST>:8443/` redirects to `/chat`
  - `https://<SSH_HOST>:8443/chat` loads the chat UI
  - `https://<SSH_HOST>:8443/api/health` returns `{"status": "ok", ...}`
- Command line (use `-k` for self-signed certificates):

```bash
curl -k -I "https://<SSH_HOST>:8443/" | head -n 5
curl -k "https://<SSH_HOST>:8443/api/health"
```

Notes:

- The chat UI is exposed at `https://<SSH_HOST>:8443/chat`.
- If you put Nginx in front of a streaming endpoint in the future, you may need
  `proxy_buffering off` for that location.

## Notes

- Do not commit anything under `data/` to the public repository.
- If you run multiple worker processes, the demo session cookie (in-memory) is not shared across workers.
