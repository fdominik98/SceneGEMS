FROM node:20-bookworm

WORKDIR /app

COPY package.json package-lock.json ./
COPY website/package.json website/package-lock.json ./website/

RUN npm ci && npm ci --prefix website

COPY . .

COPY docker-entrypoint.sh /usr/local/bin/frontend-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/frontend-entrypoint.sh && chmod +x /usr/local/bin/frontend-entrypoint.sh

EXPOSE 5173

ENTRYPOINT ["/usr/local/bin/frontend-entrypoint.sh"]
