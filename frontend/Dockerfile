# Build and serve static frontend on Fly.
# Runs the same build pipeline as GitHub Pages (scripts/build-frontend.sh):
# pack_bundle.py -> transform_bundle.py -> dist/, then serves dist/ via nginx.
#
# Build context must be the repo root (needs both scripts/ and frontend/):
#   flyctl deploy . -c deploy/fly/fly.staging-frontend.toml -a samvara-web-staging
FROM python:3.12-slim AS build

WORKDIR /src
COPY scripts/ scripts/
COPY frontend/ frontend/
RUN bash scripts/build-frontend.sh

FROM nginx:latest

COPY --from=build /src/dist/ /usr/share/nginx/html/
COPY frontend/nginx.conf /etc/nginx/nginx.conf

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
