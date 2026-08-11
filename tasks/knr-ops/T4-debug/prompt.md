## Task: Fix SOPS secret referencing wrong age key

**Stack:** knr-ops (Flux + SOPS + kustomize)

You are given an knr-ops GitOps repository with a seeded defect.

### Symptoms

Flux kustomizations are stuck in a failed state:
```
flux get kustomizations
NAME        READY   MESSAGE
myapp-dev   False   failed to merge command output: yaml: line 1: did not find expected key
myapp-prod  False   failed to merge command output: yaml: line 1: did not find expected key
```

### Seeded Defect

The SOPS configuration has the wrong age key reference, and a kustomize patch targets a renamed resource.

### Your Task

1. Identify the SOPS configuration issue
2. Fix the age key reference
3. Fix the kustomize patch target
4. Verify kustomize build succeeds

### Context Files

{{scenario_spec}}
