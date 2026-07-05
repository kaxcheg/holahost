# Shared single-instance resources. s3_frontend + route53 are created here once; staging/prod
# read them via data sources and add their own per-env cloudfront (I-11). All static config comes
# from infra/config.yaml (single source of truth) — modules receive explicit inputs.
locals {
  cfg     = yamldecode(file("${path.module}/../../config.yaml"))
  project = local.cfg.project
  # Cert SANs = every env subdomain that isn't the apex itself (prod's subdomain == the apex).
  cert_sans = [for _, e in local.cfg.envs : e.subdomain if e.subdomain != local.cfg.domain]
}

module "s3_frontend" {
  source      = "../../modules/s3_frontend"
  bucket_name = local.cfg.frontend_bucket
  # config.yaml holds these repo-root-relative; the repo root is 3 levels up from this root dir.
  guidebook_template_path = "${path.module}/../../../${local.cfg.guidebook_template_path}"
  sample_guidebook_path   = "${path.module}/../../../${local.cfg.sample_guidebook_path}"
  sample_guidebook_key    = local.cfg.sample_guidebook_key
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

module "ecr" {
  source          = "../../modules/ecr"
  repository_name = "${local.project}-api"
}
