# ---- Build Stage ----
FROM python:3.12-slim AS builder

WORKDIR /build
COPY . .
RUN pip install --no-cache-dir build \
    && python -m build --wheel \
    && ls -la dist/

# ---- Runtime Stage ----
FROM python:3.12-slim

# Security: non-root user
RUN groupadd -r drugpipeline && useradd -r -g drugpipeline drugpipeline

# Tini for proper signal handling
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

# Install the wheel (with HTTP deps for Smithery)
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl[httpx] && rm -rf /tmp/*.whl

# Clean up pip cache
RUN pip cache purge || true

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8081/', timeout=5)" || exit 1

USER drugpipeline
EXPOSE 8081

LABEL org.opencontainers.image.title="drug-pipeline-mcp" \
      org.opencontainers.image.description="Pharmaceutical R&D Pipeline Intelligence MCP Server" \
      org.opencontainers.image.source="https://github.com/DasClown/drug-pipeline-mcp" \
      org.opencontainers.image.licenses="MIT"

ENTRYPOINT ["tini", "--", "drug-pipeline", "--http", "--port", "8081"]
