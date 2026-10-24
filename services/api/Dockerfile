# InkLoom backend (services/api) with the verification engine (services/verification).
# Build from the REPOSITORY ROOT, so both services are in the context:
#   docker build -f services/api/Dockerfile -t inkloom-api .
# Secrets (DATABASE_URL, AUTH_SECRET_KEY, provider keys) are set in the host's environment at run
# time - never baked in: the root .dockerignore keeps every .env file out of the image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ENVIRONMENT=production \
    PORT=8000

WORKDIR /app
COPY services/verification /app/services/verification
COPY services/api /app/services/api

WORKDIR /app/services/api
# Exact tested versions (constraints.txt; CI installs the same on Python 3.12). Editable, so the
# engine finds its prompts and its labelled evaluation dataset next to its source.
RUN python -m pip install -e . -e ../verification -c constraints.txt \
 && useradd --create-home --uid 10001 app \
 && mkdir -p var/brand_sources \
 && chown -R app /app/services/api/var

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=4)"

# Migrations, then ONE worker (the review rate limiter is in memory, per process).
CMD ["sh", "scripts/start.sh"]
