run:
	uv run streamlit run app.py

dashboard:
	uv run streamlit run dashboard.py --server.port 8502

docker-up:
	docker compose up --build

docker-down:
	docker compose down

k8s-build:
	docker build -t anime-finder:latest .
	minikube image load anime-finder:latest

k8s-namespace:
	kubectl apply -f k8s/00-namespace.yaml

# The Secret mirrors .env exactly, so .env must hold only this app's
# credentials — anything else in it lands in the cluster for no reason and is
# readable by anyone with namespace access. Today that is OPENAI_API_KEY, plus
# APP_PASSWORD if you set one. --dry-run | apply (rather than plain create)
# makes this re-runnable and prunes keys that have been removed from .env.
k8s-secret: k8s-namespace
	kubectl create secret generic anime-finder-secrets \
	  --from-env-file=.env --namespace=anime-finder \
	  --dry-run=client -o yaml | kubectl apply -f -

# Ingress is deliberately NOT applied here — it is an optional access path that
# needs the ingress addon and a tunnel. See `make k8s-ingress`.
k8s-apply: k8s-secret
	kubectl apply -f k8s/00-namespace.yaml -f k8s/01-configmap.yaml \
	  -f k8s/03-pvc.yaml \
	  -f k8s/04-deployment-app.yaml -f k8s/05-service-app.yaml \
	  -f k8s/06-deployment-dashboard.yaml -f k8s/07-service-dashboard.yaml
	kubectl rollout restart deployment/anime-finder-app deployment/anime-finder-dashboard -n anime-finder
	kubectl rollout status deployment/anime-finder-app -n anime-finder --timeout=120s
	kubectl rollout status deployment/anime-finder-dashboard -n anime-finder --timeout=120s

k8s-ingress:
	kubectl apply -f k8s/08-ingress.yaml
	@echo "Applied. Requires 'minikube addons enable ingress' and 'sudo minikube tunnel'."
	@echo "Then add to /etc/hosts:  127.0.0.1  anime-finder.local dashboard.anime-finder.local"

k8s-status:
	kubectl get all -n anime-finder

k8s-open-app:
	minikube service anime-finder-app -n anime-finder

k8s-open-dashboard:
	minikube service anime-finder-dashboard -n anime-finder

k8s-url:
	@echo "Optional: Ingress host-based routing instead of 'make k8s-open-*'."
	@echo "Run 'make k8s-ingress' first, then 'sudo minikube tunnel' in a separate"
	@echo "terminal, then add to /etc/hosts:"
	@echo "  127.0.0.1  anime-finder.local dashboard.anime-finder.local"
	@echo "Then: open http://anime-finder.local  /  http://dashboard.anime-finder.local"

k8s-delete:
	kubectl delete -f k8s/08-ingress.yaml -f k8s/07-service-dashboard.yaml \
	  -f k8s/06-deployment-dashboard.yaml -f k8s/05-service-app.yaml \
	  -f k8s/04-deployment-app.yaml -f k8s/03-pvc.yaml -f k8s/01-configmap.yaml \
	  --ignore-not-found
	kubectl delete secret anime-finder-secrets -n anime-finder --ignore-not-found
	kubectl delete -f k8s/00-namespace.yaml --ignore-not-found
