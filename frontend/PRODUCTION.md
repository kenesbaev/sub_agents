# Frontend production deployment

The browser uses relative `/api/...` URLs only. Next.js proxies those requests
to the private backend and agent services, so neither service origin is exposed
in the browser bundle.

## Required build configuration

`BACKEND_INTERNAL_URL` and `AGENT_INTERNAL_URL` must be absolute HTTP(S)
origins without a path, query, or fragment. Next.js compiles rewrites during
`npm run build`, so these values must be present at build time. Changing only
the runtime environment does not update an existing image.

Example for Docker Compose service DNS:

```env
BACKEND_INTERNAL_URL=http://backend:8000
AGENT_INTERNAL_URL=http://agent:4173
```

Do not set either variable to a public browser URL. Do not restore
`NEXT_PUBLIC_API_URL`; authentication cookies and agent requests are designed
to remain on the frontend origin.

## Docker image

Build from the repository root because `frontend/Dockerfile` copies the
`frontend/` directory from that context:

```sh
docker build \
  --build-arg BACKEND_INTERNAL_URL=http://backend:8000 \
  --build-arg AGENT_INTERNAL_URL=http://agent:4173 \
  -f frontend/Dockerfile \
  -t teamora-frontend:local .
```

The runtime image uses Next.js standalone output, runs as an unprivileged user,
listens on port `3000`, and exposes an HTTP health check.

## Release verification

Run before building an image:

```sh
npm ci
npm run typecheck
npm run build
```

After deployment, verify through the public HTTPS origin:

- `/` and `/auth` return `200`;
- `/api/health` reaches the backend through the rewrite;
- `/api/agents/capabilities` reaches the agent service through the rewrite;
- login cookies remain first-party and no browser request targets localhost or
  a private service hostname;
- responses contain the configured security headers.

Terminate TLS at the edge proxy. HSTS is emitted in production, so production
traffic must not expose the Next.js service directly over plain HTTP.
