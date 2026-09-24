# Kubernetes deployment

A local Minikube deployment of hf-model-finder, written as plain hand-written manifests (no Helm/Kustomize) so each Kubernetes primitive stays visible. This mirrors `docker-compose.yml`'s shape: two Deployments (app, dashboard) built from the same image, differing only in which Streamlit script they run, sharing one SQLite file for the monitoring data.

## What's deployed

| File | What it is |
|---|---|
| `00-namespace.yaml` | isolates everything under the `hf-model-finder` namespace |
| `01-configmap.yaml` | non-secret config (`DB_PATH`) |
| `02-secret.example.yaml.tpl` | reference only — shows the Secret's shape. **Not a `.yaml` on purpose**: `kubectl apply -f k8s/` reads every `.yaml` in the directory, so a real extension here would overwrite the live Secret with the placeholder |
| `03-pvc.yaml` | shared persistent storage for the SQLite monitoring DB |
| `04/05` | app Deployment + Service |
| `06/07` | dashboard Deployment + Service |
| `08-ingress.yaml` | optional host-based routing to both, via Minikube's ingress addon. **Not applied by `make k8s-apply`** — see `make k8s-ingress` and "Reaching it" below |

## The shared-SQLite decision

There's no separate "db" container — the monitoring database is a plain SQLite file that both the app and dashboard processes open directly (see `db.py`), at the `DB_PATH` set in `01-configmap.yaml`: `/app/state/monitoring.db`. Both Deployments mount the same `ReadWriteOnce` PVC at `/app/state`.

This only works because Minikube is single-node: an RWO PersistentVolume can be mounted by multiple Pods as long as they're scheduled on the same node, which is guaranteed here. **It does not generalize to a multi-node cluster** — there, this would either force both Deployments onto one node or require RWX storage (NFS/EFS), and SQLite over a network filesystem is a known corruption risk. The real fix at that scale is a proper DB server (e.g. a Postgres StatefulSet) instead of a shared file — see stretch goals below.

## Secrets

`OPENAI_API_KEY` and `APP_PASSWORD` are never written to a committed YAML file. `make k8s-secret` creates the Secret imperatively straight from the existing `.env`:

```
kubectl create secret generic hf-model-finder-secrets \
  --from-env-file=.env --namespace=hf-model-finder \
  --dry-run=client -o yaml | kubectl apply -f -
```

`02-secret.example.yaml.tpl` is committed with placeholder values purely so the Secret's shape is visible in the repo.

Two things worth knowing about this flow:

- **The Secret mirrors `.env` exactly.** Whatever is in that file lands in the cluster, so `.env` should hold only this app's credentials — today that is `OPENAI_API_KEY`. Piping `--dry-run` into `apply` (rather than plain `create`) makes the target re-runnable and prunes keys you later remove.
- **`APP_PASSWORD` is optional and currently unset.** `auth.py` no-ops without it, which is fine on a local single-user cluster. Set it in `.env` before exposing this deployment on anything public — otherwise the app is open to anyone who can reach it, and every query bills `OPENAI_API_KEY`.

## Running it

```bash
brew install minikube               # one-time
minikube start --driver=docker --cpus=4 --memory=6g

make k8s-build                      # docker build + minikube image load
make k8s-apply                      # namespace, secret, configmap, pvc, deployments, services, ingress
```

Check status any time with `make k8s-status`. Tear everything down with `make k8s-delete`.

`k8s-apply` ends with an explicit `kubectl rollout restart`. This is not cosmetic: the image tag is pinned at `:latest` and side-loaded with `minikube image load`, so after a rebuild the Deployment spec is byte-identical and `kubectl apply` alone would leave the old Pods running — a rebuild that silently doesn't deploy.

## Reaching it

**Primary (recommended):**

```bash
make k8s-open-app          # minikube service hf-model-finder-app -n hf-model-finder
make k8s-open-dashboard    # minikube service hf-model-finder-dashboard -n hf-model-finder
```

Each opens a local URL to that Service (`minikube service` proxies a `ClusterIP` Service through the Docker driver — no sudo, no `/etc/hosts` edit). Keep the terminal running while you use it; `Ctrl-C` to stop.

**Optional: via Ingress**, if you want to exercise host-based routing (`08-ingress.yaml`) the way a real cluster would expose multiple apps behind one entrypoint:

```bash
make k8s-ingress            # applies 08-ingress.yaml (k8s-apply deliberately does not)
minikube addons enable ingress
sudo minikube tunnel        # separate terminal, keep running — needs sudo to bind :80/:443
make k8s-url                # prints the /etc/hosts line to add
# add the printed line to /etc/hosts, then:
open http://hf-model-finder.local
open http://dashboard.hf-model-finder.local
```

This path exists to demonstrate Ingress as a primitive; it's not required to use the app locally, which is why it's neither the default flow above nor part of `make k8s-apply`. ⚠️ Unlike everything else here, **this path has not been exercised end to end** — it needs an interactive `sudo` for the tunnel. The manifest is written and applies cleanly; the routing itself is untested.

## Stretch goals (not built)

- HorizontalPodAutoscaler on the app Deployment
- Repackage as a Helm chart or Kustomize overlays
- NetworkPolicy between app/dashboard/egress
- Postgres StatefulSet replacing shared-SQLite-over-PVC
- TLS on the Ingress via cert-manager + mkcert
