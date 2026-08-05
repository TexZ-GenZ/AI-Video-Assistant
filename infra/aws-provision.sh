#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Provision ALL VideoSense AWS infrastructure:
#   EKS cluster (Fargate-only) + Fargate profiles
#   3 ECR repositories (ingestion / transcription / summarization)
#   S3 bucket, DynamoDB table, 3 SQS queues + DLQs
#   EFS filesystem + access points (whisper cache, chroma data) + mount targets
#   AWS Load Balancer Controller (raw manifests — no Helm)
#   EFS CSI driver (EKS managed add-on)
#   KEDA (raw manifests — no Helm) + IRSA for SQS/CloudWatch scaling
#
# Prerequisites: aws CLI configured, eksctl installed, kubectl installed.
# Usage:         ./infra/aws-provision.sh [cluster-name]   (default: videosense)
#
# Idempotent: safe to re-run; existing resources are skipped.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

CLUSTER="${1:-videosense}"
REGION="${AWS_REGION:-ap-south-1}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_ENV="$SCRIPT_DIR/.videosense.env"

echo "==> Provisioning VideoSense (cluster=$CLUSTER, region=$REGION, account=$ACCOUNT)"
echo "    This takes ~15-20 min the first time (EKS cluster creation)."

# ── 1. EKS cluster + Fargate profiles ──────────────────────────────────────
if eksctl get cluster --name "$CLUSTER" --region "$REGION" >/dev/null 2>&1; then
  echo "==> EKS cluster '$CLUSTER' already exists"
else
  echo "==> Creating EKS cluster '$CLUSTER' (Fargate-only) ..."
  eksctl create cluster \
    --name "$CLUSTER" \
    --region "$REGION" \
    --fargate \
    --with-oidc
fi

# Fargate profiles: one per namespace that hosts pods. The default profile
# (namespace: default) is created by --fargate above.
for ns in kube-system keda cert-manager; do
  if ! eksctl get fargateprofile --cluster "$CLUSTER" --region "$REGION" --name "$ns" >/dev/null 2>&1; then
    echo "==> Adding Fargate profile for namespace '$ns' ..."
    eksctl create fargateprofile --cluster "$CLUSTER" --region "$REGION" --name "$ns" --namespace "$ns"
  fi
done

# ── 2. ECR repositories ────────────────────────────────────────────────────
for repo in ingestion transcription summarization; do
  if aws ecr describe-repositories --repository-names "videosense/$repo" --region "$REGION" >/dev/null 2>&1; then
    echo "==> ECR repo videosense/$repo exists"
  else
    echo "==> Creating ECR repo videosense/$repo ..."
    aws ecr create-repository --repository-name "videosense/$repo" --region "$REGION" >/dev/null
  fi
done

# ── 3. S3 bucket ───────────────────────────────────────────────────────────
BUCKET="videosense-$ACCOUNT"
if aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
  echo "==> S3 bucket $BUCKET exists"
else
  echo "==> Creating S3 bucket $BUCKET ..."
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration "LocationConstraint=$REGION"
  fi
fi

# ── 4. DynamoDB table ──────────────────────────────────────────────────────
TABLE="videosense-jobs"
if aws dynamodb describe-table --table-name "$TABLE" --region "$REGION" >/dev/null 2>&1; then
  echo "==> DynamoDB table $TABLE exists"
else
  echo "==> Creating DynamoDB table $TABLE ..."
  aws dynamodb create-table \
    --table-name "$TABLE" \
    --key-schema "AttributeName=job_id,KeyType=HASH" \
    --attribute-definitions "AttributeName=job_id,AttributeType=S" \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" >/dev/null
  aws dynamodb wait table-exists --table-name "$TABLE" --region "$REGION"
fi

