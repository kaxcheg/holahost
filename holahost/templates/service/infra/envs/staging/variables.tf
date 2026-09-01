variable "env" {
  type    = string
  default = "staging"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "alert_email" {
  type        = string
  description = "SNS subscription endpoint for this service's alarms."
}
