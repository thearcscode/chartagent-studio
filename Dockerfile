# syntax=docker/dockerfile:1
#
# The build context is the PARENT directory holding both checkouts:
#
#   chartagent-studio/   this repo
#   chartagent/          the library, checked out at the pinned LIBRARY_GIT_SHA
#
# CI creates that layout (see the docker job in .github/workflows/ci.yml).
# Locally, from the directory containing both repos:
#
#   docker build -f chartagent-studio/Dockerfile .
#
# The library travels as build-context bytes rather than a git fetch because
# the repo is private until release; a pinned checkout keeps the pin exact.

# --- Stage 1: build the SPA. Node is a build-time tool, never a runtime one. ---
FROM node:22-slim AS web
WORKDIR /build
COPY chartagent-studio/web/package.json chartagent-studio/web/package-lock.json ./
RUN npm ci
COPY chartagent-studio/web/ ./
ARG VITE_CLERK_PUBLISHABLE_KEY
ENV VITE_CLERK_PUBLISHABLE_KEY=$VITE_CLERK_PUBLISHABLE_KEY
RUN npm run build

# --- Stage 2: runtime. Python and static files; no Node in this image. ---
FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /usr/local/bin/
WORKDIR /srv/studio

# Sibling layout matching the dev path source (../../chartagent from app/).
COPY chartagent/ /srv/chartagent/
COPY chartagent-studio/app/ ./app/
RUN cd app && uv sync --no-dev --no-editable

COPY --from=web /build/dist ./web/dist
ENV WEB_DIST_DIR=/srv/studio/web/dist

EXPOSE 8000
CMD ["/srv/studio/app/.venv/bin/uvicorn", "studio.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
