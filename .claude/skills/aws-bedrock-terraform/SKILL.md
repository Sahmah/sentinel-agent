---
name: aws-bedrock-terraform
description: Least-privilege IAM and Terraform module best practices for a small Bedrock-powered AWS pipeline, used in the Sentinel Agent project
---

# AWS Bedrock + Terraform: Least-Privilege Reference (2026)

Reference for architecting Sentinel Agent: an event-driven pipeline (S3 snapshots → detector worker calling Bedrock → DynamoDB events table) that stays cheap and demonstrably least-privilege. Not a tutorial — assumes you already know Terraform/IAM/S3/DynamoDB/Lambda/ECS basics.

## 1. Bedrock model invocation now requires inference profiles (not model IDs)

As of 2026, most current-generation Claude models on Bedrock **reject on-demand invocation by base model ID** in most regions — you must pass an inference profile ID/ARN instead, or the call fails with `ValidationException: Invocation of model ID ... with on-demand throughput isn't supported`. [repost.aws](https://repost.aws/questions/QU9XhzpqTQTo6_4P392-2WKw/how-to-invoke-bedrock-claude-models-in-eu-west-1-getting-invocation-with-on-demand-throughput-isn-t-supported)

- **System-defined (cross-region/CRIS) profile ID** = base model ID with a region prefix, e.g. `us.anthropic.claude-sonnet-4-5-20250929-v1:0`, or `global.anthropic.claude-opus-4-5-20251101-v1:0` for global routing. [thedeployloop.substack.com](https://thedeployloop.substack.com/p/understanding-inference-profiles)
- **ARN shape** for IAM/Terraform: `arn:aws:bedrock:{region}:{account-id}:inference-profile/{inference-profile-id}` (account-scoped, unlike the account-less `foundation-model/` ARNs). [zenn.dev](https://zenn.dev/hknote/articles/bedrock-haiku-inference-profile?locale=en)
- **Important IAM gotcha**: an inference-profile ARN alone is not sufficient. Bedrock also checks permission on the underlying foundation-model ARN in *every destination region* the profile can route to — so your policy needs `Resource` entries for both the inference-profile ARN and the `foundation-model/*` ARNs in the profile's target regions (or use `aws:RequestedRegion` conditions for global CRIS). [Global cross-Region inference guidance — AWS ML blog](https://aws.amazon.com/blogs/machine-learning/securing-amazon-bedrock-cross-region-inference-geographic-and-global/)
- For Sentinel Agent (single detector worker, cost-sensitive), prefer a **regional** inference profile (`us.` prefix) over `global.` — predictable region footprint, simpler IAM resource list, no surprise cross-continent latency/data-residency questions.

## 2. Least-privilege IAM policy for InvokeModel

Never grant `bedrock:*`. Scope `Action` to exactly the invoke calls you use, and `Resource` to exact model/profile ARNs — not `foundation-model/*`. [AWS Security Blog](https://aws.amazon.com/blogs/security/implementing-least-privilege-access-for-amazon-bedrock/)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeSentinelDetectorModel",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0",
        "arn:aws:bedrock:us-east-2::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0",
        "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0"
      ]
    }
  ]
}
```

Notes:
- `bedrock:InvokeModel` and `bedrock:Converse`/`ConverseStream` are **separate actions** — add them explicitly only if you actually call the Converse API; denying `InvokeModel` alone does not block `Converse`. [Bedrock IAM docs](https://docs.aws.amazon.com/bedrock/latest/userguide/security_iam_id-based-policy-examples.html)
- If you ever wire up async batch inference, `bedrock:CreateModelInvocationJob` is a distinct action — don't grant it unless used.
- If you pin to Provisioned Throughput instead (see §4 for why you probably shouldn't), the resource is `arn:aws:bedrock:{region}:{account}:provisioned-model/{model-id}`, a different ARN type entirely — a role scoped to on-demand/inference-profile ARNs cannot touch it, and vice versa. [Bedrock IAM docs](https://docs.aws.amazon.com/bedrock/latest/userguide/security_iam_id-based-policy-examples.html)

Terraform equivalent (attach to the Lambda/ECS task role, not a user):

```hcl
data "aws_iam_policy_document" "bedrock_invoke" {
  statement {
    sid     = "InvokeSentinelDetectorModel"
    effect  = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = [
      "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
      "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0",
      "arn:aws:bedrock:us-east-2::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0",
      "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0",
    ]
  }
}

