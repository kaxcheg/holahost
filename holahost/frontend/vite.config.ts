/// <reference types="vitest/config" />
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import tailwindcss from '@tailwindcss/vite';
import { parse as parseEnvFile } from 'dotenv';
import type { Plugin } from 'vite';
import { defineConfig } from 'vitest/config';

// Non-secret config the frontend bakes into the bundle (a subset of the capture-lead service's
// envs/<env>.env — the frontend is a client of the service across the ownership boundary).
// MAGIC_LINK_URL_PARAM is NOT here — it is frontend-owned config, resolved from frontend/.env (see
// resolveContract).
const CONFIG_KEYS = ['ENV', 'API_BASE_URL'] as const;
const DEPLOY_ENVS = ['dev', 'staging', 'prod'] as const;

/**
 * Resolve the non-secret config for a build.
 *
 * The frontend consumes config from the ENVIRONMENT — at deploy, CI (frontend) / Terraform (backend)
 * populate it from services/lead-capture/envs/<env>.env, so the frontend is a pure env consumer, symmetric with
 * the backend. For local one-command builds it falls back to reading that file directly (the single
 * place that knows the path). Unknown modes (e.g. vitest's "test") resolve to nothing.
 */
function resolveConfig(mode: string): Record<string, string | undefined> {
  // Vitest runs in mode "test"; resolve it against the dev config so config values are non-null in tests.
  const sourceMode = mode === 'test' ? 'dev' : mode;
  let fileEnv: Record<string, string> = {};
  if ((DEPLOY_ENVS as readonly string[]).includes(sourceMode)) {
    const path = resolve(
      import.meta.dirname,
      '..',
      'services',
      'lead-capture',
      'envs',
      `${sourceMode}.env`,
    );
    if (existsSync(path)) {
      fileEnv = parseEnvFile(readFileSync(path));
    }
  }
  const resolved: Record<string, string | undefined> = {};
  for (const key of CONFIG_KEYS) {
    resolved[key] = process.env[key] ?? fileEnv[key];
  }
  if ((DEPLOY_ENVS as readonly string[]).includes(sourceMode) && resolved.ENV === undefined) {
    throw new Error(
      `no config for --mode ${mode}: set env vars or provide holahost/services/lead-capture/envs/${sourceMode}.env`,
    );
  }
  return resolved;
}

/**
 * Resolve the frontend-owned magic-link URL contract (source of truth): the token query-param name
 * (`MAGIC_LINK_URL_PARAM`) and the landing path (`MAGIC_LINK_PATH`). Both are baked into the bundle —
 * the frontend uses the param to read `?<param>=` and the path to scope the landing (see
 * boot/magic-link-landing) — and Terraform relays both to the backend Lambda (I-12) to build the email
 * link. Read from frontend/.env (committed, non-secret); `process.env` overrides for CI.
 */
function resolveContract(): Record<string, string | undefined> {
  const path = resolve(import.meta.dirname, '.env');
  const fileEnv = existsSync(path) ? parseEnvFile(readFileSync(path)) : {};
  return {
    MAGIC_LINK_URL_PARAM: process.env.MAGIC_LINK_URL_PARAM ?? fileEnv.MAGIC_LINK_URL_PARAM,
    MAGIC_LINK_PATH: process.env.MAGIC_LINK_PATH ?? fileEnv.MAGIC_LINK_PATH,
  };
}

// Published config assets (§10.9): canonical files under docs/ served at their deployed /config/*
// paths. Content types matter — the frontend guards against the SPA fallback serving text/html.
const CONFIG_ASSETS = [
  {
    route: '/config/template_schema.json',
    file: 'guidebook_template.json',
    contentType: 'application/json',
  },
  {
    route: '/config/sample_messages.json',
    file: 'sample_messages.json',
    contentType: 'application/json',
  },
  {
    route: '/config/sample_guidebook.md',
    file: 'sample_guidebook.md',
    contentType: 'text/markdown',
  },
] as const;

/**
 * Dev-only statics for the published config assets (F-16/F-20/F-21, §10.6/§10.9): serve each
 * canonical `docs/*` file at its `/config/*` path, read fresh per request (no copy, not bundled).
 * In deployed envs these paths are served from S3/CloudFront by Terraform (§10.6/§12/I-18), so the
 * plugin is `apply: 'serve'` only — the canon stays the single source.
 */
function configAssetsDevServer(): Plugin {
  return {
    name: 'serve-config-assets',
    apply: 'serve',
    configureServer(server) {
      for (const asset of CONFIG_ASSETS) {
        const assetPath = resolve(
          import.meta.dirname,
          '..',
          'services',
          'lead-capture',
          'docs',
          asset.file,
        );
        server.middlewares.use(asset.route, (_req, res, next) => {
          if (!existsSync(assetPath)) {
            next();
            return;
          }
          res.setHeader('Content-Type', asset.contentType);
          res.end(readFileSync(assetPath));
        });
      }
    },
  };
}

