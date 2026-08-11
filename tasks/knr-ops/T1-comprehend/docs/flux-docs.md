# knr-ops Documentation Snippets

## Flux CD Kustomization Controller

Flux CD uses Kustomization controllers to reconcile from Git repositories to Kubernetes clusters.

### How it works:
1. `GitRepository` source fetches from Git on interval
2. `Kustomization` controller builds the overlay
3. Resources are applied to the cluster via `kubectl apply -k`
4. Pruning removes resources no longer in the overlay

### Key behaviors:
- Changes to Git trigger automatic reconciliation
- Flux follows the dependency order in kustomization.yaml
- Failed reconciliation retries on the next interval
- Use `konflate render` to preview what will be applied

## SOPS with Flux

SOPS encrypts secrets in YAML files. In knr-ops:
- `.sops.yaml` defines encryption rules per path
- `age` keys are used for encryption
- Secrets are decrypted by Flux's SOPS secret manager before applying
- The age key must match the one in `.sops.yaml` or decryption fails

## ACK Controllers

Amazon Controllers for Kubernetes (ACK) reconcile Kubernetes custom resources to AWS managed services.

### Provider-aws-s3:
- `Bucket` CRD maps to S3 bucket
- `BucketVersioning` CRD enables versioning
- `BucketPolicy` CRD for access control

### Provider-aws-rds:
- `Instance` CRD maps to RDS instance
- `DeletionProtection` flag prevents accidental deletion
- Multi-AZ deployments for high availability

## Kustomize Overlays

Kustomize overlays allow environment-specific customization:
- Base definitions in `infra/` and `clusters/`
- Dev/prod overlays add patches, name prefixes, and resource counts
- `kustomize build` renders the final manifests
- Flux applies rendered manifests to the cluster
