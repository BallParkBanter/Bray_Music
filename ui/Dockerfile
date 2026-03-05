FROM python:3.11-slim
WORKDIR /app

# Install font for Pillow cover art fallback
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7861
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7861"]
