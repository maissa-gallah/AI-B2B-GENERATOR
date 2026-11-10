FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for lxml and building wheels if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy project dependency definitions
COPY pyproject.toml ./

# Install dependencies into system/venv
RUN uv sync --no-install-project

# Copy application source and configuration
COPY config/ ./config/
COPY src/ ./src/
COPY tests/ ./tests/
COPY data/ ./data/
COPY README.md ./

RUN uv sync

ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["uv", "run", "python", "-m", "src.main", "--help"]
