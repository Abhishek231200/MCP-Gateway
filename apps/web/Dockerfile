FROM node:20-alpine AS base
WORKDIR /app

# ─── Development stage ───────────────────────────────────────────────────────
FROM base AS development

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev"]

# ─── Build stage ─────────────────────────────────────────────────────────────
FROM base AS builder

COPY package.json package-lock.json* ./
RUN npm install --prefer-offline

COPY . .
RUN npm run build

# ─── Production stage ────────────────────────────────────────────────────────
FROM nginx:alpine AS production

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
