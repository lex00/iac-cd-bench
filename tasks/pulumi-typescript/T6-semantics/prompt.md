## Task: Semantic prediction quiz — Pulumi TypeScript runtime behavior

**Stack:** pulumi-typescript (AWS classic provider)

You are given a Pulumi TS program (`index.ts`, `Pulumi.yaml`,
`Pulumi.prod.yaml` in the workspace). The `prod` stack is deployed and state
matches the code. Answer questions about what Pulumi will ACTUALLY do.
Each question is independent.

### Questions

Q1. `const bucketMsg = "bucket is " + artifacts.bucket` — at runtime during
`pulumi up`, what does the string contain: the actual bucket name, or
something else? What TypeScript type does `artifacts.bucket` have here?

Q2. `pulumi destroy` runs on prod. Does it complete, and if not which
resource blocks it?

Q3. The `cache` bucket must be replaced (its `bucket` name arg changes). Given
`deleteBeforeReplace: true`, describe the operation order and one practical
risk of this mode compared to Pulumi's default.

Q4. `export const tokenOut = apiToken` re-exports a `requireSecret` value.
In `pulumi stack output` WITHOUT `--show-secrets`, is it readable or masked?

Q5. `logRetention` uses `config.getNumber("logRetention") ?? 30` and
`Pulumi.prod.yaml` does NOT set the key. What is the value on prod, and is
this a config error at runtime? (`getNumber` vs `requireNumber` semantics.)

Q6. The logical name of the `artifacts` bucket resource changes from
`"artifacts"` to `"artifactStore"` in code (no aliases added). What does
`pulumi up` plan, and what single ResourceOption would make it a no-op
rename instead?

Q7. `policy` reads `artifacts.arn.apply(...)`. On a fresh stack's
`pulumi preview`, is the policy JSON computed with the real ARN, or is it
unknown until `pulumi up` creates the bucket?

### Answer format

Return ONLY a fenced JSON code block named `answers.json` in exactly this
shape:

```json
{
  "q1": {"contains": "actual-name | output-repr", "type": "<TS type>"},
  "q2": {"completes": "<true|false>", "blocking_resource": "<name or none>"},
  "q3": {"order": "delete-then-create | create-then-delete", "risk": "<short>"},
  "q4": "readable | masked",
  "q5": {"value": 0, "error": "<true|false>"},
  "q6": {"plan": "replace | update | no-op", "fix_option": "<ResourceOption name>"},
  "q7": "real-arn | unknown"
}
```

For booleans use JSON true/false. For q5 `"value"` use a JSON number.

### Context Files

{{scenario_spec}}
