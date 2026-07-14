# The lead-capture microservice as a composite, ENVIRONMENT-AGNOSTIC Terraform module. It DECLARES the
# service's AWS resources — Secrets Manager containers, the api + cleanup Lambdas, and its observability
# (its own SLO alarms). The hosting app (Holahost) DECIDES the environment and injects placement +
# platform values via the variables in variables.tf. Intrinsic, env-invariant config is read from
# ./config.yaml. No provider/backend/env here — the caller (a holahost env root) owns those.
#
# Independent deploy: this module can be applied on its own (via its holahost env root) without touching
# the app edge; routine code redeploys go through `update-function-code` (no Terraform) — see the spec.
locals {
  svc = yamldecode(file("${path.module}/config.yaml"))

  # Non-secret Lambda env. The app injects the parsed <env>.env (backend_env) + the platform values; the
  # service owns the var NAMES, the app owns the VALUES. Secret keys and blanks are dropped from the
  # base map (secrets are read from Secrets Manager at cold start, not passed as env).
  secret_keys_upper = [for k in local.svc.secret_keys : upper(k)]
  backend_env = {
    for k, v in var.backend_env : k => v
    if !contains(local.secret_keys_upper, upper(k)) && v != ""
  }
  environment_variables = merge(local.backend_env, {
    FRONTEND_ORIGIN            = var.frontend_origin
    AWS_RESOURCES_REGION       = var.aws_region
    SAMPLE_GUIDEBOOK_S3_BUCKET = var.frontend_bucket
    SAMPLE_GUIDEBOOK_S3_KEY    = var.sample_guidebook_key
    SYSTEM_PROMPT_S3_BUCKET    = var.frontend_bucket
    SYSTEM_PROMPT_S3_KEY       = var.system_prompt_key
    MAGIC_LINK_PATH            = var.magic_link_path
    MAGIC_LINK_URL_PARAM       = var.magic_link_url_param
  })
}

module "sm" {
  source = "./modules/sm"

  env                     = var.env
  secret_keys             = local.svc.secret_keys
  recovery_window_in_days = var.recovery_window_in_days
}

module "lambda" {
  source = "./modules/lambda"

  name_prefix           = var.name_prefix
  image_uri             = var.image_uri
  environment_variables = local.environment_variables
  secret_arns           = values(module.sm.secret_arns)
  frontend_bucket_arn   = var.frontend_bucket_arn
  sample_guidebook_key  = var.sample_guidebook_key
  api_memory_mb         = var.lambda_api_memory_mb
  api_timeout_s         = var.lambda_api_timeout_s
  cleanup_memory_mb     = var.lambda_cleanup_memory_mb
  cleanup_timeout_s     = var.lambda_cleanup_timeout_s
  log_retention_days    = var.log_retention_days
}

module "observability" {
  source = "./modules/observability"

  name_prefix            = var.name_prefix
  api_log_group_name     = module.lambda.api_log_group_name
  cleanup_log_group_name = module.lambda.cleanup_log_group_name
  alert_email            = var.alert_email
  # Single source of the cap is the injected <env>.env (SAMPLE_BUDGET_DAILY_CAP_TOKENS); the alarm fires
  # at 0.8x this value.
  sample_budget_daily_cap_tokens = tonumber(local.environment_variables["SAMPLE_BUDGET_DAILY_CAP_TOKENS"])
}
