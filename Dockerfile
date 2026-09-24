FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The Compose bind mount uses the host file, which may not be executable.
ENTRYPOINT ["sh", "/app/entrypoint.sh"]
CMD ["tail", "-f", "/dev/null"]
