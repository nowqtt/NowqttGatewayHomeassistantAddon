FROM python:3.8

WORKDIR /app

COPY requirements.txt ./

RUN pip3 install --no-cache-dir --upgrade pip
RUN pip3 install --trusted-host pypi.python.org -r requirements.txt

COPY src src
COPY run.sh ./

RUN chmod a+x run.sh

CMD [ "python3", "/app/src/main.py" ]