/**
 * Dev-only REST→Lambda-RIE bridge (local stack only, NOT for deployed envs).
 *
 * In dev the backend runs as a Lambda RIE container exposing only the invoke endpoint
 * (`:9000/2015-03-31/functions/function/invocations`), which expects a Function-URL v2.0 EVENT — not
 * REST. The SPA calls same-origin `/api/*`, so this middleware wraps each `/api/*` request into that
 * event (method, rawPath incl. the `/api` prefix the router keys on, headers, sourceIp — required by
 * the handler's ip-hash — and the body as base64: `_body_bytes` decodes it uniformly for both JSON
 * and multipart), invokes RIE, then unwraps the `{statusCode, headers, body}` response back to the
 * browser. `apply: 'serve'` only — deployed envs front `/api` via API Gateway / Function URL (§12).
 */
function rieBridgeDevServer(): Plugin {
  const RIE_ENDPOINT =
    process.env.RIE_ENDPOINT ?? 'http://localhost:9000/2015-03-31/functions/function/invocations';
  return {
    name: 'dev-rie-bridge',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = req.url ?? '';
        if (!url.startsWith('/api/')) {
          next();
          return;
        }
        const chunks: Buffer[] = [];
        req.on('data', (chunk: Buffer) => chunks.push(chunk));
        req.on('end', () => {
          const [rawPath, rawQueryString = ''] = url.split('?');
          const headers: Record<string, string> = {};
          for (const [key, value] of Object.entries(req.headers)) {
            if (typeof value === 'string') headers[key] = value;
            else if (Array.isArray(value)) headers[key] = value.join(', ');
          }
          const event = {
            version: '2.0',
            rawPath,
            rawQueryString,
            headers,
            requestContext: {
              http: {
                method: req.method ?? 'GET',
                path: rawPath,
                sourceIp: req.socket?.remoteAddress ?? '127.0.0.1',
              },
            },
            body: Buffer.concat(chunks).toString('base64'),
            isBase64Encoded: true,
          };
          fetch(RIE_ENDPOINT, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(event),
          })
            .then((rieResponse) => rieResponse.json())
            .then((payload) => {
              if (payload == null || typeof payload !== 'object' || !('statusCode' in payload)) {
                // Uncaught Lambda error (RIE returns {errorMessage,...}) or an unexpected shape.
                res.statusCode = 502;
                res.setHeader('Content-Type', 'application/json');
                res.end(
                  JSON.stringify({
                    error: {
                      code: 'ERR_DEV_BRIDGE',
                      message: 'RIE returned a non-HTTP payload',
                      details: payload,
                    },
                  }),
                );
                return;
              }
              res.statusCode = payload.statusCode;
              for (const [key, value] of Object.entries(payload.headers ?? {})) {
                res.setHeader(key, String(value));
              }
              res.end(
                payload.isBase64Encoded
                  ? Buffer.from(payload.body ?? '', 'base64')
                  : (payload.body ?? ''),
              );
            })
            .catch((err: unknown) => {
              res.statusCode = 502;
              res.setHeader('Content-Type', 'application/json');
              res.end(JSON.stringify({ error: { code: 'ERR_DEV_BRIDGE', message: String(err) } }));
            });
        });
        req.on('error', () => {
          res.statusCode = 400;
          res.end();
        });
      });
    },
  };
}

// Statics-only SPA: single bundle to dist/ (no code-splitting needed — screens are small, §11.6).
export default defineConfig(({ mode }) => {
  const cfg = resolveConfig(mode);
  const contract = resolveContract();
  return {
    plugins: [tailwindcss(), configAssetsDevServer(), rieBridgeDevServer()],
    define: {
      'import.meta.env.VITE_APP_ENV': JSON.stringify(cfg.ENV ?? null),
      'import.meta.env.VITE_API_BASE_URL': JSON.stringify(cfg.API_BASE_URL ?? null),
      'import.meta.env.VITE_MAGIC_LINK_URL_PARAM': JSON.stringify(
        contract.MAGIC_LINK_URL_PARAM ?? null,
      ),
      'import.meta.env.VITE_MAGIC_LINK_PATH': JSON.stringify(contract.MAGIC_LINK_PATH ?? null),
    },
    build: {
      target: 'es2022',
      outDir: 'dist',
    },
    test: {
      environment: 'jsdom',
      include: ['src/**/*.test.ts'],
    },
  };
});
