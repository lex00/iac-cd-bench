## Task: Add a new ACK-managed S3 bucket + IRSA Role + Flux kustomization

**Stack:** knr-ops (Flux + kustomize + ACK)

You are given an knr-ops GitOps repository. The repo uses:
- Flux CD to reconcile from Git
- AWS Controllers for Kubernetes (ACK) for AWS resources
- SOPS for secret encryption

### Current State

The repo has:
- `infra/s3/` - existing S3 bucket manifest
- `infra/iam/` - IAM resources
- `overlays/dev/` and `overlays/prod/` - environment overlays
- `flux/kustomizations.yaml` - Flux kustomizations

### Your Task

Add a new S3 bucket for "logs" with the following requirements:
1. Bucket name: `myapp-logs-{env}` (where {env} is dev/prod)
2. Versioning enabled
3. Server-side encryption with AES256
4. No public access (public access block)
5. An IAM role for IRSA (IAM Roles for Service Accounts) that allows the bucket to be read/write
6. A Flux kustomization that reconciles the logs bucket separately

The bucket should be added idiomatically following knr-ops patterns:
- Use ACK S3 CRDs (s3.aws.upbound.io)
- Use kustomize overlays for dev/prod differentiation
- Use SOPS for any sensitive values
- Ensure the Flux kustomization references the correct source

### Context Files

{{scenario_spec}}
