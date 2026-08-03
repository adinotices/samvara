# Build and serve static frontend on Fly
FROM nginx:latest

COPY index.html /usr/share/nginx/html/
COPY src/ /usr/share/nginx/html/src/
COPY fonts/ /usr/share/nginx/html/fonts/
COPY favicon.svg /usr/share/nginx/html/
COPY api-client.js /usr/share/nginx/html/

# Copy nginx config (or use default)
COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
