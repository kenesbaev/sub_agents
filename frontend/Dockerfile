# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS dependencies

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder

WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

# Next.js compiles rewrites into the build artifact. Keep these server-only
# service origins on the private container network and provide them at build
# time (for example, http://backend:8000 and http://agent:4173).
ARG BACKEND_INTERNAL_URL=http://127.0.0.1:8000
ARG AGENT_INTERNAL_URL=http://127.0.0.1:4173
ARG NEXT_PUBLIC_SUPPORT_TELEGRAM_URL=
ENV BACKEND_INTERNAL_URL=${BACKEND_INTERNAL_URL} \
    AGENT_INTERNAL_URL=${AGENT_INTERNAL_URL} \
    NEXT_PUBLIC_SUPPORT_TELEGRAM_URL=${NEXT_PUBLIC_SUPPORT_TELEGRAM_URL}

COPY --from=dependencies /app/node_modules ./node_modules
COPY frontend/ ./
RUN npm run build

FROM node:22-alpine AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

RUN addgroup --system --gid 10001 nextjs \
    && adduser --system --uid 10001 --ingroup nextjs nextjs

WORKDIR /app

# `output: standalone` already contains the minimal production server and
# traced runtime dependencies. Static and public assets are copied separately.
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/public ./public
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))" || exit 1

CMD ["node", "server.js"]
