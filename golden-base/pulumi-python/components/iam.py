"""IAM component with user and role for service-account access."""

from __future__ import annotations

from typing import Any

import pulumi
from pulumi import ComponentResource, Output, ResourceOptions
from pulumi.aws.iam import (
    AccessKey,
    Policy,
    Role,
    RolePolicyAttachment,
    User,
)


class IAMServiceAccount(ComponentResource):
    """Creates an IAM user and/or role for service-account access.

    Args:
        name: Logical resource name.
        create_user: True to create a programmatic access user (dev).
        create_role: True to create a role with OIDC trust (prod).
        least_privilege_policy: Policy ARN for pre-existing managed policy (prod).
        allowed_arns: List of ARNs the role can access (prod).
        oidc_provider_arn: OIDC provider ARN for trust policy (prod).
        tags: Resource tags.
        opts: Pulumi resource options.
    """

    def __init__(
        self,
        name: str,
        *,
        create_user: bool = True,
        create_role: bool = False,
        least_privilege_policy: str | None = None,
        allowed_arns: list[str] | None = None,
        oidc_provider_arn: str | None = None,
        tags: dict[str, str] | None = None,
        opts: ResourceOptions | None = None,
    ) -> None:
        super().__init__("iac-cd-bench:components:IAMServiceAccount", name, None, opts)

        tag_map = tags or {}

        self._user: User | None = None
        self._user_access_key: AccessKey | None = None
        self._role: Role | None = None
        self._role_arn: Output[str] | None = None
        self._user_access_key_id: Output[str] | None = None
        self._user_secret: Output[str] | None = None

        if create_user:
            self._create_user(name, tag_map)

        if create_role:
            self._create_role(
                name,
                least_privilege_policy,
                allowed_arns,
                oidc_provider_arn,
                tag_map,
            )

        user_name: str | None = None
        if self._user is not None:
            user_name = self._user.name

        role_name: str | None = None
        if self._role is not None:
            role_name = self._role.name

        self.register_outputs(
            {
                "user_name": user_name,
                "role_name": role_name,
            }
        )

    def _create_user(self, name: str, tags: dict[str, str]) -> None:
        """Create an IAM user with programmatic access for dev."""
        assert self._user is None

        self._user = User(
            f"{name}-user",
            name=f"{name}-app-user",
            tags=tags,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self._user_access_key = AccessKey(
            f"{name}-access-key",
            user=self._user.name,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self._user_access_key_id = self._user_access_key.id
        self._user_secret = self._user_access_key.secret

    def _create_role(
        self,
        name: str,
        least_privilege_policy: str | None,
        allowed_arns: list[str] | None,
        oidc_provider_arn: str | None,
        tags: dict[str, str],
    ) -> None:
        """Create an IAM role with least-privilege policy and OIDC trust (prod)."""
        import json

        assert self._role is None

        # OIDC trust policy for EKS ServiceAccount
        if oidc_provider_arn:
            trust_document: dict[str, Any] = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Federated": oidc_provider_arn},
                        "Action": "sts:AssumeRoleWithWebIdentity",
                        "Condition": {
                            "StringEquals": {
                                f"{oidc_provider_arn}:aud": "sts.amazonaws.com",
                            }
                        },
                    }
                ],
            }
        else:
            trust_document = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": "*"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }

        self._role = Role(
            f"{name}-role",
            name=f"{name}-app-role",
            assume_role_policy=json.dumps(trust_document),
            tags=tags,
            opts=pulumi.ResourceOptions(parent=self),
        )

        if least_privilege_policy:
            # Attach pre-existing managed policy
            RolePolicyAttachment(
                f"{name}-role-policy",
                role=self._role.name,
                policy_arn=least_privilege_policy,
                opts=pulumi.ResourceOptions(parent=self),
            )
        elif allowed_arns:
            # Inline least-privilege policy scoped to specific resources
            inline_policy: dict[str, Any] = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
                        "Resource": allowed_arns,
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["rds-db:Connect"],
                        "Resource": allowed_arns,
                    },
                ],
            }
            policy = Policy(
                f"{name}-inline-policy",
                name=f"{name}-least-privilege",
                policy=json.dumps(inline_policy),
                opts=pulumi.ResourceOptions(parent=self),
            )
            RolePolicyAttachment(
                f"{name}-role-inline-attach",
                role=self._role.name,
                policy_arn=policy.arn,
                opts=pulumi.ResourceOptions(parent=self),
            )

        self._role_arn = self._role.arn

    @property
    def role_arn(self) -> Output[str] | None:
        return self._role_arn

    @property
    def user_access_key_id(self) -> Output[str] | None:
        return self._user_access_key_id

    @property
    def user_secret(self) -> Output[str] | None:
        return self._user_secret

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_name": self._user.name if self._user else None,
            "role_arn": self._role_arn,
        }
