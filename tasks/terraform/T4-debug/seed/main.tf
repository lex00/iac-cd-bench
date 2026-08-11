# SEED REPO: Terraform with circular dependency + count/for_each defect
# Defect 1: Circular dependency — output references resource before it's defined
# Defect 2: count vs for_each type mismatch

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

# DESTRUCTIVE CHANGE: missing deletion_protection flag
# CIRCULAR DEPENDENCY: outputs reference db_endpoint before instance exists
resource "aws_db_instance" "main" {
  identifier     = "${var.env}-db"
  allocated_storage = 20
  engine         = "postgres"
  engine_version = "16.1"
  instance_class = var.instance_class

  db_name  = var.db_name
  username = var.db_user
  password = var.db_password

  # count used instead of for_each — will fail when env changes
  count = length(var.envs)

  skip_final_snapshot = true
  deletion_protection = false  # Should be true for prod
}

# Circular dependency: this output references the instance before it exists in plan
output "db_endpoint" {
  value = aws_db_instance.main[0].endpoint
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "env" {
  type    = string
  default = "dev"
}

variable "envs" {
  type    = list(string)
  default = ["dev"]
}

variable "instance_class" {
  type    = string
  default = "db.t3.medium"
}

variable "db_name" {
  type    = string
  default = "appdb"
}

variable "db_user" {
  type    = string
  default = "app-user"
}

variable "db_password" {
  type      = string
  sensitive = true
}
