# ZiraHive's optional local AI helper (docker compose --profile ai). CPU by default.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ZIRAHIVE_AI_MODELS=/models HF_HOME=/models/hf
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY zirahive_ai.py .
EXPOSE 8001
CMD ["uvicorn", "zirahive_ai:app", "--host", "0.0.0.0", "--port", "8001"]
