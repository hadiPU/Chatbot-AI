# Base image
FROM python:3.11-slim

# Metadata
LABEL maintainer="Anda <you@example.com>"
ENV PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.5.1

# Set working dir
WORKDIR /app

# install system deps required for some python packages and streamlit
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    ca-certificates \
    libglib2.0-0 \
    libnss3 \
    && rm -rf /var/lib/apt/lists/*

# copy requirements first (for better cache)
COPY requirements.txt /app/requirements.txt

# Install python deps
RUN pip install --upgrade pip setuptools wheel \
 && pip install -r /app/requirements.txt \
 && rm -rf /root/.cache/pip

# copy app files
COPY . /app

# Create a non-root user for safety (optional)
RUN useradd -m appuser || true
RUN chown -R appuser:appuser /app
USER appuser

# Expose Streamlit default port
EXPOSE 8501

# Default port env (can override via docker run / compose)
ENV PORT=8501

# Entrypoint: run streamlit headless on 0.0.0.0
ENTRYPOINT ["sh", "-c", "streamlit run chatbot_only.py --server.port $PORT --server.address 0.0.0.0 --server.headless true"]
