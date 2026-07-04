variable "domain_name" {
  type        = string
  description = "Apex domain / hosted zone name (supplied from infra/config.yaml)."
}

variable "subject_alternative_names" {
  type        = list(string)
  description = "Extra names on the ACM cert, e.g. the staging subdomain (supplied from infra/config.yaml)."
}

variable "email_dns_records" {
  type = map(object({
    type    = string
    ttl     = number
    records = list(string)
  }))
  description = "Email-auth DNS records (SPF/DKIM/DMARC). Keyed by record name. Values come from Resend (I-16); empty until then (D-13)."
  default     = {}
}
