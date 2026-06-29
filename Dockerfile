FROM python:3.11-slim

WORKDIR /app

# ffmpeg — для видео-фабрики агента (/factory); fonts-dejavu — кириллический шрифт
# для субтитров. Нужно только агенту; казино-боту не мешает.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY casino ./casino
COPY agent ./agent
COPY run.py .

# На хостинге работаем в режиме webhook на тестовых монетах.
ENV WALLET_PROVIDER=faucet \
    USE_WEBHOOK=true \
    WEBAPP_ENABLED=true \
    WEBAPP_ALLOW_GUEST=true

CMD ["python", "run.py"]
