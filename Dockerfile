FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY casino ./casino
COPY run.py .

# На хостинге работаем в режиме webhook на тестовых монетах.
ENV WALLET_PROVIDER=faucet \
    USE_WEBHOOK=true \
    WEBAPP_ENABLED=true \
    WEBAPP_ALLOW_GUEST=true

CMD ["python", "run.py"]
