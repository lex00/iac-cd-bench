# T5-review Reference Answer Key

## Expected security flags for knr-ops PR diff review

### Issues to identify (ranked by severity):

**CRITICAL (P0): Plaintext secret in Kustomization secretGenerator**
- `secretGenerator` with `password=dev-db-password` in plaintext
- **Impact:** Database credentials exposed in Git history
- **Fix:** Use SOPS encryption or external secret management (e.g., AWS Secrets Manager with IRSA)

**HIGH (P1): RDS deletion_protection set to false in prod**
- Prod RDS instance missing deletion protection
- **Impact:** Accidental `kubectl delete` or Flux reconciliation could destroy production database permanently
- **Fix:** Set `deletionProtection: true` for prod overlay

**MEDIUM (P2): Bucket versioning disabled in prod overlay**
- Prod S3 bucket has `versioning.status: Suspended`
- **Impact:** No recovery from accidental deletions; compliance violation for audit requirements
- **Fix:** Enable versioning: `versioning.status: Enabled`

**LOW (P3): Missing security context in Deployment**
- Container running as root, no readOnlyRootFilesystem
- **Impact:** Privilege escalation if container compromised
- **Fix:** Add securityContext with runAsNonRoot and readOnlyRootFilesystem

### Expected remediation steps:
1. Remove plaintext secrets from secretGenerator, replace with SOPS-encrypted manifests
2. Add deletion_protection: true to prod overlay patch
3. Enable versioning in prod S3 bucket config
4. Add PodSecurityContext to deployment.yaml
