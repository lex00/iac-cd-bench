# T5-review Reference Answer Key

## Expected security flags for Pulumi preview JSON review

### Issues to identify (ranked by severity):

**CRITICAL (P0): Secret exported as plaintext**
- `dbEndpoint` or password output contains unencrypted secret
- **Impact:** Secrets exposed in Pulumi state file and CI logs
- **Fix:** Use `config.requireSecret()` to wrap sensitive values; ensure exports are marked as secrets

**HIGH (P1): RDS instance replacement (data loss)**
- `replace aws:rds/instance:app-db` in preview
- **Impact:** Database replacement causes data loss
- **Fix:** Use `protect: true` flag or migrate data before replacement

**HIGH (P2): Missing `protect` flag on stateful resources**
- Stateful resources (RDS, S3 with data) not protected from deletion
- **Impact:** Accidental deletion during stack updates or deletes
- **Fix:** Add `opts=pulumi.Protect(true)` to stateful resources

**MEDIUM (P3): Security group overly permissive**
- Ingress rule allows 0.0.0.0/0 on database port
- **Impact:** Database accessible from internet
- **Fix:** Restrict to specific CIDR ranges

### Expected remediation steps:
1. Mark outputs as secrets: `pulumi.export("password", pulumi.secret(password_value))`
2. Add `protect: true` to RDS and S3 resources
3. Use `pulumi.Aliases` for resource migration without replacement
4. Restrict security group rules to specific CIDRs
