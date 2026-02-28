# Pin op een specifieke patch versie voor reproduceerbare builds.
# Controleer regelmatig op https://hub.docker.com/_/python voor updates.
# Bij elke Python security patch: versienummer hier bijwerken + opnieuw builden.
FROM python:3.12.9-slim

WORKDIR /app

# Systeem dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies — upgrade pip zelf ook voor security fixes
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# App code + entrypoint (chmod als root, vóór USER switch)
COPY . .
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Non-root user voor security
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "--config", "/app/gunicorn.conf.py", "app:app"]
