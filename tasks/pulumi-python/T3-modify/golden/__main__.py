"""GOLDEN: adds a target-tracking scaling policy to the existing ASG.

app_asg's own arguments are untouched from the seed -- no property that would
force replacement (name, launch_template, vpc_zone_identifiers) was edited --
only a new aws.autoscaling.Policy resource is added, referencing the existing
group by name.
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

app_scale_up_policy = aws.autoscaling.Policy(
    "app-scale-up",
    autoscaling_group_name=app_asg.name,
    policy_type="TargetTrackingScaling",
    target_tracking_configuration=aws.autoscaling.PolicyTargetTrackingConfigurationArgs(
        predefined_metric_specification=aws.autoscaling.PolicyTargetTrackingConfigurationPredefinedMetricSpecificationArgs(
            predefined_metric_type="ASGAverageCPUUtilization",
        ),
        target_value=60.0,
    ),
)

pulumi.export("asg_name", app_asg.name)
pulumi.export("scale_up_policy_arn", app_scale_up_policy.arn)
