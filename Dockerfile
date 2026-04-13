# Stage 1: Build dependencies
FROM python:3.11-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y gcc libpq-dev build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# Stage 2: Final image
FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .
EXPOSE 5050
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:5050", "--timeout", "180", "--workers", "3", "--worker-class", "gevent"]