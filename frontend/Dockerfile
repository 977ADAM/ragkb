FROM oven/bun:1 AS build
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile
COPY . .
RUN bun run build

FROM node:22-slim
WORKDIR /app
COPY --from=build /app/build ./build
ENV NODE_ENV=production PORT=3000 BODY_SIZE_LIMIT=21M
EXPOSE 3000
CMD ["node", "build"]
