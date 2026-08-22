# Golden answers — terraform T6-semantics

```json
{
  "q1": "error",
  "q2": ["aws_subnet.private[2]"],
  "q3": "destroy-and-recreate-all",
  "q4": "no-change",
  "q5": "no-change",
  "q6": "update-in-place",
  "q7": {"completes": false, "blocking_resource": "aws_s3_bucket.artifacts"}
}
```

## Rationale

- **q1**: `bucket` forces replacement (name change), but `prevent_destroy = true` makes Terraform ERROR during plan: "Instance cannot be destroyed".
- **q2**: `count` shrink destroys the highest index: `aws_subnet.private[2]`. Indexes 0 and 1 are untouched.
- **q3**: Switching count→for_each changes addresses; without moved blocks Terraform sees 3 deletes + 3 creates (destroy and recreate all).
- **q4**: `ignore_changes = [engine_version]` suppresses config drift on that attribute — plan shows no change for it.
- **q5**: Same lifecycle rule ignores remote drift on engine_version — no change proposed.
- **q6**: `instance_class` is an updatable RDS attribute (ModifyDBInstance) — in-place update.
- **q7**: `terraform destroy` fails on `aws_s3_bucket.artifacts` because `prevent_destroy = true` aborts the plan with an error.
