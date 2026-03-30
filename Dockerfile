FROM python:3.12-slim

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY app.py freshrss_client.py scorer.py db.py ./
COPY templates/ templates/

RUN mkdir -p data && chown app:app data

VOLUME /app/data

USER app

EXPOSE 8123

CMD ["python", "app.py"]
