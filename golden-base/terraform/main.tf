# =============================================================================
# Provider configuration and backend
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = var.state_bucket_name
    key            = "infrastructure/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = var.state_dynamodb_table
    encrypt        = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "canonical-scenario"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# =============================================================================
# Secondary provider for cross-region replication (prod only)
# =============================================================================

provider "aws" {
  alias  = "us_west_2"
  region = "us-west-2"
}
