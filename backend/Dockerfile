FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m spacy download es_core_news_sm

COPY . .

EXPOSE ${KLASS_PORT:-8001}

CMD uvicorn app.main:app --host ${KLASS_HOST:-0.0.0.0} --port ${KLASS_PORT:-8001}
