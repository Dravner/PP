FROM python:3.11-slim
RUN pip install --no-cache-dir "mcp==2.2.0" && useradd --uid 1000 --create-home agent
COPY server.py /app/server.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
USER agent
WORKDIR /work/repo
ENTRYPOINT ["python", "/app/server.py"]
