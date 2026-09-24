# AWS infrastructure (optional)

What the AWS path of Sentinel Agent needs, and nothing else. The pipeline itself runs on the
machine with the camera; AWS only provides the reasoning model and the event store.

| Resource | Why |
| --- | --- |
| DynamoDB table `sentinel-events` | `SENTINEL_STORAGE_BACKEND=dynamodb`. Same keys as `dynamodb_store.create_table`: `id`, plus the `by_time` GSI for newest-first queries. On-demand billing, point-in-time recovery, encryption. |
| IAM role `sentinel-agent-pipeline` | Assumed by your existing IAM identity, so no access keys are created. Allowed: `bedrock:InvokeModel*` on one inference profile and its foundation model in each routed region; `PutItem`/`GetItem`/`Query` on the table and its index. No wildcards (a test enforces it). |
| Budget (optional) | Email at 80% of a monthly limit (actual) and at 100% (forecast). |

Snapshots stay on the local disk; there is no S3 bucket until the code uploads to one.

> **Applying this creates billable AWS resources.** DynamoDB on demand costs cents at this
> volume and Bedrock is billed per token, but check before you apply, and `terraform destroy`
> when you are done.

## Check it (offline, no AWS account needed)

```bash
cd infra
terraform init -backend=false
terraform fmt -check && terraform validate
terraform test          # mocked provider: table shape, no IAM wildcards, optional budget
```

## Deploy

```bash
cp terraform.tfvars.example terraform.tfvars   # your IAM identity ARN, budget email
terraform init
terraform plan
terraform apply                                # only when you mean it
```

Then add a profile that assumes the role, and point Sentinel at it:

```ini
# ~/.aws/config
[profile sentinel]
role_arn = <pipeline_role_arn output>
source_profile = default
region = us-east-1
```

```bash
export AWS_PROFILE=sentinel
export SENTINEL_LLM_BACKEND=bedrock SENTINEL_BEDROCK_MODEL_ID=<bedrock_model_id output>
export SENTINEL_STORAGE_BACKEND=dynamodb SENTINEL_DYNAMODB_TABLE=<table_name output>
uv run sentinel demo
```

Model ids: check the Bedrock console for the inference profile available in your region and
set `inference_profile_id` / `foundation_model_id` to match; the defaults assume a `us.`
profile for Claude Opus 5.
