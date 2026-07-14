# Snapshot renderer image: the Playwright base ships the BROWSERS but
# (in some tags) not the Python package — bake it in, version-matched
# to the browser build in this base tag.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy
RUN pip install --no-cache-dir playwright==1.47.0
COPY render.py /render/render.py
CMD ["python", "/render/render.py"]
