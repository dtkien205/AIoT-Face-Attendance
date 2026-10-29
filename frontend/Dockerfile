# syntax=docker/dockerfile:1
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY index.html tsconfig*.json ./
COPY src ./src
# Empty URL means same-origin /api and /ws via Nginx; works from other LAN PCs.
ENV VITE_API_URL=""
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.28-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD wget -q --spider http://127.0.0.1:8080/ || exit 1
