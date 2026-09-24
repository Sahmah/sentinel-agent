provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "sentinel-agent"
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
