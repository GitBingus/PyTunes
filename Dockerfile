# Use slim Python base for a small dev image
FROM python:3.12-slim

# Create a non-root user to match host UID later if desired
ARG USER=dev
ARG UID=1000
RUN adduser --disabled-password --gecos "" --uid ${UID} ${USER}

WORKDIR /PyTunes

# Install build deps (if you need them) and common tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential git curl && \
    rm -rf /var/lib/apt/lists/*

# Copy only dependency files first for caching (adjust for your project)

# Switch to non-root user
USER ${USER}

# Default command for dev (override in docker-compose)
CMD ["python", "gui.py"]
