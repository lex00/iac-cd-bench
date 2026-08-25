# GOLDEN: single for_each-driven aws_eks_node_group, zero-diff state moves
# from the seed's duplicated dev/prod resources via `moved` blocks.

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

locals {
  node_groups = {
    dev = {
      cluster_name  = "myapp-dev"
      instance_type = "t3.medium"
      desired_size  = 2
      min_size      = 1
      max_size      = 3
    }
    prod = {
      cluster_name  = "myapp-prod"
      instance_type = "t3.large"
      desired_size  = 4
      min_size      = 2
      max_size      = 6
    }
  }
}

resource "aws_eks_node_group" "this" {
  for_each = local.node_groups

  cluster_name    = each.value.cluster_name
  node_group_name = "${each.value.cluster_name}-nodes"
  node_role_arn   = var.node_role_arn
  subnet_ids      = var.subnet_ids

  instance_types = [each.value.instance_type]

  scaling_config {
    desired_size = each.value.desired_size
    min_size     = each.value.min_size
    max_size     = each.value.max_size
  }
}

moved {
  from = aws_eks_node_group.dev
  to   = aws_eks_node_group.this["dev"]
}

moved {
  from = aws_eks_node_group.prod
  to   = aws_eks_node_group.this["prod"]
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "node_role_arn" {
  type    = string
  default = "arn:aws:iam::123456789012:role/eks-node-role"
}

variable "subnet_ids" {
  type    = list(string)
  default = ["subnet-aaaa", "subnet-bbbb"]
}
