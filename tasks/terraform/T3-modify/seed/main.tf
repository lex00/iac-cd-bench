# SEED REPO: duplicated dev/prod EKS node group blocks (anti-pattern to
# refactor into a single for_each-driven resource).

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

resource "aws_eks_node_group" "dev" {
  cluster_name    = "myapp-dev"
  node_group_name = "myapp-dev-nodes"
  node_role_arn   = var.node_role_arn
  subnet_ids      = var.subnet_ids

  instance_types = ["t3.medium"]

  scaling_config {
    desired_size = 2
    min_size     = 1
    max_size     = 3
  }
}

resource "aws_eks_node_group" "prod" {
  cluster_name    = "myapp-prod"
  node_group_name = "myapp-prod-nodes"
  node_role_arn   = var.node_role_arn
  subnet_ids      = var.subnet_ids

  instance_types = ["t3.large"]

  scaling_config {
    desired_size = 4
    min_size     = 2
    max_size     = 6
  }
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
