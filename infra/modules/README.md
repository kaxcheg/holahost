# Terraform modules

Per-resource modules land here in I-06 … I-14 (one module per AWS resource group). The env-root skeleton
in `infra/envs/{staging,prod}/` (providers + S3 backend + variables) is created in **I-05**; a third
`infra/envs/shared/` root (I-09/I-10) owns the single-instance resources shared by both cloud envs
(frontend bucket, hosted zone, ACM cert). Module instances are wired into each root's `main.tf` as the
modules are built.

Static config (region, bucket/domain, per-env prefix/recovery/price) is centralized in
`infra/config.yaml` and passed to modules as **explicit** inputs (no implicit module defaults for
config values); see spec **§10.9 Settings inventory** for the full app-vs-infra settings map.

| Module          | Ticket | Root       | Purpose                                                          |
|-----------------|--------|------------|------------------------------------------------------------------|
| `sm`            | I-06   | per-env    | Secrets Manager secrets (value-less); ARNs consumed by `lambda`  |
| `ecr`           | I-08   | shared     | single `holahost-api` repo + lifecycle policy                    |
| `s3_frontend`   | I-09   | shared     | single `holahost-frontend` bucket + policy (account-wildcard `AWS:SourceArn`) + schema object; OAC lives in `cloudfront` |
| `route53`       | I-10   | shared     | hosted zone `hola.host` + ACM (us-east-1, DNS-validated); email SPF/DKIM/DMARC var-driven (I-16) |
| `cloudfront`    | I-11   | per-env    | per-env distribution + own OAC + response-headers policy + `/config/*` + SPA fallback + alias records |
| `lambda`        | I-12   | per-env    | `holahost-{env}-api` + `-cleanup` + EventBridge + GetSecretValue IAM + `/api/*` CloudFront behavior |
| `observability` | I-13   | per-env    | log groups, metric filters, alarms, SNS + email subscription     |
| `github_repo`   | I-14   | repo       | repo settings, branch protection, GitHub Environments            |
