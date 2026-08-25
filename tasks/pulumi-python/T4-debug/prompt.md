## Task: Fix stack failure: secret read as plain string, deletion protection disabled

**Stack:** Pulumi (Python)

Symptoms: the DB password is read as a plain config string instead of a secret, and the RDS instance has `deletion_protection=False` even though this is the prod database.

{{scenario_spec}}
