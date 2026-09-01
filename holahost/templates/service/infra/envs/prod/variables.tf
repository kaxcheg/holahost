variable "env" {
  type    = string
  default = "prod"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "alert_email" {
  type        = string
  description = "SNS subscription endpoint for this service's alarms."
}
