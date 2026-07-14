import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { MESSAGES_URL, SAMPLE_GUIDEBOOK_URL } from './components/sample-response-screen';
import { SCHEMA_URL } from './components/template-screen';

// Published-key ↔ fetch-path parity (C-11, §11.2/§11.3): the S3 keys s3_frontend publishes must
// equal the paths the SPA fetches — otherwise CloudFront's SPA fallback silently serves
// index.html (text/html) instead of the asset. A failed extraction below is drift too.
// The published-config source of truth (config.yaml + s3_frontend) belongs to the Holahost platform
// infra; the frontend asserts published-key ↔ fetch-path parity against it.
const INFRA = resolve(import.meta.dirname, '..', '..', 'infra');

function configYamlKey(name: string): string {
  const text = readFileSync(resolve(INFRA, 'config.yaml'), 'utf8');
  const match = text.match(new RegExp(`^${name}:\\s*(\\S+)`, 'm'));
  if (!match?.[1]) {
    throw new Error(`infra/config.yaml: key ${name} not found`);
  }
  return match[1];
}

function templateSchemaTfKey(): string {
  const text = readFileSync(resolve(INFRA, 'modules', 's3_frontend', 'main.tf'), 'utf8');
  const match = text.match(
    /resource "aws_s3_object" "template_schema" \{[\s\S]*?key\s*=\s*"([^"]+)"/,
  );
  if (!match?.[1]) {
    throw new Error('s3_frontend/main.tf: template_schema key literal not found');
  }
  return match[1];
}

describe('published /config/* parity (C-11)', () => {
  it('template schema: published S3 key matches the fetch path', () => {
    expect(`/${templateSchemaTfKey()}`).toBe(SCHEMA_URL);
  });

  it('sample messages: published S3 key matches the fetch path', () => {
    expect(`/${configYamlKey('sample_messages_key')}`).toBe(MESSAGES_URL);
  });

  it('sample guidebook: published S3 key matches the download href', () => {
    expect(`/${configYamlKey('sample_guidebook_key')}`).toBe(SAMPLE_GUIDEBOOK_URL);
  });
});
