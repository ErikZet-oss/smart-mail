# Smart Mail backend (API + worker share this image)
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# WeasyPrint runtime (Money-style print PDFs, DOCUMENTS_SPEC §4) + fonts
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
      fontconfig fonts-liberation curl \
 && rm -rf /var/lib/apt/lists/*
COPY templates/print/fonts/*.ttf /usr/share/fonts/truetype/liberation-narrow/
RUN fc-cache -f

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
ENV PATH="/srv/.venv/bin:$PATH"

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY templates ./templates

RUN useradd --system --uid 10001 smartmail && chown -R smartmail /srv
USER smartmail

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD curl -fsS http://localhost:8000/healthz || exit 1
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
