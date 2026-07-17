variable "name_prefix" {
  type        = string
  description = "Env resource prefix, e.g. holahost-staging."
}

variable "bucket_regional_domain_name" {
  type        = string
  description = "Frontend bucket regional domain name (S3 origin)."
}

variable "acm_certificate_arn" {
  type        = string
  description = "Validated ACM cert ARN (us-east-1) for the viewer cert."
}

variable "route53_zone_id" {
  type        = string
  description = "Hosted zone id for the alias A/AAAA records."
}

variable "aliases" {
  type        = list(string)
  description = "CNAMEs served by this distribution (staging: [staging.hola.host]; prod: [hola.host])."
}

variable "release_prefix" {
  type        = string
  description = "Origin path for the releases S3 origin (releases/<git-sha>). Empty at create; CI mutates it (ignored via lifecycle)."
  default     = ""
}

variable "price_class" {
  type        = string
  description = "CloudFront price class (supplied per env from infra/config.yaml)."
}

variable "api_origin_domain" {
  type        = string
  description = "Lambda Function URL host (from the service) served under the api_base_url behavior."
}

variable "api_base_url" {
  type        = string
  description = "Service mount path — SINGLE source of the API prefix (API_BASE_URL, e.g. /api/lead-capture; §11.6). The `<api_base_url>/*` behavior routes to the Lambda Function URL; the backend router strips the same value."
}
