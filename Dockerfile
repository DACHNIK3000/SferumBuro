FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sferum_buro_bot.py .
COPY russian_trusted_root_ca_pem.crt .
COPY webapp/ webapp/

RUN useradd -m botuser && chown -R botuser:botuser /app
USER botuser

EXPOSE 8080

CMD ["python", "sferum_buro_bot.py"]
