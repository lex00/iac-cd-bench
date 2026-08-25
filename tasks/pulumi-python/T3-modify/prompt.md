## Task: Add auto-scaling policy without replacing existing resources

**Stack:** Pulumi (Python)

### Current State

`__main__.py` declares a fixed-capacity `aws.autoscaling.Group` named `app-asg`
(Pulumi resource name), physical name `myapp-{env}-asg`, with `min_size=2`,
`max_size=6`, `desired_capacity=2`. It has no scaling policy.

### Your Task

Add a target-tracking (or step) scaling policy for `app-asg` without triggering
replacement of the existing group -- do not change any of `app-asg`'s existing
arguments (name, launch template, VPC zone identifiers, tags). Only add a new
`aws.autoscaling.Policy` resource that references the existing group.

{{scenario_spec}}
