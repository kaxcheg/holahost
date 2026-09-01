output "log_group_name" {
  value = aws_cloudwatch_log_group.app.name
}

output "alerts_topic_arn" {
  value       = aws_sns_topic.alerts.arn
  description = "For the service's own alarms, which add to these rather than replacing them."
}

output "metric_namespace" {
  value       = local.namespace
  description = "So the service's own metric filters publish alongside the platform's."
}
