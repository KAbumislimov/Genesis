FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir flask werkzeug requests
COPY . .
CMD ["python", "app.py"]
