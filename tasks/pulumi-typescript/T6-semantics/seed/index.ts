import * as pulumi from "@pulumi/pulumi";
import * as aws from "@pulumi/aws";

const config = new pulumi.Config();
const env = config.require("env");
const logRetention = config.getNumber("logRetention") ?? 30;
const apiToken = config.requireSecret("apiToken");

export const artifacts = new aws.s3.Bucket("artifacts", {
    bucket: `knr-artifacts-${env}`,
    versioning: { enabled: true },
    tags: { Env: env },
}, { protect: true });

const cache = new aws.s3.Bucket("cache", {
    bucket: `knr-cache-${env}`,
    forceDestroy: true,
}, { deleteBeforeReplace: true, dependsOn: [artifacts] });

const role = new aws.iam.Role("appRole", {
    assumeRolePolicy: JSON.stringify({
        Version: "2012-10-17",
        Statement: [{
            Effect: "Allow",
            Principal: { Service: "ec2.amazonaws.com" },
            Action: "sts:AssumeRole",
        }],
    }),
});

// Policy depends on the bucket ARN (an Output<string>)
const policy = new aws.iam.RolePolicy("appPolicy", {
    role: role.id,
    policy: artifacts.arn.apply(arn => JSON.stringify({
        Version: "2012-10-17",
        Statement: [{
            Effect: "Allow",
            Action: ["s3:GetObject", "s3:PutObject"],
            Resource: `${arn}/*`,
        }],
    })),
});

const tokenParam = new aws.ssm.Parameter("apiToken", {
    type: "SecureString",
    value: apiToken,
});

// String concat on an Output<string> — classic footgun
const bucketMsg = "bucket is " + artifacts.bucket;

export const bucketName = artifacts.bucket;
export const tokenOut = apiToken;
export const message = bucketMsg;
