FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Cloud Run sets $PORT; Vertex/BigQuery use the service account's ADC.
CMD exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT}
