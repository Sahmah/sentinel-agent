variable "aws_region" {
  description = "Region for the table and the Bedrock inference profile."
  type        = string
  default     = "us-east-1"
}

variable "table_name" {
  description = "DynamoDB events table. Must match SENTINEL_DYNAMODB_TABLE."
  type        = string
  default     = "sentinel-events"
}

variable "inference_profile_id" {
  description = "Bedrock inference profile the agent calls (SENTINEL_BEDROCK_MODEL_ID). A regional (us.) profile keeps the IAM resource list short."
  type        = string
  default     = "us.anthropic.claude-opus-5"
}

variable "foundation_model_id" {
  description = "The model behind the inference profile. Bedrock also checks access to it in every region the profile routes to."
  type        = string
  default     = "anthropic.claude-opus-5"
}

variable "profile_regions" {
  description = "Regions the inference profile can route requests to."
  type        = list(string)
  default     = ["us-east-1", "us-east-2", "us-west-2"]
}

variable "trusted_principal_arn" {
  description = "IAM user or role allowed to assume the pipeline role (the identity on the machine running `sentinel webcam`). No long-lived keys are created here."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Monthly cost budget; an email goes out at 80% of it (actual) and 100% (forecast)."
  type        = number
  default     = 10
}

variable "budget_email" {
  description = "Where budget alerts go. Leave empty to skip the budget."
  type        = string
  default     = ""
}
