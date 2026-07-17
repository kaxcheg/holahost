# Holahost places the lead-capture service into PROD. Same shape as staging/lead-capture; env-specific
# values come from ../prod.env, the platform config, and the service's declared prod sizing.
locals {
  platform  = yamldecode(file("${path.module}/../../../config.yaml"))
  project   = local.platform.project
  env       = "prod"
  env_cfg   = local.platform.envs[local.env]
  subdomain = local.env_cfg.subdomain_prefix == "" ? local.platform.domain : "${local.env_cfg.subdomain_prefix}.${local.platform.domain}"

  svc     = yamldecode(file("${path.module}/../../../../services/lead-capture/infra/config.yaml"))
  svc_env = local.svc.envs[local.env]

  # Parse the service's committed per-env backend config (owned by lead-capture).
  beenv_lines = [
    for line in split("\n", file("${path.module}/../../../../services/lead-capture/envs/${local.env}.env")) : trimspace(line)
    if trimspace(line) != "" && !startswith(trimspace(line), "#") && strcontains(line, "=")
  ]
  beenv = {
    for line in local.beenv_lines :
    trimspace(split("=", line)[0]) => trimspace(join("=", slice(split("=", line), 1, length(split("=", line)))))
  }
  fe_env_lines = [
    for line in split("\n", file("${path.module}/../../../../frontend/.env")) : trimspace(line)
    if trimspace(line) != "" && !startswith(trimspace(line), "#") && strcontains(line, "=")
  ]
  fe_env = {
    for line in local.fe_env_lines :
    trimspace(split("=", line)[0]) => trimspace(join("=", slice(split("=", line), 1, length(split("=", line)))))
  }
}

data "terraform_remote_state" "common" {
  backend = "s3"
  config = {
    bucket = "holahost-tfstate-common"
    key    = "common/terraform.tfstate"
    region = "us-east-1"
  }
}

module "lead_capture" {
  source = "../../../../services/lead-capture/infra"

  env                      = local.env
  name_prefix              = "${local.project}-${local.env}"
  aws_region               = local.platform.aws_region
  image_uri                = "${data.terraform_remote_state.common.outputs.ecr_repository_urls["lead-capture"]}:latest"
  frontend_origin          = "https://${local.subdomain}"
  frontend_bucket          = local.platform.frontend_bucket
  frontend_bucket_arn      = data.terraform_remote_state.common.outputs.frontend_bucket_arn
  sample_guidebook_key     = local.platform.sample_guidebook_key
  system_prompt_key        = local.env_cfg.system_prompt_key
  magic_link_path          = local.fe_env.MAGIC_LINK_PATH
  magic_link_url_param     = local.fe_env.MAGIC_LINK_URL_PARAM
  backend_env              = local.beenv
  recovery_window_in_days  = local.svc_env.recovery_window_in_days
  log_retention_days       = local.svc_env.log_retention_days
  lambda_api_memory_mb     = local.svc_env.lambda_api_memory_mb
  lambda_api_timeout_s     = local.svc_env.lambda_api_timeout_s
  lambda_cleanup_memory_mb = local.svc_env.lambda_cleanup_memory_mb
  lambda_cleanup_timeout_s = local.svc_env.lambda_cleanup_timeout_s
  alert_email              = local.platform.alert_email
}
