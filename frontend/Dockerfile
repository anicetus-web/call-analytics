# ── Build stage ───────────────────────────────────────────────────────────────
FROM node:22-alpine AS build
WORKDIR /app
# Copy manifests first for layer caching.
# package-lock.json MUST be committed to the repo for reproducible builds.
# npm ci will fail without it — this is intentional (no silent fallback).
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# ── Serve stage ───────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
# Default matches the docker-compose service name; override via API_UPSTREAM env var
# when frontend and api are separate hosted services (see render.yaml).
# The official nginx image runs envsubst on templates/*.template -> conf.d/*.conf at startup.
ENV API_UPSTREAM=http://api:8000
EXPOSE 80
