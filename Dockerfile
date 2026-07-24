FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY geracao/ ./geracao/
COPY static/ ./static/

ENV PYTHONPATH=/app/geracao

EXPOSE 8000

CMD ["uvicorn", "geracao.api:app", "--host", "0.0.0.0", "--port", "8000"]
