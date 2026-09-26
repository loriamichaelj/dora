#!/usr/bin/env bash
# Create the Terraform state bucket if it doesn't exist yet, and print its name.
# Runs in bootstrap.yml before `terraform init`: Terraform can't create the
# bucket its own state lives in. infra/bootstrap then imports the bucket and
# manages the rest of its configuration.
#
# Versioning and the public access block are set here too, so state is
# protected from its very first write. Safe to re-run.
set -euo pipefail

# Stdout is captured by the workflow and must contain only the bucket name.
# Send everything else (including AWS CLI output such as head-bucket's JSON)
# to stderr, where it still shows in the job log; fd 3 keeps the real stdout.
exec 3>&1 1>&2

# Both come from infra/project.env, loaded by the workflow.
REGION="${AWS_REGION:?AWS_REGION must be set}"
NAME_PREFIX="${NAME_PREFIX:?NAME_PREFIX must be set}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="${NAME_PREFIX}-tfstate-${ACCOUNT_ID}"

if aws s3api head-bucket --bucket "${BUCKET}" >/dev/null 2>&1; then
  echo "State bucket ${BUCKET} already exists."
else
  echo "Creating state bucket ${BUCKET} in ${REGION}."
  if [ "${REGION}" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" >/dev/null
  else
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" \
      --create-bucket-configuration "LocationConstraint=${REGION}" >/dev/null
  fi
  aws s3api wait bucket-exists --bucket "${BUCKET}"
fi

aws s3api put-public-access-block --bucket "${BUCKET}" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket "${BUCKET}" \
  --versioning-configuration Status=Enabled

echo "${BUCKET}" >&3
