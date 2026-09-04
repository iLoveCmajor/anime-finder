run:
	uv run streamlit run app.py

dashboard:
	uv run streamlit run dashboard.py --server.port 8502

docker-up:
	docker compose up --build

docker-down:
	docker compose down
