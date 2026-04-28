FROM python:3.12-slim

WORKDIR /app

RUN groupadd --gid 1000 app && useradd --uid 1000 --gid 1000 --no-create-home app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY . .

RUN mkdir -p data && chown app:app data

VOLUME /app/data

USER app

EXPOSE 8123

CMD ["python", "app.py"]
