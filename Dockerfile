FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY app /app/app

RUN pip install --no-cache-dir .
RUN python -m playwright install --with-deps chromium

EXPOSE 8000

CMD ["sh", "-c", "xvfb-run -a uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
