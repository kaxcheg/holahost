# Module instances for this env. Static config from infra/config.yaml (single source); shared
# resources (frontend bucket, hosted zone, ACM cert) live in the `shared` root and are read here
# via data sources. ecr / lambda / observability land in I-08 … I-13.
locals {
  cfg     = yamldecode(file("${path.module}/../../config.yaml"))
  project = local.cfg.project
  env     = "staging"
  env_cfg = local.cfg.envs[local.env]

  # Non-secret Lambda env (§10.9): parse <env>.env (drop comments/blanks + the SM secret keys, loaded
  # from Secrets Manager at cold start, §10.3) and merge the config.yaml/s3_frontend/fe-env cross-source
  # values. Duplicated verbatim in prod/main.tf — kept in sync by hand (no module/symlink, D-37).
  beenv_lines = [
    for line in split("\n", file("${path.module}/${local.env}.env")) : trimspace(line)
    if trimspace(line) != "" && !startswith(trimspace(line), "#") && strcontains(line, "=")
  ]
  beenv_all = {
    for line in local.beenv_lines :
    trimspace(split("=", line)[0]) => trimspace(join("=", slice(split("=", line), 1, length(split("=", line)))))
  }
  secret_keys_upper = [for k in module.sm.secret_keys : upper(k)]
  beenv_nonsecret = {
    for k, v in local.beenv_all : k => v if !contains(local.secret_keys_upper, k) && v != ""
  }
  fe_env_lines = [
    for line in split("\n", file("${path.module}/../../../frontend/.env")) : trimspace(line)
    if trimspace(line) != "" && !startswith(trimspace(line), "#") && strcontains(line, "=")
  ]
  fe_env = {
    for line in local.fe_env_lines :
    trimspace(split("=", line)[0]) => trimspace(join("=", slice(split("=", line), 1, length(split("=", line)))))
  }
  # SYSTEM_PROMPT is NOT here — the backend fetches it from S3 at cold start (D-30).
  lambda_env = merge(local.beenv_nonsecret, {
    FRONTEND_ORIGIN            = "https://${local.env_cfg.subdomain}"
    AWS_RESOURCES_REGION       = local.cfg.aws_region
    SAMPLE_GUIDEBOOK_S3_BUCKET = local.cfg.frontend_bucket
    SAMPLE_GUIDEBOOK_S3_KEY    = local.cfg.sample_guidebook_key
    SYSTEM_PROMPT_S3_BUCKET    = local.cfg.frontend_bucket
    SYSTEM_PROMPT_S3_KEY       = local.env_cfg.system_prompt_key
    MAGIC_LINK_PATH            = local.fe_env.MAGIC_LINK_PATH
    MAGIC_LINK_URL_PARAM       = local.fe_env.MAGIC_LINK_URL_PARAM
  })
}

module "sm" {
  source = "../../modules/sm"

  env                     = local.env
  recovery_window_in_days = local.env_cfg.recovery_window_in_days
}

# Shared resources (frontend bucket, hosted zone, ACM cert) are owned by the `shared` root and
# read here via data sources — apply `shared` before this env.
data "aws_s3_bucket" "frontend" {
  bucket = local.cfg.frontend_bucket
}

data "aws_route53_zone" "primary" {
  name = local.cfg.domain
}

data "aws_acm_certificate" "frontend" {
  provider    = aws.us_east_1
  domain      = local.cfg.domain
  statuses    = ["ISSUED"]
  most_recent = true
}

# Shared ECR repo (owned by the shared root) — read by name (config.yaml), like the other shared reads.
data "aws_ecr_repository" "api" {
  name = "${local.project}-api"
}

module "lambda" {
  source = "../../modules/lambda"

  name_prefix           = local.env_cfg.name_prefix
  image_uri             = "${data.aws_ecr_repository.api.repository_url}:latest"
  environment_variables = local.lambda_env
  secret_arns           = values(module.sm.secret_arns)
  frontend_bucket_arn   = data.aws_s3_bucket.frontend.arn
  sample_guidebook_key  = local.cfg.sample_guidebook_key
  api_memory_mb         = local.env_cfg.lambda_api_memory_mb
  api_timeout_s         = local.env_cfg.lambda_api_timeout_s
  cleanup_memory_mb     = local.env_cfg.lambda_cleanup_memory_mb
  cleanup_timeout_s     = local.env_cfg.lambda_cleanup_timeout_s
  log_retention_days    = local.env_cfg.log_retention_days
}

module "cloudfront" {
  source = "../../modules/cloudfront"

  name_prefix                 = local.env_cfg.name_prefix
  aliases                     = [local.env_cfg.subdomain]
  price_class                 = local.env_cfg.price_class
  bucket_regional_domain_name = data.aws_s3_bucket.frontend.bucket_regional_domain_name
  acm_certificate_arn         = data.aws_acm_certificate.frontend.arn
  route53_zone_id             = data.aws_route53_zone.primary.zone_id
  api_origin_domain           = module.lambda.function_url_domain
}

# CloudFront → Function URL invoke (D-28). Root-level (needs the distribution ARN → no module cycle);
# exact ARN = least-privilege.
resource "aws_lambda_permission" "cloudfront_invoke" {
  statement_id           = "AllowCloudFrontInvoke"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = module.lambda.api_function_name
  principal              = "cloudfront.amazonaws.com"
  function_url_auth_type = "AWS_IAM"
  source_arn             = module.cloudfront.distribution_arn
}