# ── 5. SQS queues + DLQs ───────────────────────────────────────────────────
for q in jobs transcribe summarize; do
  QNAME="videosense-$q"
  DLQNAME="videosense-$q-dlq"

  if aws sqs get-queue-url --queue-name "$QNAME" --region "$REGION" >/dev/null 2>&1; then
    echo "==> SQS queue $QNAME exists"
    continue
  fi

  echo "==> Creating SQS queue $QNAME + DLQ ..."
  aws sqs create-queue --queue-name "$DLQNAME" --region "$REGION" >/dev/null
  DLQ_URL="$(aws sqs get-queue-url --queue-name "$DLQNAME" --region "$REGION" --query QueueUrl --output text)"
  DLQ_ARN="$(aws sqs get-queue-attributes --queue-url "$DLQ_URL" --region "$REGION" \
    --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)"

  # RedrivePolicy is passed inline (no temp file): a git-bash/WSL /tmp path is
  # unreadable by the Windows aws.exe when passed as file://...
  REDRIVE="$(printf '{\\"deadLetterTargetArn\\":\\"%s\\",\\"maxReceiveCount\\":3}' "$DLQ_ARN")"
  aws sqs create-queue --queue-name "$QNAME" --region "$REGION" \
    --attributes "{\"RedrivePolicy\":\"$REDRIVE\"}" >/dev/null
done

# ── 6. AWS Load Balancer Controller ────────────────────────────────────────
POLICY_NAME="AWSLoadBalancerControllerIAMPolicy-videosense"
POLICY_ARN="arn:aws:iam::$ACCOUNT:policy/$POLICY_NAME"
if aws iam get-policy --policy-arn "$POLICY_ARN" >/dev/null 2>&1; then
  echo "==> IAM policy $POLICY_NAME exists"
else
  echo "==> Creating IAM policy $POLICY_NAME ..."
  # git-bash/WSL paths are unreadable by the Windows aws.exe — convert to
  # a Windows path when cygpath is available (plain paths elsewhere).
  if command -v cygpath >/dev/null 2>&1; then
    POLICY_FILE="file://$(cygpath -m "$SCRIPT_DIR/alb-iam-policy.json")"
  else
    POLICY_FILE="file://$SCRIPT_DIR/alb-iam-policy.json"
  fi
  aws iam create-policy --policy-name "$POLICY_NAME" \
    --policy-document "$POLICY_FILE" \
    --description "AWS Load Balancer Controller for VideoSense" >/dev/null
fi

if eksctl get iamserviceaccount --cluster "$CLUSTER" --region "$REGION" \
    --name aws-load-balancer-controller --namespace kube-system 2>/dev/null | grep -q aws-load-balancer-controller; then
  echo "==> IRSA aws-load-balancer-controller exists"
else
  echo "==> Creating IRSA aws-load-balancer-controller ..."
  eksctl create iamserviceaccount \
    --cluster "$CLUSTER" --region "$REGION" \
    --name aws-load-balancer-controller --namespace kube-system \
    --attach-policy-arn "$POLICY_ARN" --approve
fi

echo "==> Installing AWS Load Balancer Controller (v2.11.0) ..."
# The full manifest includes the CRDs (no separate crds asset in this release).
# cert-manager MUST be installed first — the webhook's Certificate/Issuer
# resources need its CRDs.
if ! kubectl get deployment cert-manager -n cert-manager >/dev/null 2>&1; then
  echo "==> Installing cert-manager (v1.16.3) ..."
  kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.16.3/cert-manager.yaml
fi
# --vpc-id is REQUIRED on Fargate: there is no EC2 instance metadata, so the
# controller's VPC discovery fails without it.
ALB_VPC_ID="$(aws eks describe-cluster --name "$CLUSTER" --region "$REGION" \
  --query 'cluster.resourcesVpcConfig.vpcId' --output text)"
curl -fsSL https://github.com/kubernetes-sigs/aws-load-balancer-controller/releases/download/v2.11.0/v2_11_0_full.yaml \
  | sed -e "s/your-cluster-name/$CLUSTER/g" \
        -e "s|--cluster-name=$CLUSTER|--cluster-name=$CLUSTER\\n            - --vpc-id=$ALB_VPC_ID|" \
  | kubectl apply -f -

# ── 7. EFS (whisper cache + chroma data) ───────────────────────────────────
VPC_ID="$(aws eks describe-cluster --name "$CLUSTER" --region "$REGION" \
  --query 'cluster.resourcesVpcConfig.vpcId' --output text)"
CLUSTER_SG="$(aws eks describe-cluster --name "$CLUSTER" --region "$REGION" \
  --query 'cluster.resourcesVpcConfig.clusterSecurityGroupId' --output text)"

FS_ID="$(aws efs describe-file-systems --region "$REGION" \
  --query "FileSystems[?Name=='videosense-efs'].FileSystemId" --output text)"
