output "sns_topic_arn" {
  description = "Alarms SNS topic ARN — the env's single notification channel."
  value       = aws_sns_topic.alarms.arn
}
