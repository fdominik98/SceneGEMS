# NanoMQ 0.25.6, pinned by digest.
FROM emqx/nanomq:0.25.6-slim@sha256:f42285e8936e5c08cde7a3430aab5face26a3bf707bf5eff05f1e1131d0ff22e

# Plain MQTT, anonymous: the master's cluster broker (deploy/master/docker-compose.yml), open to
# the VPN, which master and nodes trust.
COPY nanomq.conf /etc/nanomq.conf

EXPOSE 1883 8883

CMD ["nanomq", "start", "--conf", "/etc/nanomq.conf"]
