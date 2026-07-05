# Execution role (first IAM role in the repo). assume-role + one inline policy: GetSecretValue scoped
# to the four SM ARNs (D-04), s3:GetObject on the sample guidebook + the private system-prompt prefix
# (D-32/D-34), and log writes to the two pre-created groups.
data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "exec" {
  name               = "${var.name_prefix}-lambda-exec"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${var.name_prefix}-api"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "cleanup" {
  name              = "/aws/lambda/${var.name_prefix}-cleanup"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "perms" {
  statement {
    sid       = "GetSecretValues"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = var.secret_arns
  }

  statement {
    sid     = "ReadRuntimeObjects"
    effect  = "Allow"
    actions = ["s3:GetObject"]
    resources = [
      "${var.frontend_bucket_arn}/${var.sample_guidebook_key}", # public download + backend sample flow
      "${var.frontend_bucket_arn}/system-prompt/*",             # private prompt (this env's key)
    ]
  }

  statement {
    sid       = "WriteLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.api.arn}:*", "${aws_cloudwatch_log_group.cleanup.arn}:*"]
  }
}

resource "aws_iam_role_policy" "perms" {
  name   = "${var.name_prefix}-lambda-perms"
  role   = aws_iam_role.exec.id
  policy = data.aws_iam_policy_document.perms.json
}

# Request Lambda (Function URL). Same image, default handler command.
resource "aws_lambda_function" "api" {
  function_name = "${var.name_prefix}-api"
  role          = aws_iam_role.exec.arn
  package_type  = "Image"
  image_uri     = var.image_uri
  architectures = ["x86_64"] # CI builds on x86_64 runners; base image is multi-arch (§13.4)
  memory_size   = var.api_memory_mb
  timeout       = var.api_timeout_s

  image_config {
    command = ["interface.lambda_.handler.lambda_handler"]
  }

  environment {
    variables = var.environment_variables
  }

  depends_on = [aws_cloudwatch_log_group.api]

  # CI swaps the running image via update-function-code (§13.5) — ignore image drift.
  lifecycle {
    ignore_changes = [image_uri]
  }
}

# Cleanup Lambda — same image, cleanup handler command (§8.6).
resource "aws_lambda_function" "cleanup" {
  function_name = "${var.name_prefix}-cleanup"
  role          = aws_iam_role.exec.arn
  package_type  = "Image"
  image_uri     = var.image_uri
  architectures = ["x86_64"]
  memory_size   = var.cleanup_memory_mb
  timeout       = var.cleanup_timeout_s

  image_config {
    command = ["scripts.bootstrap_cleanup.lambda_handler"]
  }

  environment {
    variables = var.environment_variables
  }

  depends_on = [aws_cloudwatch_log_group.cleanup]

  lifecycle {
    ignore_changes = [image_uri]
  }
}

# Function URL: IAM-signed only; CloudFront reaches it via OAC (D-28). The invoke permission for
# CloudFront lives in the env root (needs the distribution ARN → avoids a module cycle).
resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.api.function_name
  authorization_type = "AWS_IAM"
  invoke_mode        = "BUFFERED"
}

# Daily cleanup schedule (§8.6): 00:30 UTC.
resource "aws_cloudwatch_event_rule" "cleanup" {
  name                = "${var.name_prefix}-cleanup"
  description         = "Daily cleanup of expired magic links / rate counters (§8.6)."
  schedule_expression = "cron(30 0 * * ? *)"
}

resource "aws_cloudwatch_event_target" "cleanup" {
  rule      = aws_cloudwatch_event_rule.cleanup.name
  target_id = "cleanup-lambda"
  arn       = aws_lambda_function.cleanup.arn
}

resource "aws_lambda_permission" "eventbridge_cleanup" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.cleanup.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.cleanup.arn
}
