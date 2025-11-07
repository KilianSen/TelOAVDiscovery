FROM python:3.14-slim
LABEL authors="KilianSen"
LABEL org.opencontainers.image.source="https://https://github.com/KilianSen/TelOAVDiscovery"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY src/ ./src/

# Create input/output directories
RUN mkdir -p /input /output

# Set environment variables with defaults
ENV TELEGRAF_CONFIG_PATH_IN="/input/telegraf.conf" \
    TELEGRAF_CONFIG_PATH_OUT="/output/telegraf.conf" \
    POLLING_INTERVAL="-1" \
    PYTHONUNBUFFERED=1

# Run the application
ENTRYPOINT ["python", "src/main.py"]
