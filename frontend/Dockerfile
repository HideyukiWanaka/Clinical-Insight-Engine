# =========================================================
# Frontend — Next.js (App Router) + TypeScript + TailwindCSS
# Multi-stage: dev → prod
# =========================================================

# ── Stage 1: base ─────────────────────────────────────────
FROM node:20-alpine AS base
WORKDIR /app
RUN apk add --no-cache libc6-compat curl

# ── Stage 2: deps (install only production deps) ──────────
FROM base AS deps
COPY package.json package-lock.json* ./
RUN npm ci

# ── Stage 3: dev (hot reload with volume mount) ───────────
FROM base AS dev
ENV NODE_ENV=development
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]

# ── Stage 4: builder (production build) ───────────────────
FROM base AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ── Stage 5: prod (minimal runtime image) ─────────────────
FROM base AS prod
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
RUN addgroup --system --gid 1001 nodejs \
 && adduser  --system --uid 1001 nextjs
COPY --from=builder /app/public              ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone .
COPY --from=builder --chown=nextjs:nodejs /app/.next/static     ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
