## Task: Fix Composition never Ready

**Stack:** Crossplane

Symptoms: Composition never reaches Ready state
- Defect: incorrect `fromFieldPath` in patch
- Defect: missing `ReadinessChecks` on RDS resource

{{scenario_spec}}
