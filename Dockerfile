FROM python:3.12-slim
LABEL authors="KilianSen"
LABEL org.opencontainers.image.authors="KilianSen"
LABEL org.opencontainers.image.description="A OPCUA Discovery Service that generates Telegraf configuration"
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

#
COPY test/ /input/

# Copy application source
COPY . .

# Create input/output directories
RUN mkdir -p /input /output

# Set environment variables with defaults
ENV PYTHONUNBUFFERED=1 \
    TELEGRAF_CONFIG_PATH_IN="/input/telegraf.conf" \
    TELEGRAF_CONFIG_PATH_OUT="/output/telegraf.conf" \
    POLLING_INTERVAL="-1"

# Run the application
CMD ["python", "main.py"]