# Golden answers — pulumi-python T6-semantics

```json
{
  "q1": {"completes": false, "blocking_resource": "artifacts"},
  "q2": "replace",
  "q3": "masked",
  "q4": "delete-then-create",
  "q5": {"value": 4, "changes_if_removed": true},
  "q6": "unknown",
  "q7": "output-repr"
}
```

## Rationale

- **q1**: `artifacts` has `protect=True`; destroy fails until the protection is lifted (`pulumi state unprotect` or opts change).
- **q2**: The logical resource name is part of the URN; renaming it makes Pulumi see delete+create — a replacement (aliases would avoid it).
- **q3**: Secret-ness propagates through exports; without `--show-secrets` the output is masked.
- **q4**: `delete_before_replace=True` inverts Pulumi's default create-before-delete: old bucket is deleted first, then the new one created.
- **q5**: Stack config wins: 4. Removing the key falls back to the code default 2 — the value changes.
- **q6**: On a fresh stack the ARN is unknown at preview; apply lambdas may not run / run with unknowns, so the policy value is unknown until up.
- **q7**: `artifacts.bucket` is an Output; f-string interpolation prints the Output object representation, not the value (must use .apply or pulumi.Output.format).
