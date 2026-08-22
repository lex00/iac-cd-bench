# Golden answers — knr-ops T6-semantics

```json
{
  "q1": "updated-in-place",
  "q2": {"kustomization": "infra-aws", "outcome": "pruned"},
  "q3": "deleted",
  "q4": "retained",
  "q5": {"changes": false, "reason": "apps-prod is suspended (suspend: true), so Flux does not apply prod overlay changes"},
  "q6": {"apps_dev_reconciles": false, "reason": "apps-dev dependsOn infra-aws; infra-aws never becomes Ready because its healthCheck on app-artifacts fails"},
  "q7": ["infra-controllers", "infra-aws", "apps-dev"]
}
```

## Rationale

- **q1**: `dbInstanceClass` is a mutable RDS attribute; ACK issues ModifyDBInstance. The instance identity (`dbInstanceIdentifier`) is unchanged — in-place update, possibly with restart, never replacement.
- **q2**: The Bucket objects are delivered by `infra-aws` (path ./infra/aws) which has `prune: true` — objects removed from source get garbage-collected (pruned).
- **q3**: `app-artifacts` has no deletion-policy annotation; ACK default deletion policy is `delete`, so deleting the K8s Bucket resource deletes the AWS bucket.
- **q4**: The `services.k8s.aws/deletion-policy: retain` annotation makes ACK orphan the AWS resource — the RDS database survives.
- **q5**: `apps-prod` has `suspend: true`; suspended Kustomizations record new revisions but apply nothing.
- **q6**: `apps-dev` has `dependsOn: [infra-aws]`. `infra-aws` has a healthCheck on Bucket `app-artifacts`; if it never becomes ready, `infra-aws` never reports Ready and `apps-dev` stays blocked (dependency gate).
- **q7**: Dependency chain: `infra-controllers` → `infra-aws` (dependsOn infra-controllers) → `apps-dev` (dependsOn infra-aws).
