# T1-comprehend Reference Answer Key

## Expected answers for Pulumi Python/TypeScript preview behavior prediction

**Q1: Which property triggered the RDS replacement?**
**Answer:** The instanceClass property triggers replacement on RDS. Changing instance_class/instanceClass requires AWS to destroy and recreate the instance. This shows as `replace` in `pulumi preview`.

**Q2: What does `pulumi up --target` skip?**
**Answer:** `pulumi up --target aws:rds/instance:app-db` only applies changes to the specified RDS resource. Other resources that would be modified are skipped entirely. This is useful for targeted deployments but can leave the stack in an inconsistent state if dependencies exist.

**Q3: How does Pulumi handle secrets in outputs?**
**Answer:** Secrets are:
- Encrypted at rest in the state file
- Masked in CLI output as `(secret)`
- Available as `pulumi.Output<string>` that must be accessed via `.apply()`
- Exported as encrypted values that can only be read with proper encryption keys
- `config.requireSecret()` wraps values automatically for encryption

**Q4: What is Pulumi's preview lifecycle?**
**Answer:** `pulumi preview` simulates the deployment without applying changes:
1. Loads stack state
2. Computes diff between desired state (code) and actual state (state file)
3. Shows planned actions (create/update/delete/replace)
4. Returns without making any API calls to cloud providers
