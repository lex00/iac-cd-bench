## Task: Review PR diff for security issues

**Stack:** knr-ops (Flux + kustomize + konflate)

You are given a PR diff for an knr-ops GitOps repository. The diff shows changes to:
- RDS instance configuration
- S3 bucket policy
- App deployment manifests

### PR Diff Preview

The rendered diff shows:
1. RDS instance class change (no issue)
2. A new S3 bucket policy that grants public read access
3. An app deployment with plaintext password in env vars
4. Missing resource limits on containers

### Your Task

Review the PR diff and identify security issues. Rank them by severity and provide:
1. What security issues exist?
2. Which are critical vs warning vs info?
3. What should be changed before merge?

### Context Files

{{scenario_spec}}
