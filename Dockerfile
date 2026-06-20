FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY whoop_policy_layer ./whoop_policy_layer

CMD ["python", "-m", "whoop_policy_layer.server"]
