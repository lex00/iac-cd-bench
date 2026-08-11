## Task: Review Terraform plan for hidden destructive changes

**Stack:** Terraform

Review a tfplan JSON output with 40 changes:
- DB recreate (destroy + create) hidden among no-op changes
- 0.0.0.0/0 ingress added to security group

{{scenario_spec}}