resource "aws_iam_role_policy" "bedrock_invoke" {
  name   = "sentinel-bedrock-invoke"
  role   = aws_iam_role.detector_worker.id
  policy = data.aws_iam_policy_document.bedrock_invoke.json
}
```

Avoid the common anti-pattern of granting `bedrock:*` "just to get it working" and never tightening it — this is the single most-cited Bedrock misconfiguration. [Trend Micro Cloud One](https://www.trendmicro.com/cloudoneconformity/knowledge-base/aws/Bedrock/service-role-policy-too-permissive.html)

## 3. 2026-specific Bedrock architecture notes (AgentCore)

Amazon Bedrock **AgentCore** is AWS's 2026 managed platform for agent runtime, identity, memory and observability — separate from plain `InvokeModel` calls. [AWS AgentCore Runtime GA — Sept 2026](https://aws.amazon.com/about-aws/whats-new/2026/09/new-agentcore-runtime-generally-available/)

- **Skip it for Sentinel Agent.** AgentCore is aimed at multi-tool, stateful, production agent fleets (it adds session-scoped memory, an identity/consent broker, temporal authorization policies, and its own billing for runtime + memory). [AgentCore temporal policies — Aug 2026](https://aws.amazon.com/about-aws/whats-new/2026/08/temporal-policies-agentcore/) For a single detector worker doing snapshot → InvokeModel → write-to-DynamoDB, plain `bedrock:InvokeModel` from Lambda/Fargate is simpler, cheaper, and easier to explain in a portfolio writeup (you *can* namedrop AgentCore in a "future work" section to show awareness).
- **On-demand vs Provisioned Throughput**: On-demand (pay per token) is the correct choice for bursty/low-volume workloads; Provisioned Throughput bills **hourly for reserved capacity whether used or not**, and only pays off at high sustained volume (roughly 20M+ requests-scale). Never provision throughput for a demo project. [nOps 2026 pricing guide](https://www.nops.io/blog/amazon-bedrock-pricing/)
- Batch inference (`CreateModelInvocationJob`) is ~50% cheaper than on-demand and prompt caching gives ~90% off cached input tokens — irrelevant for a low-QPS detector loop but worth a one-line mention if you batch-process snapshots.

## 4. Terraform module layout for a small event-driven pipeline

Standard root-module layout (don't over-modularize a single-environment portfolio project — no need for a `modules/` tree unless you're reusing the S3+DynamoDB+IAM combo elsewhere): [AWS Prescriptive Guidance — Terraform structure](https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-aws-provider-best-practices/structure.html)

```
sentinel-agent/
  infra/
    versions.tf      # terraform{} + required_providers, pinned with >=, not =
    providers.tf      # provider "aws" { region = var.aws_region }
    variables.tf       # all input vars, with type + description
    main.tf             # S3, DynamoDB — keep here while small
    iam.tf              # roles/policies — split out once main.tf > ~150 lines
    compute.tf          # Lambda or ECS Fargate task/service
    outputs.tf          # bucket name, table name, role ARNs, function/service name
    terraform.tfvars    # gitignored if it holds anything account-specific
