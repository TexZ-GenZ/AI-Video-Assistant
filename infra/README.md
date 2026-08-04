# VideoSense AWS Infrastructure (eksctl + AWS CLI)

Everything the deployed system needs, provisioned with **eksctl + AWS CLI** —
no Terraform, no Helm. The application itself (Deployments, Ingress, HPA,
KEDA ScaledObjects) lives in [`../k8s/`](../k8s/) as plain manifests.

## What gets created

| Resource | Name | Purpose |
| --- | --- | --- |
| EKS cluster | `videosense` | Fargate-only, 2 AZs, OIDC enabled |
| Fargate profiles | `default`, `kube-system`, `keda` | one per namespace hosting pods |
| ECR repos ×3 | `videosense/{ingestion,transcription,summarization}` | container images |
| S3 bucket | `videosense-<account-id>` | uploads, chunks, transcripts |
| DynamoDB table | `videosense-jobs` | job workflow state (PAY_PER_REQUEST) |
| SQS queues ×3 + DLQs | `videosense-{jobs,transcribe,summarize}` + `-dlq` | async pipeline, redrive after 3 failures |
| EFS filesystem | `videosense-efs` | shared storage (bursting throughput) |
| EFS access points ×2 | whisper cache (`/models`), chroma (`/chroma`) | per-PVC roots for the CSI driver |
| IAM policy | `AWSLoadBalancerControllerIAMPolicy-videosense` | official ALB controller policy |
| IRSA roles ×3 | ALB controller, EFS CSI, KEDA operator | least-privilege pod identities |
| EKS add-on | `aws-efs-csi-driver` | EFS volumes on Fargate |
| ALB controller | v2.11.0 (raw manifests) | Kubernetes Ingress → AWS ALB |
| KEDA | v2.16.1 core (raw manifests) | SQS-depth autoscaling |

## Prerequisites

```bash
aws configure                          # credentials with admin-ish access
aws sts get-caller-identity            # verify
winget install Amazon.EKSctl           # or: choco install eksctl
kubectl version --client
```

## Run

```bash
./infra/aws-provision.sh [cluster-name]   # default cluster name: videosense
```

- **First run: ~15–20 min** (EKS cluster creation is the slow part).
- **Idempotent**: re-running skips everything that already exists.
- Writes machine-specific values to `infra/.videosense.env` (gitignored) —
  the `k8s/` manifests read those values (or you set them by hand).

## Verify

```bash
eksctl get cluster --name videosense
kubectl get pods -A        # kube-system: alb controller + efs csi; keda: operator
aws sqs list-queues
aws efs describe-file-systems
```

## Teardown

See [`../k8s/README.md`](../k8s/README.md) — an `aws-teardown.sh` script ships
with the deploy docs (or `eksctl delete cluster --name videosense` for the
cluster, plus deleting the remaining AWS resources by hand).

## Cost notes (rough, us-east-1, ~24/7)

| Resource | ~$/mo |
| --- | --- |
| EKS control plane | 73 (flat, unavoidable) |
| Fargate pods (3–5 × 0.5 vCPU/1 GB) | 30–50 |
| ALB + EFS + S3 + DDB + SQS + ECR | 15–25 |
| **Total** | **~120–150/mo running 24/7** |

KEDA can scale workers to zero replicas between jobs (minReplicas 0), and
stopping the stack (`kubectl scale` deployments to 0) drops the Fargate cost
to just the control plane + storage.
