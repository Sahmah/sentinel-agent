# Offline checks: `terraform test` with a mocked AWS provider, no credentials, no cost.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_resource "aws_dynamodb_table" {
    defaults = { arn = "arn:aws:dynamodb:us-east-1:123456789012:table/sentinel-events" }
  }
}

variables {
  trusted_principal_arn = "arn:aws:iam::123456789012:user/sarah"
}

run "table_matches_the_python_store" {
  command = plan

  assert {
    condition     = aws_dynamodb_table.events.billing_mode == "PAY_PER_REQUEST"
    error_message = "The table must be on-demand: no idle cost."
  }
  assert {
    condition     = aws_dynamodb_table.events.hash_key == "id"
    error_message = "Partition key must be `id`, as in dynamodb_store.create_table."
  }
  assert {
    condition     = one(aws_dynamodb_table.events.global_secondary_index).name == "by_time"
    error_message = "The by_time GSI serves newest-first queries."
  }
}

run "pipeline_policy_is_least_privilege" {
  command = apply # mocked: computes the policy JSON without calling AWS

  assert {
    condition = alltrue([
      for s in jsondecode(aws_iam_role_policy.pipeline.policy).Statement :
      alltrue([for a in s.Action : !strcontains(a, "*")])
    ])
    error_message = "No wildcard actions."
  }
  assert {
    condition = alltrue([
      for s in jsondecode(aws_iam_role_policy.pipeline.policy).Statement :
      alltrue([for r in s.Resource : !endswith(r, "*")])
    ])
    error_message = "No wildcard resources."
  }
  assert {
    condition     = length(local.bedrock_resources) == 1 + length(var.profile_regions)
    error_message = "The inference profile plus one foundation-model ARN per routed region."
  }
}

run "budget_is_optional" {
  command = plan

  assert {
    condition     = length(aws_budgets_budget.monthly) == 0
    error_message = "No budget without an email."
  }
}

run "budget_when_email_given" {
  command = plan
  variables {
    budget_email = "me@example.com"
  }

  assert {
    condition     = length(aws_budgets_budget.monthly) == 1
    error_message = "A budget alert is created when an email is set."
  }
}
