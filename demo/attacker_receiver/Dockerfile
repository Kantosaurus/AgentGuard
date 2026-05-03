FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir flask==3.* gunicorn==22.*

COPY demo/attacker_receiver/app /app/app

EXPOSE 9090

CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:9090", "app:create_app()"]
