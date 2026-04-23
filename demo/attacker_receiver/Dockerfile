FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir flask

COPY app.py /app/app.py

EXPOSE 9090

CMD ["python", "-m", "flask", "--app", "app", "run", "--host=0.0.0.0", "--port=9090"]
