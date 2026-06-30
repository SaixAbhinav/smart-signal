# SmartSignal live dashboard — FastAPI + SUMO (via the eclipse-sumo pip wheel).
# SUMO ships inside the wheel, so no apt SUMO install is needed; we only add the
# shared libraries the headless `sumo` binary links against.
FROM python:3.12-slim-bookworm

# Runtime libs for the eclipse-sumo wheel's headless `sumo` binary.
# If a deploy log shows "error while loading shared libraries: libXXX.so", add it here.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxerces-c3.2 \
    libgl1 \
    libgomp1 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    libsm6 \
    libatomic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render / Railway inject $PORT; default 8000 for local `docker run`.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn dashboard.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
