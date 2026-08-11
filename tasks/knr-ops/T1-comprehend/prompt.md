## Task: Predict delivery behavior from repo slice

**Stack:** knr-ops (Flux + kustomize + ACK)

You are given a slice of an knr-ops GitOps repository. The repo uses:
- Flux CD to reconcile from Git
- Cluster API (CAPI/CAPA) for EKS cluster provisioning
- AWS Controllers for Kubernetes (ACK) for S3, RDS, IAM
- SOPS for secret encryption
- kustomize overlays for dev/prod environments

### Repo Structure

```
clusters/eksa/          # CAPA cluster configs
infra/s3/bucket.yaml     # ACK S3 bucket
infra/rds/instance.yaml  # ACK RDS instance
infra/iam/access.yaml    # IAM user/role
infra/app/deployment.yaml # App deployment
overlays/dev/            # Dev overlay
overlays/prod/           # Prod overlay
flux/kustomizations.yaml # Flux kustomizations
```

### Scenario

A PR #42 is about to merge. It contains:
1. The RDS instance manifest has `instanceClass` changed from `db.t3.micro` to `db.t3.medium`
2. A new S3 bucket manifest is added in `infra/s3/`
3. The `prod` overlay kustomization has a new patch targeting the app deployment with `replicas: 4`

**Questions:**
1. What reconciles when PR #42 merges, and in what order?
2. Does the RDS instance get recreated? Why or why not?
3. What happens to the S3 bucket if its manifest is deleted from Git?
4. How does Flux handle the prod-only replica change?
5. What role does the `dependsOn` relationship between kustomizations play?

### Context Files

{{scenario_spec}}
