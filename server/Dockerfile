# Server container image (optional alternative when you do not want to install a systemd service)
# Build: docker build -t send-ip .
# Run:   docker run -d --name send-ip -p 127.0.0.1:8000:8000 \
#          -e APP_TOKEN=your-token -v sendip-data:/data send-ip

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/ips.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates ./templates

RUN mkdir -p /data && useradd -r -u 10001 sendip && chown -R sendip:sendip /app /data
USER sendip

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"

CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:8000", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
