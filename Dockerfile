FROM python:3.13-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY valyu_mcp/ valyu_mcp/

# Default port
ENV FASTMCP_HOST=0.0.0.0
ENV FASTMCP_PORT=8012
EXPOSE 8012

CMD ["uv", "run", "python", "-m", "valyu_mcp"]
