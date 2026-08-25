## Task: Refactor duplicated dev/prod blocks

**Stack:** Terraform

### Current State

`main.tf` declares the EKS managed node group twice, once per environment, identical apart from sizing:

- `aws_eks_node_group.dev` — cluster `myapp-dev`, instance type `t3.medium`, `desired_size = 2`, `min_size = 1`, `max_size = 3`
- `aws_eks_node_group.prod` — cluster `myapp-prod`, instance type `t3.large`, `desired_size = 4`, `min_size = 2`, `max_size = 6`

### Your Task

Refactor the two node group resources into a single `aws_eks_node_group` resource driven by `for_each` over a map keyed by environment (`dev`, `prod`), preserving each environment's existing sizing exactly. State moves must be zero-diff: add `moved` blocks so `terraform plan` shows no destroy/create for either node group after the refactor.

{{scenario_spec}}
