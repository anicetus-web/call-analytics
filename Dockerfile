FROM python:3.12-slim

# ffmpeg for audio conversion
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create temp dir for audio processing
RUN mkdir -p /tmp/call-analytics

EXPOSE 8000

# Default command runs the API. Override in docker-compose for migrate / worker.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
