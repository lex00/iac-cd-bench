variable "environment" {
  description = "Environment name (dev | prod)"
  type        = string
}

variable "cluster_name" {
  description = "Name of the EKS cluster"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type for node group"
  type        = string
}

variable "desired_nodes" {
  description = "Desired number of nodes"
  type        = number
}

variable "vpc_id" {
  description = "VPC ID for EKS"
  type        = string
}

variable "subnet_ids" {
  description = "Subnet IDs for EKS node group"
  type        = list(string)
}
