#!/bin/sh
echo "Waiting for frontend to be available..."
until curl -s http://frontend:3000 > /dev/null; do
  echo "Frontend not available yet, retrying in 5 seconds..."
  sleep 5
done
echo "Frontend is available, starting NGINX..."
exec "$@"
