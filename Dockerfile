FROM python:3.12-slim
WORKDIR /app
COPY . .
ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/data
CMD ["python", "bot.py"]
