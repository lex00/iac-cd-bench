## Task: Semantic prediction quiz — Pulumi Python runtime behavior

**Stack:** pulumi-python (AWS classic provider)

You are given a Pulumi program (`__main__.py`, `Pulumi.yaml`,
`Pulumi.prod.yaml` in the workspace). The `prod` stack is deployed and state
matches the code. Answer questions about what Pulumi will ACTUALLY do.
Each question is independent.

### Questions

Q1. `pulumi destroy` is run on the prod stack. Does it complete? If not,
which resource blocks it and why?

Q2. The bucket resource name string in code is changed from
`"artifacts"` to `"artifact-store"` (the first constructor argument only;
`bucket=` stays the same). What does `pulumi up` plan for this resource:
update in-place, replacement, or no-op?

Q3. In the exports, `db_password_plain` re-exports `db_password` (which came
from `config.require_secret`). In `pulumi stack output` WITHOUT
`--show-secrets`, is the value readable plaintext or masked as a secret?

Q4. The `logs` bucket has `delete_before_replace=True` and
`depends_on=[artifacts]`. If a change forces `logs` to be replaced, in what
order do its delete and create happen, and does the default
create-before-delete apply?

Q5. `config.get_int("replicas")` — `Pulumi.prod.yaml` sets `replicas: 4` but
the code default is `or 2`. What value does `replicas` have on the prod
stack, and would it change if the config key were removed?

Q6. `policy` uses `artifacts.arn.apply(lambda arn: ...)`. During
`pulumi preview` on a FRESH stack (nothing deployed yet), is the lambda
guaranteed to run with a concrete ARN string, or can the policy value be
unknown at preview time?

Q7. `print(f"bucket is {artifacts.bucket}")` is added at the end of the
program. Does it print the actual bucket name during `pulumi up`, or
something else? Why?

### Answer format

Return ONLY a fenced JSON code block named `answers.json` in exactly this
shape:

```json
{
  "q1": {"completes": "<true|false>", "blocking_resource": "<name or none>"},
  "q2": "update-in-place | replace | no-op",
  "q3": "plaintext | masked",
  "q4": "delete-then-create | create-then-delete",
  "q5": {"value": 0, "changes_if_removed": "<true|false>"},
  "q6": "concrete | unknown",
  "q7": "actual-name | output-repr"
}
```

For q1 `"completes"` and q5 `"changes_if_removed"` use JSON booleans. For q5
`"value"` use a JSON number.

### Context Files

{{scenario_spec}}
