output "table_name" {
  description = "Set SENTINEL_DYNAMODB_TABLE to this."
  value       = aws_dynamodb_table.events.name
}

output "pipeline_role_arn" {
  description = "Put this in an AWS profile (role_arn + source_profile) and run the pipeline with AWS_PROFILE."
  value       = aws_iam_role.pipeline.arn
}

output "bedrock_model_id" {
  description = "Set SENTINEL_BEDROCK_MODEL_ID to this."
  value       = var.inference_profile_id
}
