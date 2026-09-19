FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apk add --no-cache ffmpeg font-noto-cjk

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

EXPOSE 8997
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8997"]
