## Task: Fix preview crash: async misuse + wrong pulumi.output() wrapping

**Stack:** Pulumi (TypeScript)

Symptoms: tsc passes but preview crashes with async misuse and wrong `pulumi.output()` wrapping.

{{scenario_spec}}
