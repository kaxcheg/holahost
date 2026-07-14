# PROD app edge. Same shape as staging/gateway; serves the SPA at the apex and routes
# /api/capture-lead/* to the prod lead-capture Function URL.
locals {
  cfg       = yamldecode(file("${path.module}/../../../config.yaml"))
  project   = local.cfg.project
  env       = "prod"
  env_cfg   = local.cfg.envs[local.env]
  subdomain = local.env_cfg.subdomain_prefix == "" ? local.cfg.domain : "${local.env_cfg.subdomain_prefix}.${local.cfg.domain}"
}

data "terraform_remote_state" "common" {
  backend = "s3"
  config = {
    bucket = "holahost-tfstate-common"
    key    = "common/terraform.tfstate"
    region = "us-east-1"
  }
}

data "terraform_remote_state" "capture_lead" {
  backend = "s3"
  config = {
    bucket = "holahost-tfstate-prod"
    key    = "prod/capture-lead/terraform.tfstate"
    region = "us-east-1"
  }
}

module "cloudfront" {
  source = "../../../modules/cloudfront"

  name_prefix                 = "${local.project}-${local.env}"
  aliases                     = [local.subdomain]
  price_class                 = local.env_cfg.price_class
  bucket_regional_domain_name = data.terraform_remote_state.common.outputs.frontend_bucket_regional_domain_name
  acm_certificate_arn         = data.terraform_remote_state.common.outputs.acm_certificate_arn
  route53_zone_id             = data.terraform_remote_state.common.outputs.route53_zone_id
  api_origin_domain           = data.terraform_remote_state.capture_lead.outputs.function_url_domain
  api_base_url                = data.terraform_remote_state.capture_lead.outputs.api_base_url
}

resource "aws_lambda_permission" "cloudfront_invoke" {
  statement_id           = "AllowCloudFrontInvoke"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = data.terraform_remote_state.capture_lead.outputs.api_function_name
  principal              = "cloudfront.amazonaws.com"
  function_url_auth_type = "AWS_IAM"
  source_arn             = module.cloudfront.distribution_arn
}
