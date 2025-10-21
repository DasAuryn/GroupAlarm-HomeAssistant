ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache python3 py3-pip curl jq ca-certificates

RUN pip install --no-cache-dir --break-system-packages \
    flask==3.* gunicorn==21.* \
    requests==2.* zeroconf paho-mqtt==1.6.1

COPY run.py /run.py
COPY run_state.py /run_state.py
COPY web /web
COPY run.sh /run.sh
RUN chmod 755 /run.sh

ENTRYPOINT []
CMD ["/run.sh"]
