output "scheduler_function_name" {
  description = <<-EOT
    Scheduler Lambda name. To fire a test reminder from the AWS console:
    Lambda -> this function -> "Test" with event {} (runs the WEEKLY_PAY
    loop for today), or create a one-off EventBridge schedule targeting it
    with input {"rule": "<RULE>"}.
  EOT
  value       = aws_lambda_function.scheduler.function_name
}

output "scheduler_schedule_group" {
  description = "EventBridge Scheduler group holding the seven reminder schedules."
  value       = aws_scheduler_schedule_group.reminders.name
}

output "ses_from_identity_arn" {
  description = "Sender SES identity — confirm the verification email before expecting delivery."
  value       = aws_sesv2_email_identity.from.arn
}

output "ses_to_identity_arn" {
  description = "Recipient SES identity (sandbox mode requires verified recipients) — confirm its verification email."
  value       = aws_sesv2_email_identity.to.arn
}
