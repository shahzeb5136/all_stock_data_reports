FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # The report scripts print emoji; without this their output can raise
    # UnicodeEncodeError when stdout is a pipe rather than a terminal.
    PYTHONIOENCODING=utf-8 \
    # Lets `python -m api.build_pack` resolve `config` and `downloader`.
    PYTHONPATH=/app \
    # matplotlib needs a writable config dir; /root may be read-only.
    MPLCONFIGDIR=/tmp/matplotlib \
    # Defaults matching the Railway volume mount. Override in the dashboard.
    DATA_DIR=/data \
    STOCK_CSV_PATH=/data/stock_prices.csv

WORKDIR /app

# Dependencies first so code edits do not invalidate the install layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data /tmp/matplotlib

EXPOSE 8000

# Railway injects PORT; the default keeps `docker run` working locally.
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
