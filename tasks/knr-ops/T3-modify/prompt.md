## Task: Add prod overlay changes without touching dev

**Stack:** knr-ops (Flux + kustomize)

You are given an knr-ops GitOps repository with dev/prod overlays.

### Current State

- `overlays/dev/kustomization.yaml` - dev overlay
- `overlays/prod/kustomization.yaml` - prod overlay
- Base configs in `clusters/`, `infra/`

### Your Task

Add the following changes to the prod overlay ONLY:
1. Change app deployment replicas from 2 to 4
2. Change RDS instance class from `db.t3.micro` to `db.t3.medium`
3. Enable multi-AZ for RDS
4. Add S3 cross-region replication to us-west-2

The dev overlay should remain unchanged. Your changes must:
- Only modify `overlays/prod/kustomization.yaml`
- Use kustomize patches (strategic merge or JSON patch)
- Ensure prod changes do not affect dev

### Context Files

{{scenario_spec}}
