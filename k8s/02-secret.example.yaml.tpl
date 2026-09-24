# Reference only — shows the shape of the Secret this app needs.
#
# Deliberately NOT a .yaml file: `kubectl apply -f k8s/` reads every .yaml in
# the directory, so if this were one, applying the folder would overwrite the
# real Secret with the placeholder below and the app would start with an
# invalid key. The .tpl extension keeps it readable here and skipped there.
#
# The real Secret is created imperatively from .env via `make k8s-secret`, so
# no credential is ever written to a file on disk or committed to git.
#
# APP_PASSWORD is optional: `auth.py` no-ops when it is unset, which is fine
# locally. Set it in .env before exposing this deployment publicly, or the app
# is open to anyone who can reach it — and every query bills OPENAI_API_KEY.
apiVersion: v1
kind: Secret
metadata:
  name: hf-model-finder-secrets
  namespace: hf-model-finder
type: Opaque
stringData:
  OPENAI_API_KEY: "REPLACE_ME"
  APP_PASSWORD: ""
