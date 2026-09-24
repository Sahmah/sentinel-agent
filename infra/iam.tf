# The role `sentinel webcam` / `sentinel serve-mcp` run as. It is assumed by an
# existing identity (var.trusted_principal_arn), so no access keys are minted here.
# Policies are plain jsonencode() so `terraform test` can assert on their contents.
locals {
  account_id = data.aws_caller_identity.current.account_id

  # The inference profile, plus the model in every region it can route to:
  # Bedrock checks both (aws-bedrock-terraform skill, §1).
  bedrock_resources = concat(
    ["arn:aws:bedrock:${var.aws_region}:${local.account_id}:inference-profile/${var.inference_profile_id}"],
    [for region in var.profile_regions : "arn:aws:bedrock:${region}::foundation-model/${var.foundation_model_id}"],
  )

  pipeline_policy = {
    Version = "2012-10-17"
    Statement = [
      {
        # The Converse API the agent uses is authorized through these two actions.
        Sid      = "InvokeReasoningModel"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = local.bedrock_resources
      },
      {
        # Exactly the calls DynamoDbStorage makes: put_item, get_item, query on the GSI.
        Sid      = "ReadWriteEvents"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"]
        Resource = [aws_dynamodb_table.events.arn, "${aws_dynamodb_table.events.arn}/index/by_time"]
      },
    ]
  }
}

resource "aws_iam_role" "pipeline" {
  name                 = "sentinel-agent-pipeline"
  max_session_duration = 3600 * 12
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { AWS = var.trusted_principal_arn }
    }]
  })
}

resource "aws_iam_role_policy" "pipeline" {
  name   = "sentinel-agent-pipeline"
  role   = aws_iam_role.pipeline.id
  policy = jsonencode(local.pipeline_policy)
}
