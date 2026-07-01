# First module wiring for this env. Module instances (ecr, s3_frontend, route53,
# cloudfront, lambda, observability, github_repo) are added here in I-08 … I-14.
module "sm" {
  source = "../../modules/sm"

  env                     = var.env
  recovery_window_in_days = 0 # staging: no recovery window — recreate freely while iterating
}
