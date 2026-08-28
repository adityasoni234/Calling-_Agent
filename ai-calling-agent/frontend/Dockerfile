# syntax=docker/dockerfile:1

# ---- dependencies (shared by both targets) --------------------------------
FROM node:22-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm install

# ---- development: Vite dev server with HMR --------------------------------
FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]

# ---- production: static build served by nginx -----------------------------
FROM deps AS build
COPY . .
# Baked in at build time -- only ever public values, never secrets.
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
