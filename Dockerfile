FROM python:3.12-alpine

LABEL org.opencontainers.image.authors="Rostyslav Fridman <rostyslav.fridman@gmail.com>"
LABEL org.opencontainers.image.description="An implementation of a Prometheus exporter for Yasno"
LABEL org.opencontainers.image.source=https://github.com/frostyslav/yasno-exporter
LABEL org.opencontainers.image.licenses=GPL-3.0

RUN apk update && apk add py3-pip

ADD requirements.txt /requirements.txt
RUN pip install -r /requirements.txt

ADD yasno_exporter.py /yasno_exporter.py

CMD [ "python", "/yasno_exporter.py" ]
