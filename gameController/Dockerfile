FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN pip install --no-cache-dir paho-mqtt==2.1.0 psycopg2-binary==2.9.13

COPY . .

USER 10001:10001
STOPSIGNAL SIGINT
CMD ["python", "main.py"]
