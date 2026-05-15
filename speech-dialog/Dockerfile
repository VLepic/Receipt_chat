FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY speech-dialog/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY example/dialog.py /app/dialog.py
COPY example/static /app/static
COPY speech-dialog/app /app/app

EXPOSE 8888

CMD ["python", "-m", "app.main"]

