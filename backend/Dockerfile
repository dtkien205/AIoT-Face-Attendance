# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS wheels
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 CMAKE_BUILD_PARALLEL_LEVEL=2
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY backend/requirements.txt backend/requirements-recognition.txt ./
ARG INSTALL_RECOGNITION=true
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_RECOGNITION" = "true" ]; then \
      pip wheel --wheel-dir=/wheels -r requirements.txt -r requirements-recognition.txt; \
    else \
      pip wheel --wheel-dir=/wheels -r requirements.txt; \
    fi

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    ATTENDANCE_DATA_DIR=/app/var \
    DATABASE_URL=sqlite:////app/var/attendance.db
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid 10001 --create-home appuser \
    && mkdir -p /app/var /app/data /app/models \
    && chown appuser:appuser /app/var
RUN --mount=type=bind,from=wheels,source=/wheels,target=/wheels \
    pip install --no-cache-dir --no-index /wheels/*.whl
WORKDIR /app/backend
COPY --chown=appuser:appuser backend/app ./app
COPY --chown=appuser:appuser backend/seed.py backend/evaluate_pad.py backend/camera_bridge.py backend/docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
ENTRYPOINT ["/app/backend/docker-entrypoint.sh"]

FROM runtime AS test
USER root
RUN pip install --no-cache-dir httpx==0.28.1
COPY --chown=appuser:appuser backend/tests ./tests
USER appuser
ENTRYPOINT ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]

FROM runtime AS production
