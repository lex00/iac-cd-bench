"""SEED REPO: existing Auto Scaling Group with no scaling policy.

The app tier runs behind a fixed-capacity ASG. Add a scaling policy without
triggering replacement of this existing group.
"""

import pulumi
import pulumi_aws as aws

config = pulumi.Config()
env = config.get("env", "dev")

app_asg = aws.autoscaling.Group(
    "app-asg",
    name=f"myapp-{env}-asg",
    min_size=2,
    max_size=6,
    desired_capacity=2,
    launch_template=aws.autoscaling.GroupLaunchTemplateArgs(
        id="lt-0123456789abcdef0",
        version="$Latest",
    ),
    vpc_zone_identifiers=["subnet-aaaa", "subnet-bbbb"],
    tags=[
        aws.autoscaling.GroupTagArgs(
            key="Environment",
            value=env,
            propagate_at_launch=True,
        ),
    ],
)

pulumi.export("asg_name", app_asg.name)
