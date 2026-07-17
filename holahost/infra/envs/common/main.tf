# `common` — cross-env platform singletons owned by the Holahost app: the Route 53 zone + ACM cert
# (domain), the frontend S3 bucket + published /config/* assets, and one ECR repo per hosted service.
# Applied once, before the per-env `lead-capture` / `gateway` roots (they read these via remote_state).
locals {
  cfg     = yamldecode(file("${path.module}/../../config.yaml"))
  project = local.cfg.project
  env     = "common"

  # Every env subdomain, DERIVED from the single `domain` (prefix "" => apex). Cert SANs = non-apex ones.
  subdomains = {
    for e, c in local.cfg.envs : e => (c.subdomain_prefix == "" ? local.cfg.domain : "${c.subdomain_prefix}.${local.cfg.domain}")
  }
  cert_sans = [for e, s in local.subdomains : s if s != local.cfg.domain]
}

module "s3_frontend" {
  source      = "../../modules/s3_frontend"
  bucket_name = local.cfg.frontend_bucket
  # config.yaml holds these app-root-relative; the app root is 3 levels up from this root dir.
  guidebook_template_path = "${path.module}/../../../${local.cfg.guidebook_template_path}"
  sample_guidebook_path   = "${path.module}/../../../${local.cfg.sample_guidebook_path}"
  sample_guidebook_key    = local.cfg.sample_guidebook_key
  sample_messages_path    = "${path.module}/../../../${local.cfg.sample_messages_path}"
  sample_messages_key     = local.cfg.sample_messages_key
  system_prompt_objects = {
    for e, c in local.cfg.envs : e => {
      key    = c.system_prompt_key
      source = "${path.module}/../../../${c.system_prompt_path}"
    }
  }
}

module "route53" {
  source                    = "../../modules/route53"
  domain_name               = local.cfg.domain
  subject_alternative_names = local.cert_sans
  email_dns_records         = local.cfg.email_dns_records

  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }
}

# One ECR repository per hosted service (image namespace; the service reads its repo URL by name).
module "ecr" {
  for_each = toset(local.cfg.ecr_repos)
  source   = "../../modules/ecr"

  repository_name = each.value
}
