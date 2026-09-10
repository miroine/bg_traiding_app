.PHONY: install run test lint alerts docker

install:
	pip install -r requirements.txt

run:
	streamlit run app.py

test:
	-pip install pytest >/dev/null 2>&1
	pytest

lint:
	ruff check .

alerts:
	python alert_runner.py

docker:
	docker build -t oslo-desk .
