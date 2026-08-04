# VideoSense Kubernetes manifests

Plain YAML — no Helm, no Terraform. Placeholders (`YOUR_*`) are substituted
by [`apply.sh`](apply.sh) from the values in `../infra/.videosense.env`
(produced by [`../infra/aws-provision.sh`](../infra/aws-provision.sh)).

## Deploy

```bash
./k8s/apply.sh
```

What it does:

1. Refreshes the ECR pull secret (`ecr-cred`) — ECR tokens expire after
   **12 hours**; re-run `apply.sh` (or just the first section) to refresh.
2. Creates the `videosense-secrets` secret from `../.env` (keys are never
   committed — see `secrets.yaml.example` for the shape).
3. Substitutes placeholders and applies everything:
   `configmap → storage → chroma → services → ingress → autoscaling`.
4. Waits for the ALB and prints its URL.

## What's in here

| File | Contents |
| --- | --- |
| `configmap.yaml` | shared env: table/bucket/queues/CORS/whisper/chroma |
| `storage.yaml` | EFS StorageClasses (whisper cache + chroma) + PVCs |
| `chroma.yaml` | ChromaDB server deployment + service (single replica) |
| `ingestion.yaml` | ingestion API deployment + service + worker deployment |
| `transcription.yaml` | transcription worker (EFS-mounted model cache) |
| `summarization.yaml` | summarization API + service + worker |
| `ingress.yaml` | ALB, internet-facing, `target-type: ip` (Fargate), path routing |
| `autoscaling.yaml` | CPU HPA for APIs + KEDA ScaledObjects on SQS depth |
| `secrets.yaml.example` | secret shape (real values come from `../.env`) |

## Verify

```bash
kubectl get pods -A                    # all Running
kubectl get ingress                    # ALB DNS once provisioned
kubectl get scaledobject -A            # KEDA objects active
kubectl get hpa -A
kubectl logs -l app=ingestion-worker   # worker logs
```

## Autoscaling semantics

- **ingestion-worker**: 0 → 4 replicas, scales when `videosense-jobs` has ≥5 messages
- **transcription-worker**: 0 → 4 replicas, `videosense-transcribe` ≥5 messages
- **summarization-worker**: 1 → 4 replicas (never zero — chat depends on it)
- **APIs**: CPU HPA 1 → 4 at 70% utilization

All scaling reads use the `keda-operator` IRSA role (SQS + CloudWatch read-only).

## Teardown

```bash
kubectl delete -f k8s/           # or: kubectl delete all -n default --all
eksctl delete cluster --name videosense
# then delete remaining AWS resources by hand (S3, DDB, SQS, ECR, EFS, policy)
```
