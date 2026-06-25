FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --retries 10 .

CMD ["uvicorn", "personal_agent.adapters.web.api:app", "--host", "0.0.0.0", "--port", "8000"]
