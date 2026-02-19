FROM python:3.13-slim

WORKDIR /app

# Install build dependencies if needed (e.g. for aiohttp/sqlalchemy optimizations)
# RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway will provide PORT, but we expose default 8080
EXPOSE 8080

CMD ["python", "main.py"]
