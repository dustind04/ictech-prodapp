# NDI → MJPEG bridge for dashboards (see bridge.py). The ndi-python
# wheel bundles the NDI runtime for x86_64 and aarch64 (Pi 5).
# NDI® is a registered trademark of Vizrt NDI AB; the runtime is used
# under the NDI license terms (ndi.video).
FROM python:3.11-slim-bookworm
WORKDIR /usr/src/ndi
RUN pip3 install --no-cache-dir ndi-python==6.3.2.6 numpy pillow
COPY bridge.py .
EXPOSE 8060
CMD ["python3", "-u", "bridge.py"]
