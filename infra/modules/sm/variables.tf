variable "env" {
  type        = string
  description = "Deployment environment (staging | prod). Used in the secret path holahost/<env>/<key>."
}

variable "secret_keys" {
  type        = list(string)
  description = "Server-side secret keys. Mirror of SERVER_SIDE_SECRET_KEYS in backend/app/scripts/sm_loader.py. This module creates value-less containers only; values are populated out-of-band (§10.3)."
  default     = ["database_url", "resend_api_key", "ip_hash_salt", "sample_server_api_key"]
}

variable "recovery_window_in_days" {
  type        = number
  description = "Secrets Manager recovery window before permanent deletion (supplied per env from infra/config.yaml: prod 30, staging 0)."
}
