import { signal } from '@preact/signals-core';

/**
 * Email-capture entry point (`Lead.flow`, §7.2.5 / §5.4 — the two `LEAD_FLOW_VALUES`):
 * `'guidebook'` (entrypoint → Use guidebook) or `'sample'` (sample-response → Leave email).
 */
export type LeadFlow = 'guidebook' | 'sample';

/**
 * Which entry point led to `<capture-email-screen>` (§1.3.4). Set before navigating to
 * `/capture-email`; read by the capture screen for the `flow` field of `POST /api/leads/capture`.
 * The router carries no params (query strings break the path lookup), so this small signal bridges
 * the intent across the navigation. Defaults to `'guidebook'` (direct landing on `/capture-email`).
 */
export const captureFlow = signal<LeadFlow>('guidebook');
