terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0"
    }
  }

  # Local state: a single-developer project (see the aws-bedrock-terraform skill, §4).
}
