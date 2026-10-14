FROM python:3.12-slim
RUN pip install --no-cache-dir kafka-python-ng==2.2.2 psycopg2-binary
WORKDIR /gw
COPY main.py .
ENV GW_PORT=8411 KAFKA_BOOTSTRAP=kafka:9092
EXPOSE 8411
CMD ["python", "-u", "main.py"]
