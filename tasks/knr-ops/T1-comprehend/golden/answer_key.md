# T1-comprehend Reference Answer Key

## Expected answers for knr-ops delivery behavior prediction

### Scenario: PR merges Flux kustomization with RDS instance class change from db.t3.medium → db.t3.large

**Q1: Does the RDS instance get recreated?**
**Answer:** Yes — RDS instance class changes in AWS require a replacement (destroy + create), which is a destructive operation. Flux will reconcile this by applying the new spec, causing Terraform/ACK to destroy and recreate the instance.

**Q2: What reconciles first?**
**Answer:** S3 bucket versioning changes apply first (non-destructive), then RDS instance replacement begins. Flux reconciliation order follows the dependency graph in kustomization.yaml.

**Q3: What happens to in-flight requests during RDS replacement?**
**Answer:** In-flight requests fail with database connection errors during the brief window when the old instance is being destroyed and the new one is being created. This is a service disruption.

**Q4: How does Flux handle failed reconciliation?**
**Answer:** Flux retries on the next interval (default 1m0s). If the replacement fails (e.g., RDS still busy), Flux keeps retrying until success or timeout. The Kustomization status shows the last reconciliation state.

**Q5: What prevents this disruption in production?**
**Answer:** Blue/green deployment pattern with database replication, or using RDS multi-AZ failover where instance class changes happen during maintenance windows. For GitOps, the change should be reviewed via konflate to flag the destructive change before merge.
