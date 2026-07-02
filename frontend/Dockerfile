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
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
