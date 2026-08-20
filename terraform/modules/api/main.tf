# API Gateway HTTP API + a single Lambda ("monolith Lambda") running the
# FastAPI app via Mangum (§2.2). A JWT authorizer validates Cognito-issued
# tokens natively — API Gateway rejects unauthenticated requests before
# Lambda is invoked (§7.1). `/health` stays open (it's a liveness check with
# no sensitive data); every other route requires a valid JWT.

locals {
  name_prefix = "${var.project}-${var.environment}"
}

# ---- Lambda ----------------------------------------------------------------

resource "aws_iam_role" "lambda_exec" {
  name = "${local.name_prefix}-api-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Least-privilege: just enough to write its own logs. DynamoDB/S3 permissions
# are added in later phases as the API grows beyond hello-world (§7.4).
resource "aws_iam_role_policy_attachment" "lambda_basic_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_cloudwatch_log_group" "api_lambda" {
  name              = "/aws/lambda/${local.name_prefix}-api"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "api" {
  function_name = "${local.name_prefix}-api"
  role          = aws_iam_role.lambda_exec.arn

  filename         = var.lambda_artifact_path
  source_code_hash = filebase64sha256(var.lambda_artifact_path)

  handler       = "pappy.api.handler.handler"
  runtime       = "python3.13"
  architectures = ["arm64"]
  memory_size   = 512
  timeout       = 10

  depends_on = [aws_cloudwatch_log_group.api_lambda]
}

# ---- HTTP API ----------------------------------------------------------------

resource "aws_apigatewayv2_api" "this" {
  name          = "${local.name_prefix}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = var.cors_allowed_origins
    allow_methods = ["GET"]
    allow_headers = ["authorization", "content-type"]
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

# JWT authorizer, validating Cognito-issued access tokens (§7.1). API
# Gateway checks the signature/expiry/issuer/audience itself and rejects bad
# tokens before Lambda runs; the Lambda still derives `employerId` from the
# token's `sub` claim for authorization scoping.
resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.this.id
  name             = "${local.name_prefix}-cognito"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    audience = [var.cognito_user_pool_client_id]
    issuer   = var.cognito_issuer
  }
}

# GET /health: liveness check, deliberately unauthenticated — nothing
# sensitive, and useful for probing the deploy without a token in hand.
resource "aws_apigatewayv2_route" "health" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "GET /health"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

# Every other route: the FastAPI app owns URL routing, API Gateway just
# proxies — but only once the JWT authorizer has approved the request.
resource "aws_apigatewayv2_route" "default" {
  api_id             = aws_apigatewayv2_api.this.id
  route_key          = "$default"
  target             = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      integrationErr = "$context.integrationErrorMessage"
    })
  }
}

resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/aws/apigateway/${local.name_prefix}-api"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}
