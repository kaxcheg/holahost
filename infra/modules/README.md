# Terraform modules

Per-resource modules land here in I-06 … I-14 (one module per AWS resource group). The skeleton in
`infra/envs/{staging,prod}/` (providers + S3 backend + variables) is created in **I-05**; the module
instances are wired into each env's `main.tf` as the modules are built:

| Module          | Ticket | Purpose                                                          |
|-----------------|--------|-----------------------------------------------------------------|
| `sm`            | I-06   | Secrets Manager secrets (value-less); ARNs consumed by `lambda`  |
| `ecr`           | I-08   | `holahost-api` repo + lifecycle policy                          |
| `s3_frontend`   | I-09   | frontend bucket + bucket policy + OAC                           |
| `route53`       | I-10   | hosted zone `hola.host`, ACM (us-east-1), DKIM/SPF/DMARC        |
| `cloudfront`    | I-11   | staging + prod distributions + response-headers policy          |
| `lambda`        | I-12   | `holahost-{env}-api` + `-cleanup` + EventBridge + GetSecretValue IAM |
| `observability` | I-13   | log groups, metric filters, alarms, SNS + email subscription    |
| `github_repo`   | I-14   | repo settings, branch protection, GitHub Environments           |