if [ -z "$FS_ID" ]; then
  echo "==> Creating EFS filesystem ..."
  FS_ID="$(aws efs create-file-system --region "$REGION" \
    --creation-token "videosense-efs" \
    --performance-mode generalPurpose --throughput-mode bursting \
    --tags "Key=Name,Value=videosense-efs" \
    --query FileSystemId --output text)"
  for _ in $(seq 1 60); do
    STATE="$(aws efs describe-file-systems --file-system-id "$FS_ID" --region "$REGION" \
      --query 'FileSystems[0].LifeCycleState' --output text)"
    [ "$STATE" = "available" ] && break
    sleep 5
  done
else
  echo "==> EFS filesystem $FS_ID exists"
fi

# Mount targets in the private subnets (where Fargate pods run).
# eksctl 0.229+ tags subnets with eksctl.cluster.k8s.io/v1alpha1/cluster-name
# (the older kubernetes.io/cluster/<name> tag is no longer set).
SUBNETS="$(aws ec2 describe-subnets --region "$REGION" \
  --filters "Name=tag:eksctl.cluster.k8s.io/v1alpha1/cluster-name,Values=$CLUSTER" \
            "Name=tag:kubernetes.io/role/internal-elb,Values=1" \
  --query 'Subnets[].SubnetId' --output text)"
if [ -z "$SUBNETS" ]; then
  echo "!! No private subnets found for cluster $CLUSTER — mount targets skipped"
else
  for SUBNET in $SUBNETS; do
    if aws efs describe-mount-targets --file-system-id "$FS_ID" --region "$REGION" \
        --query "MountTargets[?SubnetId=='$SUBNET'].MountTargetId" --output text | grep -q .; then
      continue
    fi
    echo "==> Adding EFS mount target in $SUBNET ..."
    SG_ID="$(aws ec2 describe-security-groups --region "$REGION" \
      --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=videosense-efs-sg" \
      --query 'SecurityGroups[0].GroupId' --output text)"
    if [ "$SG_ID" = "None" ] || [ -z "$SG_ID" ]; then
      SG_ID="$(aws ec2 create-security-group --region "$REGION" \
        --group-name videosense-efs-sg --description "NFS access for VideoSense EFS" \
        --vpc-id "$VPC_ID" --query GroupId --output text)"
      aws ec2 authorize-security-group-ingress --region "$REGION" \
        --group-id "$SG_ID" --protocol tcp --port 2049 --source-group "$CLUSTER_SG"
    fi
    aws efs create-mount-target --region "$REGION" \
      --file-system-id "$FS_ID" --subnet-id "$SUBNET" --security-groups "$SG_ID" >/dev/null
  done
fi

# Access points: whisper model cache + chroma data (containers run as root → uid 0)
AP_MODELS="$(aws efs describe-access-points --region "$REGION" \
  --query "AccessPoints[?Name=='videosense-whisper-cache'].AccessPointId" --output text)"
if [ -z "$AP_MODELS" ]; then
  echo "==> Creating EFS access point (whisper cache) ..."
  # MSYS_NO_PATHCONV: git-bash would rewrite /models into a Windows path
  AP_MODELS="$(MSYS_NO_PATHCONV=1 aws efs create-access-point --region "$REGION" \
    --file-system-id "$FS_ID" --client-token "videosense-models-$(date +%s)" \
    --tags "Key=Name,Value=videosense-whisper-cache" \
    --posix-user "Uid=0,Gid=0" \
    --root-directory 'Path=/models,CreationInfo={OwnerUid=0,OwnerGid=0,Permissions=0755}' \
    --query AccessPointId --output text)"
fi

AP_CHROMA="$(aws efs describe-access-points --region "$REGION" \
  --query "AccessPoints[?Name=='videosense-chroma'].AccessPointId" --output text)"
if [ -z "$AP_CHROMA" ]; then
  echo "==> Creating EFS access point (chroma data) ..."
  AP_CHROMA="$(MSYS_NO_PATHCONV=1 aws efs create-access-point --region "$REGION" \
    --file-system-id "$FS_ID" --client-token "videosense-chroma-$(date +%s)" \
    --tags "Key=Name,Value=videosense-chroma" \
    --posix-user "Uid=0,Gid=0" \
    --root-directory 'Path=/chroma,CreationInfo={OwnerUid=0,OwnerGid=0,Permissions=0755}' \
    --query AccessPointId --output text)"
