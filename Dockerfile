FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY frontend/ ./frontend/
ENV GO2RTC_CONFIG=/app/data/go2rtc.yaml
EXPOSE 8000
CMD ["python", "backend/app.py"]
