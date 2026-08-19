output "api_invoke_url" {
  description = "Base invoke URL for the HTTP API — set as the SPA's VITE_API_BASE_URL."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "lambda_function_name" {
  value = aws_lambda_function.api.function_name
}
