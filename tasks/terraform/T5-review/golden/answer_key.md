# T5-review Reference Answer Key

## Expected security flags for Terraform plan JSON review

### Issues to identify (ranked by severity):

**CRITICAL (P0): DB instance destroy + create (data loss)**
- `aws_db_instance.main` shows replace action
- **Impact:** Database recreation loses all data
- **Fix:** Use `migrate_to` parameter or blue/green migration with snapshot restore

**HIGH (P1): Security group 0.0.0.0/0 ingress**
- New ingress rule opens port 5432 to entire internet
- **Impact:** PostgreSQL accessible from any IP; data breach risk
- **Fix:** Restrict to CIDR ranges (e.g., VPC internal subnet or specific bastion IP)

**HIGH (P2): Plaintext password in tfvars**
- `db_password = "my-super-secret-password"` in prod.tfvars
- **Impact:** Credentials in Git history; anyone with repo access can read DB password
- **Fix:** Use `sops-terraform` or AWS Secrets Manager reference; add to .gitignore

**MEDIUM (P3): skip_final_snapshot = true on prod RDS**
- Prod database will not create final snapshot before destruction
- **Impact:** No recovery point if instance is accidentally destroyed
- **Fix:** Set `skip_final_snapshot = false` for prod

### Expected remediation steps:
1. Add `migrate_to` or `copy_tags_to_snapshot` for zero-downtime migration
2. Replace 0.0.0.0/0 with specific VPC/subnet CIDR ranges
3. Encrypt tfvars with SOPS; move passwords to AWS Secrets Manager
4. Enable final snapshots for prod databases
