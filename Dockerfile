FROM python:3.11-slim

WORKDIR /app

# System deps for common Python packages
RUN apt-get update     && apt-get install -y --no-install-recommends build-essential     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

EXPOSE 8510

CMD ["streamlit", "run", "ui/app.py", "--server.address=0.0.0.0", "--server.port=8510"]
