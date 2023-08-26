FROM python:3.8

WORKDIR /app

COPY src /app/src
COPY requirements.txt /app/requirements.txt
COPY run.sh /app/

RUN chmod a+x /app/run.sh

RUN pip3 install --no-cache-dir --upgrade pip
RUN pip3 install --trusted-host pypi.python.org -r requirements.txt

CMD [ "/app/run.sh" ]