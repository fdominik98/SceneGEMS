# Stage 1: Builder ==============================================================================

# Define python version
ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS builder

# Reactivate variables within each stage
ARG PYTHON_VERSION 

# Install necessary build tools and any additional dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    python3-dev \
    libffi-dev \
    ninja-build \
    cmake \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

# Set the working directory
WORKDIR /app

# Install additional dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Final Image ==========================================================================
FROM python:${PYTHON_VERSION}-slim

# Reactivate variables within each stage
ARG PYTHON_VERSION

# Install the necessary package for adding a non-root user
RUN apt-get update && apt-get install -y --no-install-recommends \
    passwd \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user and group
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy the application code
COPY app/. /app/

# Set the working directory
WORKDIR /app

# Copy installed dependencies from the builder stage
COPY --from=builder /usr/local/lib/python${PYTHON_VERSION}/site-packages /usr/local/lib/python${PYTHON_VERSION}/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Change ownership of the application directory to the non-root user
RUN chown -R appuser:appuser /app

# Switch to the non-root user
USER appuser

# Set the entrypoint or command
CMD ["python", "-B", "-u", "/app/main.py"]
