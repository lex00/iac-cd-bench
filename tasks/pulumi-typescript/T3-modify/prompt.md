## Task: Migrate flat program to ComponentResource without replacement

**Stack:** Pulumi (TypeScript)

### Current State

`index.ts` declares two resources at the top level, with no `ComponentResource`
wrapper: `app-bucket` (`aws.s3.Bucket`, versioned, tagged `Environment: env`)
and `app-db` (`aws.rds.Instance`, `db.t3.medium`, Postgres 16.1, 20GB, password
from `config.requireSecret("dbPassword")`).

### Your Task

Migrate `app-bucket` and `app-db` into a `pulumi.ComponentResource` subclass
without triggering replacement of either resource -- keep their existing
logical names and resource arguments unchanged, parent them to the new
component, and use `aliases` so Pulumi recognizes them as the same resources
under their new parent rather than recreating them.

{{scenario_spec}}
