# Golden answers — pulumi-typescript T6-semantics

```json
{
  "q1": {"contains": "output-repr", "type": "Output<string>"},
  "q2": {"completes": false, "blocking_resource": "artifacts"},
  "q3": {"order": "delete-then-create", "risk": "downtime window between delete and create (resource briefly does not exist)"},
  "q4": "masked",
  "q5": {"value": 30, "error": false},
  "q6": {"plan": "replace", "fix_option": "aliases"},
  "q7": "unknown"
}
```

## Rationale

- **q1**: String concatenation with an `Output<string>` does not unwrap it — the string contains the Output object's toString (Pulumi even warns "Calling [toString] on an [Output<T>] is not supported"). The declared type of `artifacts.bucket` is `pulumi.Output<string>`.
- **q2**: `protect: true` on `artifacts` blocks `pulumi destroy` until unprotected.
- **q3**: `deleteBeforeReplace: true` deletes the old bucket first, then creates the new one — the practical risk is a downtime/data-loss window (default create-before-delete avoids it).
- **q4**: Secretness flows through exports — masked without `--show-secrets`.
- **q5**: `getNumber` returns undefined when unset (no error); `?? 30` yields 30. `requireNumber` would throw.
- **q6**: Logical-name change = new URN = replace (delete+create). The `aliases` ResourceOption maps the old URN to the new one, making it a no-op.
- **q7**: On a fresh stack the ARN is unknown at preview; the applied policy JSON is unknown until the bucket exists.
