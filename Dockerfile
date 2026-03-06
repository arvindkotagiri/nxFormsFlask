FROM python:3.11-slim

WORKDIR /app

# Install system dependencies needed for psycopg2 + cryptography
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5050

# CMD ["gunicorn", "--bind", "0.0.0.0:5050", "main:app"]
CMD ["gunicorn", "main:app", \
"--bind", "0.0.0.0:5050", \
"--timeout", "180", \
"--workers", "3", \
"--worker-class", "gevent"]