# Dev-oriented Dockerfile: runs the Vite dev server with hot reload.
FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5173

# VITE_API_BASE is provided via docker-compose so the SPA talks to the backend.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
