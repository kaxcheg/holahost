variable "service_name" {
  type        = string
  description = "The service's `<svc>` name — names the log group and the alarms."
}

variable "env" {
  type        = string
  description = "dev | staging | prod."
}

variable "alert_email" {
  type        = string
  description = "SNS subscription endpoint for this service's alarms."
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention. Shorter on staging than prod, by convention."
}

variable "metric_namespace_prefix" {
  type        = string
  description = <<-EOT
    CloudWatch namespace prefix, e.g. "RagDocuments". The env is appended, giving
    "RagDocuments/staging". Separate from `service_name` because a namespace is read by a
    person on a dashboard, where the kebab-case deploy identity reads badly.
  EOT
}
