ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/app /app/app
COPY clients/python/keydesk_client.py /app/client_sdk/keydesk.py
COPY backend/alembic.ini /app/alembic.ini
COPY backend/migrations /app/migrations

EXPOSE 8000
CMD ["sh", "-c", "python -m app.preflight && alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
