FROM python:3.8

WORKDIR /app

COPY src /app/src
COPY config/config.yaml /app/config/config.yaml
COPY requirements.txt /app/requirements.txt

RUN pip3 install --no-cache-dir --upgrade pip
RUN pip3 install --trusted-host pypi.python.org -r requirements.txt

CMD ["python3", "/app/src/main.py"]
