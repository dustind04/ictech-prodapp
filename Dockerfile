# icTech Services — production tooling for Immanuel Church.
# Python only. No Node. No webpack. Builds in ~60 seconds on a Pi.
FROM python:3.11-slim-bookworm

WORKDIR /usr/src/app

# Install Python deps first so they get cached separately from app code.
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy app code.
COPY app.py db.py ./
COPY migrations ./migrations
COPY templates ./templates
COPY static ./static

# Persistent data lives in /data, mounted from a volume on the host.
# The application creates this directory if missing.
ENV ICTECH_DB=/data/ictech.db
VOLUME ["/data"]

EXPOSE 8058

# Run via gunicorn in production. Two workers is plenty for a single-venue
# deployment; the app is I/O-bound on the Shure socket loops (which run as
# threads inside the worker, not as separate workers).
CMD ["gunicorn", "--workers", "1", "--threads", "4", \
     "--bind", "0.0.0.0:8058", \
     "--access-logfile", "-", \
     "app:app"]
