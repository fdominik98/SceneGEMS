# Use the latest NanoMQ image as the base
# FROM emqx/nanomq:latest
FROM emqx/nanomq:latest-slim

# Define the path for the configuration file inside the container
COPY nanomq.conf /etc/nanomq.conf

# Expose ports 1883 and 8883
EXPOSE 1883 8883

# # Start NanoMQ with the specified configuration
CMD ["nanomq", "start", "--conf", "/etc/nanomq.conf"]