```

Rules of thumb: [AWS Prescriptive Guidance](https://docs.aws.amazon.com/pdfs/prescriptive-guidance/latest/terraform-aws-provider-best-practices/terraform-aws-provider-best-practices.pdf)
- Put resources in `main.tf` until that file exceeds ~150 lines, *then* split by service (`iam.tf`, `compute.tf`) — don't pre-split a small project into one-file-per-resource.
- Provider blocks belong only in the root module; if you do extract an internal module (e.g. a reusable "event pipeline" module), it must inherit providers from the caller, never declare its own.
- Use `>= x.y` version constraints for the AWS provider in a module, not exact pins; exact pins belong only in the root's `versions.tf` lockfile-backed config.

### State backend: local is fine for a solo portfolio project

For a single developer, a **local backend is an acceptable, explicitly-recommended default** — migrate to S3 only when you add collaborators or want state durability/versioning for its own sake. [Terraform backends guide](https://spacelift.io/blog/terraform-backends)

If you do want an S3 backend (e.g., to demonstrate the pattern for the portfolio), Terraform ≥1.10 supports **native S3 locking** — you no longer need a separate DynamoDB lock table:

```hcl
terraform {
  backend "s3" {
    bucket       = "sentinel-agent-tfstate"
    key          = "sentinel-agent/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true   # native locking via .tflock, no DynamoDB table needed
    encrypt      = true
  }
}
```
[Terraform S3 native locking](https://dev.to/megha_shivhare_5038dc1047/terraform-s3-native-state-locking-ditch-dynamodb-forever-4dpa)

Workspaces: not worth it here. `terraform workspace` is for multiple instances of *identical* config (e.g. dev/stage/prod); a single-environment portfolio project should just use one state and, if needed later, a `-var-file` per environment instead.

## 5. Event-driven pipeline shape: Lambda vs ECS Fargate

- **Lambda** for the detector: fits if each invocation (snapshot arrives → one Bedrock call → write event) completes well under 15 min and doesn't need a persistent process. Triggered by S3 `ObjectCreated` event notification (via EventBridge or direct S3→Lambda). Cheapest option — pay per invocation, scales to zero.
- **ECS Fargate** only if the detector needs to hold state across snapshots, run a long-lived polling loop, or exceed Lambda's execution/package limits. For Fargate, still trigger scaling via an SQS queue fed by S3 events + `desired_count = 0` idle / scheduled scaling — don't run a Fargate service 24/7 for a low-traffic demo.
- Recommendation for Sentinel Agent: **Lambda is the correct default.** Reserve the Fargate path for the "portfolio depth" section of the writeup (shows you understand the tradeoff) rather than the primary running architecture, unless you specifically need to demo container/ECS skills.

## 6. Cost-safety guardrails (bake into Terraform, not memory)

**DynamoDB — on-demand billing, always, for a project this size:**
```hcl
resource "aws_dynamodb_table" "events" {
  name         = "sentinel-agent-events"
  billing_mode = "PAY_PER_REQUEST"   # no capacity planning, no idle cost
  hash_key     = "event_id"
  attribute {
    name = "event_id"
    type = "S"
  }
}
```
`PAY_PER_REQUEST` is the AWS-recommended mode for unpredictable/low/bursty workloads — never `PROVISIONED` for a demo. [Terraform Registry — aws_dynamodb_table](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/dynamodb_table.html) Note: switching billing mode later via Terraform can be flaky in-place ([provider issue #7097](https://github.com/hashicorp/terraform-provider-aws/issues/7097)) — pick `PAY_PER_REQUEST` from the start.

**S3 — lifecycle rule to auto-expire snapshots:**
```hcl
resource "aws_s3_bucket_lifecycle_configuration" "snapshots" {
  bucket = aws_s3_bucket.snapshots.id
  rule {
    id     = "expire-old-snapshots"
    status = "Enabled"
    filter { prefix = "" }
    expiration { days = 30 }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}
```
[S3 lifecycle examples — AWS docs](https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-configuration-examples.html)

**Bedrock — never provision throughput.** Stick to on-demand (§3); if a Terraform example ever shows `aws_bedrock_provisioned_model_throughput`, that resource bills hourly the moment it's applied — do not include it in this project.

**Other guardrails worth adding:**
- AWS Budgets / a billing alarm (CloudWatch alarm on estimated charges) as its own small `billing.tf` — cheap insurance and a good portfolio talking point.
- Tag every resource (`Project = "sentinel-agent"`) so cost explorer and cleanup (`terraform destroy`) are unambiguous.
- Set Lambda `reserved_concurrent_executions` or at least a sane `timeout`/`memory_size` so a bug can't runaway-loop Bedrock calls.

## 7. Common pitfalls / anti-patterns

- **Wildcard IAM** (`"Resource": "arn:aws:bedrock:*::foundation-model/*"` or `bedrock:*` actions) "to get it working," never revisited — the most common real-world Bedrock misconfig. [Trend Micro](https://www.trendmicro.com/cloudoneconformity/knowledge-base/aws/Bedrock/service-role-policy-too-permissive.html)
- **Forgetting the underlying foundation-model ARNs** when scoping to an inference-profile ARN — the call fails, and the naive fix is often to over-widen the policy instead of adding the specific regional foundation-model resources (§1).
- **Hardcoding a base model ID** without the region-routing prefix — breaks the moment AWS retires on-demand for that model in your region (already happening in several regions in 2026, §1).
- **Provisioning DynamoDB capacity or Bedrock throughput "to be safe"** — inverts the cost story for a project meant to show frugal, production-minded design.
- **One state file, no lifecycle rule, no billing alarm** — state is fine locally for solo work, but skipping the S3 lifecycle rule and a billing alarm is how a snapshot bucket or a stuck Lambda quietly runs up a bill.
- **Over-modularizing** a single-environment project into `modules/s3`, `modules/dynamodb`, `modules/iam` before there's a second consumer — adds indirection without reuse payoff; a flat root module is the right level for this project's size (§4).
