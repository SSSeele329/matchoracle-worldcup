FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=5012

WORKDIR /app

RUN addgroup --system matchoracle \
    && adduser --system --ingroup matchoracle matchoracle \
    && mkdir -p /var/lib/matchoracle

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN chown -R matchoracle:matchoracle /app /var/lib/matchoracle

USER matchoracle

EXPOSE 5012

CMD ["gunicorn", "--bind", "0.0.0.0:5012", "--workers", "2", "--threads", "4", "--timeout", "60", "app:app"]
