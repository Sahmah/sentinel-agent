# The events table, exactly as sentinel_agent.storage.dynamodb_store.create_table builds it:
# partition key `id`, plus the `by_time` GSI (kind, occurred_at) that serves "newest first".
resource "aws_dynamodb_table" "events" {
  name         = var.table_name
  billing_mode = "PAY_PER_REQUEST" # no idle cost, no capacity planning
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }
  attribute {
    name = "kind"
    type = "S"
  }
  attribute {
    name = "occurred_at"
    type = "S"
  }

  global_secondary_index {
    name            = "by_time"
    projection_type = "ALL"
    key_schema {
      attribute_name = "kind"
      key_type       = "HASH"
    }
    key_schema {
      attribute_name = "occurred_at"
      key_type       = "RANGE"
    }
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}

# Cheap insurance against a runaway loop of Bedrock calls.
resource "aws_budgets_budget" "monthly" {
  count        = var.budget_email == "" ? 0 : 1
  name         = "sentinel-agent-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Project$sentinel-agent"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}
