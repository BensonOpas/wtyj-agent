FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Download gws CLI binary
RUN curl -L https://github.com/googleworkspace/cli/releases/download/v0.8.0/gws-x86_64-unknown-linux-gnu.tar.gz \
    | tar xz --strip-components=1 -C /usr/local/bin/ gws-x86_64-unknown-linux-gnu/gws && \
    chmod +x /usr/local/bin/gws

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY bluemarlin/ /app/

# Copy supervisord config
COPY supervisord.conf /etc/supervisord.conf

# Create directories for mounted volumes (defaults if not mounted)
RUN mkdir -p /app/config /app/data /app/logs

# Expose webhook server port
EXPOSE 8001

# Run supervisord
CMD ["supervisord", "-c", "/etc/supervisord.conf"]
