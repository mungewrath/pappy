# Scheduler Lambda + EventBridge Schedules + SES (design-doc.md §6.6, phase 4).
#
# EventBridge Scheduler fires this function per reminder cadence; the run
# materializes `ReminderInstance` rows and emails them via SES. The weekly
# cadence additionally seeds DRAFT pay runs from each employee's default
# schedule (§6.1), making the weekly loop hands-off.
#
# Manual triggering (test reminders) — two supported paths, no code needed:
#
#   1. Lambda console: open the function named in the
#      `scheduler_function_name` output, click "Test", keep/enter event
#      {}. An empty payload runs the WEEKLY_PAY loop for today.
#      {"rule": "<RULE>", "fire_date": "YYYY-MM-DD"} pins any other rule.
#
#   2. EventBridge console: create a one-off ("recurring schedule" ->
#      single occurrence) Schedule targeting this function with input
#      {"rule": "<RULE>"} at any future time.
#
# The API's POST /reminders/test-send runs the same code path for the
# signed-in employer without touching AWS at all.

locals {
  name_prefix = "${var.project}-${var.environment}"
  timezone    = "America/Los_Angeles"
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_exec" {
  name               = "${local.name_prefix}-scheduler-lambda"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role_policy_attachment" "lambda_basic_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Least privilege (§7.4): the table permissions mirror the API Lambda's,
# plus dynamodb:Scan — the scheduler has no request context, so it
# discovers employers by scanning PROFILE items (employer_repo.list_all).
resource "aws_iam_role_policy" "lambda_dynamodb" {
  name = "${local.name_prefix}-scheduler-dynamodb"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:Query",
        "dynamodb:Scan",
      ]
      Resource = var.table_arn
    }]
  })
}

# ---- SES --------------------------------------------------------------------
#
# Sandbox mode is sufficient by design (§2.2): sender and recipient are both
# fixed, verified identities owned by this account. Creating these resources
# sends verification emails to both addresses — each must be confirmed by
# clicking its link before any mail is delivered. Test mail goes to
# var.reminder_to_email; flip it to the real owner's address later via
# -var if desired.
resource "aws_sesv2_email_identity" "from" {
  email_identity = var.reminder_from_email
}

resource "aws_sesv2_email_identity" "to" {
  email_identity = var.reminder_to_email
}

resource "aws_iam_role_policy" "lambda_ses" {
  name = "${local.name_prefix}-scheduler-ses"
  role = aws_iam_role.lambda_exec.id

  # Send only, from/to the two verified identities (§7.4: no wildcard
  # resource ARNs). SES evaluates SendEmail against every identity involved
  # — the sender AND a same-account verified recipient — so both ARNs are
  # required in Resource. ses:Recipients is multivalued (ArrayOfString), so
  # it needs the ForAllValues set operator; plain StringEquals never matches.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ses:SendEmail", "ses:SendRawEmail"]
      Resource = [aws_sesv2_email_identity.from.arn, aws_sesv2_email_identity.to.arn]
      Condition = {
        "ForAllValues:StringEquals" = {
          "ses:Recipients" = [var.reminder_to_email]
        }
      }
    }]
  })
}

# ---- Lambda -----------------------------------------------------------------

