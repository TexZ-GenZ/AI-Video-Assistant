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

## Cost notes (rough, ap-south-1, idle — no jobs running)

| Resource | ~$/mo |
| --- | --- |
| EKS control plane | 73 (flat, unavoidable) |
| NAT gateway (private-subnet egress) | 32 |
| Fargate idle pods: 2 APIs + summarization worker + chroma + KEDA (2) + ALB controller (2) + EFS CSI | ~100 (Fargate bills a **minimum 0.25 vCPU / 0.5 GB per pod**, so even tiny pods cost ~$9/mo each) |
| ALB (hourly + minimal LCUs) | ~18 |
| EFS + S3 + DDB + SQS + ECR (idle) | ~2 |
| **Total idle 24/7** | **~$210–225/mo** |

Per processed video (30 min): ~$0.05–0.15 (transient Fargate pod + Mistral).

### Cutting the idle cost

| Mode | ~$/mo | What you do |
| --- | --- | --- |
| Alive 24/7 | ~215 | as deployed |
| Scaled to zero | ~115 | `kubectl scale deployment --all -n default --replicas=0` + delete the ingress (ALB gone); cold start ~2–5 min |
| Destroyed | ~2–5 | `./infra/aws-teardown.sh`, recreate with `aws-provision.sh` (~15–20 min) |

KEDA already scales both workers to zero between jobs (minReplicas 0).
