# T1-comprehend Reference Answer Key

## Expected answers for Terraform plan behavior prediction

### Scenario: Variable flips (instance_class changes, state file deleted, workspace changes)

**Q1: What does the next plan show after instance_class changes?**
**Answer:** `terraform plan` shows:
- `aws_db_instance.main` will be replaced (instance_class is a required replacement attribute)
- 1 resource to add, 1 resource to destroy
- Detailed diff showing old instance_class → new instance_class

**Q2: What happens if the state file is deleted?**
**Answer:** Terraform thinks all resources need to be created since it has no record of existing infrastructure. Running `terraform plan` shows everything as `+` (create). If `terraform apply` runs, it will try to create resources that already exist, likely failing on unique name constraints (e.g., bucket name already taken).

**Q3: How does Terraform handle the RDS instance class change?**
**Answer:** Terraform will replace the RDS instance (destroy then create). This is a destructive operation that causes data loss unless `migrate_to` or backup/restore is used.

**Q4: What is the difference between state and configuration?**
**Answer:** Configuration (.tf files) defines what should exist. State (.terraform.tfstate) records what actually exists. The plan computes the difference between state and configuration to determine what actions are needed. State is the source of truth for "what's deployed" while configuration is the desired state.
