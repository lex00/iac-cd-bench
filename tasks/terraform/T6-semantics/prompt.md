## Task: Semantic prediction quiz — Terraform plan/apply behavior

**Stack:** terraform (AWS provider)

You are given `main.tf` (in the workspace). State exists and matches the
config (fresh `terraform apply` just succeeded, 3 subnets exist). Answer
questions about what `terraform plan` / `apply` will ACTUALLY do for each
hypothetical change. Each question is independent — changes do not stack.

### Questions

Q1. `var.env` is changed from `"prod"` to `"staging"`. What does the plan
show for `aws_s3_bucket.artifacts`: an in-place update, a destroy-and-create
replacement, or an error before apply?

Q2. `var.az_count` is changed from 3 to 2. Which subnet instance(s) get
destroyed: `aws_subnet.private[0]`, `[1]`, or `[2]`?

Q3. The `aws_subnet.private` block is changed from `count` to
`for_each = toset(["a", "b", "c"])` (addresses become
`aws_subnet.private["a"]`...). Without any `moved` blocks or state mv, what
does the plan do with the three existing `aws_subnet.private[0..2]`
instances?

Q4. Someone edits `engine_version` from `"15.4"` to `"16.1"` in the config.
What does the plan show for `aws_db_instance.app`?

Q5. AWS releases a new engine minor and the actual RDS instance is
auto-upgraded out-of-band; the config still says `"15.4"`. On the next
`terraform plan` (with refresh), does Terraform propose to change
`engine_version` back?

Q6. `instance_class` is changed from `"db.t3.micro"` to `"db.m5.large"`.
Update in-place or replacement, per the AWS provider's schema for
`instance_class`?

Q7. A teammate runs `terraform destroy`. Does it complete? If not, which
resource blocks it and why?

### Answer format

Return ONLY a fenced JSON code block named `answers.json` in exactly this
shape:

```json
{
  "q1": "update-in-place | replace | error",
  "q2": ["<address(es) destroyed>"],
  "q3": "destroy-and-recreate-all | rename-in-place | error",
  "q4": "update-in-place | replace | no-change",
  "q5": "proposes-change | no-change",
  "q6": "update-in-place | replace",
  "q7": {"completes": "<true|false>", "blocking_resource": "<address or none>"}
}
```

For q2 list full resource addresses like `aws_subnet.private[2]`. For q7
`"completes"` use a JSON boolean.

### Context Files

{{scenario_spec}}
