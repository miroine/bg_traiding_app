FROM python:3.12-slim

WORKDIR /app

# Install deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persist the portfolio outside the container by mounting a volume at /data
ENV PORTFOLIO_DB=/data/portfolio.db
VOLUME ["/data"]

EXPOSE 8501
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Set APP_PASSWORD at run time to lock the app:
#   docker run -p 8501:8501 -v $PWD/data:/data -e APP_PASSWORD=secret oslo-desk
ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
