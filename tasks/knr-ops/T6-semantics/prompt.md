## Task: Semantic prediction quiz — Flux + ACK delivery behavior

**Stack:** knr-ops (Flux + kustomize + ACK)

You are given the live state of a GitOps repository slice (below). Answer the
questions about what the toolchain will ACTUALLY do. These are questions about
runtime semantics, not syntax.

### Repo files

The workspace contains:

- `flux/kustomizations.yaml` — four Flux Kustomizations: `infra-controllers`,
  `infra-aws`, `apps-dev`, `apps-prod`
- `infra/aws/rds-instance.yaml` — ACK DBInstance `app-db`
- `infra/aws/s3-buckets.yaml` — ACK Buckets `app-artifacts`, `app-logs`

### Questions

Q1. A commit changes `spec.dbInstanceClass` from `db.t3.micro` to
`db.m5.large` in `rds-instance.yaml`. After Flux reconciles and ACK applies
the change, is the RDS instance REPLACED (destroyed and recreated with a new
identity) or UPDATED IN-PLACE (same instance identity, possibly with downtime)?

Q2. The file `infra/aws/s3-buckets.yaml` is deleted entirely from Git and the
commit merges. The `app-artifacts` Bucket manifest is gone from the source.
Name the Flux Kustomization whose configuration decides what happens to the
Bucket objects in the cluster, and state what happens to them.

Q3. After the deletion in Q2 is processed, does the AWS S3 bucket
`knr-app-artifacts-prod` still exist in AWS? Answer for the default ACK
deletion policy given the manifests as written.

Q4. The DBInstance `app-db` carries the annotation
`services.k8s.aws/deletion-policy: retain`. If the DBInstance manifest is
removed from Git and pruned from the cluster, does the actual RDS database
in AWS get deleted?

Q5. A commit touches only `overlays/prod/`. Given the `apps-prod`
Kustomization spec as written, does anything change in the cluster? Why or
why not?

Q6. `infra-aws` has `dependsOn: [infra-controllers]` and a `healthChecks`
entry on Bucket `app-artifacts`. If the `app-artifacts` Bucket never becomes
ready, what happens to `apps-dev`? Does it reconcile?

Q7. In what order do these Kustomizations reconcile on a fresh cluster
bootstrap: `apps-dev`, `infra-aws`, `infra-controllers`? (`apps-prod` is
excluded — see its spec.)

### Answer format

Return ONLY a fenced JSON code block named `answers.json` in exactly this
shape (keys q1..q7, values as specified):

```json
{
  "q1": "replaced | updated-in-place",
  "q2": {"kustomization": "<name>", "outcome": "pruned | orphaned"},
  "q3": "exists | deleted",
  "q4": "deleted | retained",
  "q5": {"changes": "<true|false>", "reason": "<short>"},
  "q6": {"apps_dev_reconciles": "<true|false>", "reason": "<short>"},
  "q7": ["first", "second", "third"]
}
```

Replace each placeholder with your answer. For q5 `"changes"` and q6
`"apps_dev_reconciles"` answer with JSON booleans (true/false). For q7 list
the three kustomization names in reconcile order.

### Context Files

{{scenario_spec}}
