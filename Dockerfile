FROM python:3.9-slim

# Native build tools for curl_cffi + lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (Chromium only for scraping)
RUN playwright install chromium --with-deps

COPY . .

WORKDIR /app/sole

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=sole.settings

EXPOSE 8000

CMD ["gunicorn", "sole.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120"]
