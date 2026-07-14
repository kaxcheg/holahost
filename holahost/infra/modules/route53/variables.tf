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
    name    = string
    type    = string
    ttl     = number
    records = list(string)
  }))
  description = "Email-auth DNS records (SPF/DKIM/DMARC). Keyed by a free-form label; `name` is the DNS record name — labels allow several record types on one name (Resend puts MX + SPF TXT both on send.<domain>). Values come from Resend (I-16); empty until then (D-13)."
  default     = {}
}
