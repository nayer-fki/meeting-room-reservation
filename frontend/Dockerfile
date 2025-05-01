# frontend/Dockerfile
# Use an official Node.js runtime as the base image
FROM node:18-alpine

# Set the working directory inside the container
WORKDIR /app

# Copy package.json and package-lock.json to the working directory
COPY package.json package-lock.json ./

# Install dependencies
RUN npm install

# Copy the rest of the application code
COPY . .

# Build the React app for production
RUN npm run build

# Use a lightweight web server to serve the static files
FROM nginx:alpine

# Copy the build output to the Nginx HTML directory
COPY --from=0 /app/build /usr/share/nginx/html

# Expose port 80 for the Nginx server
EXPOSE 80

# Start Nginx server
CMD ["nginx", "-g", "daemon off;"]