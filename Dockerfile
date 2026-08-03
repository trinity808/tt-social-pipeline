FROM python:3.12-slim

WORKDIR /app

# Install dependencies first, separately from copying the app code --
# Docker caches this layer, so code-only changes don't trigger a full
# dependency reinstall on every rebuild.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run sets $PORT at runtime -- gunicorn has to bind to whatever that
# actually is, never a hardcoded port. --workers 1: Cloud Run scales by
# adding container instances, not by running multiple worker processes
# inside one -- one worker per container is the correct pattern here, not
# a resource-saving compromise. --threads 8: this workload is I/O-bound
# (waiting on LLM/API calls, not doing heavy computation), so threads
# handle concurrency within that one worker fine. --timeout 0: disables
# gunicorn's own worker timeout entirely -- its default (30s) would kill
# a run mid-pipeline long before a real multi-step LLM run finishes. Cloud
# Run's own --timeout flag (set at deploy time) is the real timeout that
# should apply here, not gunicorn's.
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app