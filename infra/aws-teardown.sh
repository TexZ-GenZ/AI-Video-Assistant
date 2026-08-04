#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Tear down EVERYTHING created by aws-provision.sh — back to ~$0/mo.
#
# Order matters:
#   1. delete app resources (ingress first → ALB goes away)
#   2. eksctl delete cluster (removes EKS, Fargate profiles, IRSA roles,
#      OIDC provider, NAT gateway, VPC, subnets — everything CloudFormation-made)
#   3. delete standalone AWS resources (EFS, S3, DynamoDB, SQS, ECR, IAM policy)
#
# Usage: ./infra/aws-teardown.sh [cluster-name]   (default: videosense)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

CLUSTER="${1:-videosense}"
REGION="${AWS_REGION:-ap-south-1}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$SCRIPT_DIR/.videosense.env" ]; then
  source "$SCRIPT_DIR/.videosense.env"
fi
BUCKET="${JOBS_BUCKET:-videosense-$ACCOUNT}"

echo "==> Tearing down VideoSense (cluster=$CLUSTER, region=$REGION)"
read -r -p "Type the cluster name to confirm: " CONFIRM
[ "$CONFIRM" = "$CLUSTER" ] || { echo "Aborted."; exit 1; }

# ── 1. App resources (only if kubectl can reach the cluster) ───────────────
if kubectl get clusterrolebindings >/dev/null 2>&1; then
  echo "==> Deleting app resources ..."
  kubectl delete ingress videosense-ingress -n default --ignore-not-found
  kubectl delete deployment --all -n default --ignore-not-found
  kubectl delete pvc --all -n default --ignore-not-found
  kubectl delete secret ecr-cred videosense-secrets -n default --ignore-not-found
fi

# ── 2. EKS cluster (deletes Fargate profiles, IRSA roles, OIDC, VPC, NAT) ──
if eksctl get cluster --name "$CLUSTER" --region "$REGION" >/dev/null 2>&1; then
  echo "==> Deleting EKS cluster '$CLUSTER' (this takes ~15 min) ..."
  eksctl delete cluster --name "$CLUSTER" --region "$REGION"
else
  echo "==> No EKS cluster '$CLUSTER'"
fi

# ── 3. Standalone AWS resources ────────────────────────────────────────────
# EFS: mount targets first, then access points, then the filesystem
FS_ID="$(aws efs describe-file-systems --region "$REGION" \
  --query "FileSystems[?Name=='videosense-efs'].FileSystemId" --output text)"
if [ -n "$FS_ID" ]; then
  echo "==> Deleting EFS $FS_ID ..."
  for MT in $(aws efs describe-mount-targets --file-system-id "$FS_ID" --region "$REGION" \
    --query 'MountTargets[].MountTargetId' --output text); do
    aws efs delete-mount-target --mount-target-id "$MT" --region "$REGION"
  done
  # mount-target deletion is async — wait before removing the filesystem
  for _ in $(seq 1 30); do
    LEFT="$(aws efs describe-mount-targets --file-system-id "$FS_ID" --region "$REGION" \
      --query 'length(MountTargets)' --output text)"
    [ "$LEFT" = "0" ] && break
    sleep 5
  done
  for AP in $(aws efs describe-access-points --region "$REGION" \
    --query "AccessPoints[?FileSystemId=='$FS_ID'].AccessPointId" --output text); do
    aws efs delete-access-point --access-point-id "$AP" --region "$REGION"
  done
  aws efs delete-file-system --file-system-id "$FS_ID" --region "$REGION"
  SG_ID="$(aws ec2 describe-security-groups --region "$REGION" \
    --filters "Name=group-name,Values=videosense-efs-sg" \
    --query 'SecurityGroups[0].GroupId' --output text)"
  if [ "$SG_ID" != "None" ] && [ -n "$SG_ID" ]; then
    aws ec2 delete-security-group --group-id "$SG_ID" --region "$REGION" || true
  fi
fi

# S3
if aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
  echo "==> Emptying + deleting S3 bucket $BUCKET ..."
  aws s3 rm "s3://$BUCKET" --recursive --region "$REGION"
  aws s3api delete-bucket --bucket "$BUCKET" --region "$REGION"
fi

# DynamoDB
if aws dynamodb describe-table --table-name videosense-jobs --region "$REGION" >/dev/null 2>&1; then
  echo "==> Deleting DynamoDB table videosense-jobs ..."
  aws dynamodb delete-table --table-name videosense-jobs --region "$REGION" >/dev/null
fi

# SQS (queues + DLQs)
for q in jobs transcribe summarize; do
  for name in "videosense-$q" "videosense-$q-dlq"; do
    if URL="$(aws sqs get-queue-url --queue-name "$name" --region "$REGION" --query QueueUrl --output text 2>/dev/null)"; then
      echo "==> Deleting SQS queue $name ..."
      aws sqs delete-queue --queue-url "$URL" --region "$REGION"
    fi
  done
done

# ECR
for repo in ingestion transcription summarization; do
  if aws ecr describe-repositories --repository-names "videosense/$repo" --region "$REGION" >/dev/null 2>&1; then
    echo "==> Deleting ECR repo videosense/$repo ..."
    aws ecr delete-repository --repository-name "videosense/$repo" --region "$REGION" --force >/dev/null
  fi
done

# IAM policy
POLICY_ARN="arn:aws:iam::$ACCOUNT:policy/AWSLoadBalancerControllerIAMPolicy-videosense"
if aws iam get-policy --policy-arn "$POLICY_ARN" >/dev/null 2>&1; then
  echo "==> Deleting IAM policy ..."
  aws iam delete-policy --policy-arn "$POLICY_ARN"
fi

echo
echo "=============================================================="
echo " Teardown complete. Remaining monthly cost: ~$2-5 (nothing)."
echo " Recreate anytime: ./infra/aws-provision.sh && ./k8s/apply.sh"
echo "=============================================================="