fi

# ── 8. EFS CSI driver (EKS managed add-on) ─────────────────────────────────
if eksctl get iamserviceaccount --cluster "$CLUSTER" --region "$REGION" \
    --name efs-csi-controller-sa --namespace kube-system 2>/dev/null | grep -q efs-csi-controller-sa; then
  echo "==> IRSA efs-csi-controller-sa exists"
else
  echo "==> Creating IRSA efs-csi-controller-sa ..."
  eksctl create iamserviceaccount \
    --cluster "$CLUSTER" --region "$REGION" \
    --name efs-csi-controller-sa --namespace kube-system \
    --attach-policy-arn "arn:aws:iam::aws:policy/AmazonEFSCSIDriverPolicy" --approve
fi
EFS_ROLE_ARN="$(aws iam list-roles --region "$REGION" \
  --query "Roles[?starts_with(RoleName, 'eksctl-$CLUSTER-addon-iamserviceaccount-kube-system-efs-csi-controller-sa')].Arn" \
  --output text | tr '\t' '\n' | head -1)"
if aws eks describe-addon --cluster-name "$CLUSTER" --addon-name aws-efs-csi-driver --region "$REGION" >/dev/null 2>&1; then
  echo "==> EKS add-on aws-efs-csi-driver exists"
else
  echo "==> Installing EKS add-on aws-efs-csi-driver ..."
  eksctl create addon --name aws-efs-csi-driver --cluster "$CLUSTER" --region "$REGION" \
    --service-account-role-arn "$EFS_ROLE_ARN" --force
fi

# ── 9. KEDA (SQS autoscaling) ──────────────────────────────────────────────
echo "==> Installing KEDA (core, v2.16.1) ..."
# Server-side apply: client-side apply stores the whole object in an
# annotation, and KEDA's scaledjobs CRD exceeds the 256 KiB annotation limit.
kubectl apply --server-side \
  -f https://github.com/kedacore/keda/releases/download/v2.16.1/keda-2.16.1-core.yaml

if eksctl get iamserviceaccount --cluster "$CLUSTER" --region "$REGION" \
    --name keda-operator --namespace keda 2>/dev/null | grep -q keda-operator; then
  echo "==> IRSA keda-operator exists"
else
  echo "==> Creating IRSA keda-operator (SQS + CloudWatch read) ..."
  eksctl create iamserviceaccount \
    --cluster "$CLUSTER" --region "$REGION" \
    --name keda-operator --namespace keda \
    --attach-policy-arn "arn:aws:iam::aws:policy/AmazonSQSReadOnlyAccess" \
    --attach-policy-arn "arn:aws:iam::aws:policy/CloudWatchReadOnlyAccess" \
    --approve --override-existing-serviceaccounts
fi

# ── Outputs ────────────────────────────────────────────────────────────────
cat >"$OUT_ENV" <<EOF
# VideoSense infrastructure outputs (generated by aws-provision.sh — do not commit)
export CLUSTER="$CLUSTER"
export REGION="$REGION"
export ACCOUNT="$ACCOUNT"
export JOBS_BUCKET="$BUCKET"
export JOBS_TABLE="$TABLE"
export JOBS_QUEUE="videosense-jobs"
export TRANSCRIBE_QUEUE="videosense-transcribe"
export SUMMARIZE_QUEUE="videosense-summarize"
export EFS_FS_ID="$FS_ID"
export EFS_AP_MODELS="$AP_MODELS"
export EFS_AP_CHROMA="$AP_CHROMA"
EOF

echo
echo "=============================================================="
echo " VideoSense infrastructure ready!"
echo "=============================================================="
echo " Cluster:       $CLUSTER ($REGION)"
echo " Bucket:        $BUCKET"
echo " Table:         $TABLE"
echo " Queues:        videosense-{jobs,transcribe,summarize} + -dlq"
echo " ECR repos:     videosense/{ingestion,transcription,summarization}"
echo " EFS:           $FS_ID (whisper cache AP: $AP_MODELS, chroma AP: $AP_CHROMA)"
echo
echo " Outputs saved to $OUT_ENV"
echo " Next: kubectl apply -f k8s/   (application manifests — step 11)"
echo "=============================================================="
