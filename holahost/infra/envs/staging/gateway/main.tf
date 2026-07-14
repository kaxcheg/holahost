# STAGING app edge (CloudFront today; the API-Gateway home tomorrow). Serves the SPA and routes
# /api/capture-lead/* to the lead-capture Function URL, and grants CloudFront invoke on it. Reads the
# platform singletons from `common` and the service endpoint from `staging/capture-lead` — so both must
# be applied first. This is where the app "mounts" the service at a URL.
locals {
  cfg       = yamldecode(file("${path.module}/../../../config.yaml"))
  project   = local.cfg.project
  env       = "staging"
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
    bucket = "holahost-tfstate-staging"
    key    = "staging/capture-lead/terraform.tfstate"
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

# CloudFront → Function URL invoke (D-28). The app edge grants its distribution permission to invoke the
# service Lambda; the function name comes from the service state, the distribution ARN is local.
resource "aws_lambda_permission" "cloudfront_invoke" {
  statement_id           = "AllowCloudFrontInvoke"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = data.terraform_remote_state.capture_lead.outputs.api_function_name
  principal              = "cloudfront.amazonaws.com"
  function_url_auth_type = "AWS_IAM"
  source_arn             = module.cloudfront.distribution_arn
}
