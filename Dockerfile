FROM python:3.11-slim

WORKDIR /app

# 系統工具 + supervisord（同時跑 2 個 service）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Python 依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 程式碼
COPY . .

# 資料目錄（/data 是 Fly volume mount 點，重啟不遺失）
RUN mkdir -p /data /app/data /app/data/logs

# supervisord 設定：同時跑 Streamlit (8501) + Tracking (8503)
COPY supervisord.conf /etc/supervisor/conf.d/leadflow.conf

# DB 放 persistent volume
ENV DB_PATH=/data/leads.db
ENV PYTHONUNBUFFERED=1
ENV AUTH_ENABLED=true

EXPOSE 8501 8503

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