resource "aws_cloudwatch_log_group" "scheduler_lambda" {
  name              = "/aws/lambda/${local.name_prefix}-scheduler"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "scheduler" {
  function_name = "${local.name_prefix}-scheduler"
  role          = aws_iam_role.lambda_exec.arn

  filename         = var.lambda_artifact_path
  source_code_hash = filebase64sha256(var.lambda_artifact_path)

  handler       = "pappy.scheduler.handler.handler"
  runtime       = "python3.13"
  architectures = ["arm64"]
  memory_size   = 512
  timeout       = 60

  environment {
    variables = {
      PAPPY_TABLE_NAME          = var.table_name
      PAPPY_MAILER              = "ses"
      PAPPY_REMINDER_FROM_EMAIL = var.reminder_from_email
      PAPPY_REMINDER_TO_EMAIL   = var.reminder_to_email
    }
  }

  depends_on = [aws_cloudwatch_log_group.scheduler_lambda]
}

resource "aws_scheduler_schedule_group" "reminders" {
  name = "${local.name_prefix}-reminders"
}

# Allow only these schedules to invoke the function.
resource "aws_lambda_permission" "scheduler" {
  statement_id  = "AllowEventBridgeSchedulerInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduler.function_name
  principal     = "scheduler.amazonaws.com"
  source_arn    = aws_scheduler_schedule_group.reminders.arn
}

# ---- Schedules --------------------------------------------------------------
#
# One schedule per reminder class (§6.6). All fire in America/Los_Angeles so
# "06:00" stays 06:00 across DST. Each fires a few days ahead of its
# obligation; scheduler_service maps fire date -> due date:
#
#   WEEKLY_PAY       Fri 06:00            due same day
#   QUARTERLY_TAX    Jan/Apr/Jun/Sep 8    due the 15th (1040-ES dates)
#   WA_ESD_QUARTERLY Jan/Apr/Jul/Oct 28   due month end (EAMS filing)
#   W2_EMPLOYEE      Jan 12               due Jan 31
#   ANNUAL_ROLLOVER  Jan 5                due Jan 15
#   IRS_GUIDANCE     Jan 15               due Jan 31
#   SCHEDULE_H       Mar 15               due Apr 15
locals {
  schedules = {
    weekly-pay : {
      rule        = "WEEKLY_PAY"
      cron        = "cron(0 6 ? * FRI *)"
      description = "Weekly payroll review — seed draft runs and nag"
    }
    quarterly-tax : {
      rule        = "QUARTERLY_TAX"
      cron        = "cron(0 6 8 1,4,6,9 ? *)"
      description = "Federal quarterly estimated tax lead-time nudge"
    }
    wa-esd-quarterly : {
      rule        = "WA_ESD_QUARTERLY"
      cron        = "cron(0 6 28 1,4,7,10 ? *)"
      description = "WA ESD quarterly EAMS report after quarter close"
    }
    w2-employee : {
      rule        = "W2_EMPLOYEE"
      cron        = "cron(0 6 12 1 ? *)"
      description = "W-2 to employee — deadline Jan 31"
    }
    annual-rollover : {
      rule        = "ANNUAL_ROLLOVER"
      cron        = "cron(0 6 5 1 ? *)"
      description = "Annual statutory rate rollover checklist"
    }
    irs-guidance : {
      rule        = "IRS_GUIDANCE"
      cron        = "cron(0 6 15 1 ? *)"
      description = "Annual IRS guidance links checklist"
    }
    schedule-h : {
      rule        = "SCHEDULE_H"
      cron        = "cron(0 6 15 3 ? *)"
      description = "Schedule H preparation for tax filing season"
    }
  }
}

resource "aws_scheduler_schedule" "reminders" {
  for_each = local.schedules

  name        = "${local.name_prefix}-${each.key}"
  group_name  = aws_scheduler_schedule_group.reminders.name
  description = each.value.description
  state       = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = each.value.cron
  schedule_expression_timezone = local.timezone

  target {
    arn      = aws_lambda_function.scheduler.arn
    role_arn = aws_iam_role.schedule_invoke.arn

    input = jsonencode({ rule = each.value.rule })

    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600
    }
  }

  depends_on = [aws_lambda_permission.scheduler]
}

# EventBridge Scheduler needs a role to invoke the target on our behalf;
# distinct from the Lambda's own execution role.
data "aws_iam_policy_document" "schedule_invoke_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "schedule_invoke" {
  name               = "${local.name_prefix}-scheduler-invoke"
  assume_role_policy = data.aws_iam_policy_document.schedule_invoke_assume.json
}

resource "aws_iam_role_policy" "schedule_invoke_lambda" {
  name = "${local.name_prefix}-schedule-invoke-lambda"
  role = aws_iam_role.schedule_invoke.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lambda:InvokeFunction"]
      Resource = [aws_lambda_function.scheduler.arn]
    }]
  })
}
