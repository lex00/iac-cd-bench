terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "eu-north-1"
}

variable "env" {
  type    = string
  default = "prod"
}

variable "az_count" {
  type    = number
  default = 3
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_s3_bucket" "artifacts" {
  bucket = "knr-artifacts-${var.env}"

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Env = var.env
  }
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_subnet" "private" {
  count             = var.az_count
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(aws_vpc.main.cidr_block, 4, count.index)
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name = "private-${count.index}"
  }
}

resource "aws_vpc" "main" {
  cidr_block = "10.40.0.0/16"

  tags = {
    Name = "main-${var.env}"
  }
}

resource "aws_db_instance" "app" {
  identifier              = "app-db-${var.env}"
  engine                  = "postgres"
  engine_version          = "15.4"
  instance_class          = "db.t3.micro"
  allocated_storage       = 20
  username                = "appadmin"
  manage_master_user_password = true
  skip_final_snapshot     = false
  final_snapshot_identifier = "app-db-${var.env}-final"

  lifecycle {
    ignore_changes = [engine_version]
  }
}

output "bucket_name" {
  value = aws_s3_bucket.artifacts.bucket
}
