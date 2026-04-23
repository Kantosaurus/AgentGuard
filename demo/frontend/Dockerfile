# syntax=docker/dockerfile:1.7

# -------- build stage: full deps + next build --------
FROM node:20-alpine AS build
WORKDIR /app
COPY demo/frontend/package*.json ./
RUN npm ci
COPY demo/frontend/ .
ARG NEXT_PUBLIC_CONTROL_PLANE=http://localhost:8000
ENV NEXT_PUBLIC_CONTROL_PLANE=$NEXT_PUBLIC_CONTROL_PLANE
RUN npm run build

# -------- deps stage: prod-only node_modules for a slim runtime --------
FROM node:20-alpine AS prod-deps
WORKDIR /app
COPY demo/frontend/package*.json ./
RUN npm ci --omit=dev

# -------- runtime stage --------
FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
COPY --from=prod-deps /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/next.config.mjs ./next.config.mjs
EXPOSE 3000
CMD ["npm", "run", "start"]
