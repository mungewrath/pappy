output "table_arn" {
  value = aws_dynamodb_table.pappy.arn
}

output "table_name" {
  value = aws_dynamodb_table.pappy.name
}

output "document_bucket_name" {
  description = "Name of the S3 document bucket for generated PDFs."
  value       = aws_s3_bucket.documents.id
}

output "document_bucket_arn" {
  description = "ARN of the S3 document bucket."
  value       = aws_s3_bucket.documents.arn
}
