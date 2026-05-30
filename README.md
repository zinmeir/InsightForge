<div align="center">
  <h1>📊 InsightForge</h1>
  <p><b>Real-Time Log Ingestion & Observability Platform</b></p>
  
  ![React](https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB)
  ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
  ![Elasticsearch](https://img.shields.io/badge/Elasticsearch-005571?style=for-the-badge&logo=elasticsearch&logoColor=white)
  ![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
</div>

---

## 🚀 Overview

**InsightForge** is a high-performance, SRE-grade observability platform built to handle real-time log ingestion, indexing, and monitoring. Featuring a highly responsive Grafana-style dashboard and an async backend, it allows DevOps teams to monitor system health, instantly query unstructured logs, and trigger automated alerts based on custom rules.

### ✨ Core Features
* **High-Throughput Ingestion:** Leverages FastAPI's asynchronous event loop to buffer and batch log writes without blocking.
* **Full-Text Search:** Utilizes Elasticsearch for deep, instant querying and filtering of log messages and system metrics.
* **Grafana-Style UI:** A dark-mode React dashboard featuring live-updating Recharts and a streaming system terminal.
* **Active Alerting Pipeline:** A built-in service layer that evaluates incoming logs against configurable threshold rules to instantly flag critical system failures.
* **Fully Containerized:** Multi-container Docker orchestration for seamless deployment across any environment.

---

## 🏗️ Architecture & Tech Stack

| Component | Technology | Description |
|-----------|------------|-------------|
| **Frontend** | React, Vite, Recharts | Dynamic, auto-refreshing dashboard for data visualization and live log streaming. |
| **Backend** | Python, FastAPI | Async API handling incoming log payloads and orchestrating the alerting pipeline. |
| **Database** | Elasticsearch | Enterprise-grade search engine optimized for unstructured log indexing and rapid querying. |
| **DevOps** | Docker & Compose | Single-command local environment bootstrapping. |

---

## 🚦 Getting Started

Follow these steps to run the complete observability stack locally on your machine.

### Prerequisites
* [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.

### Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/zinmeir/insightforge.git](https://github.com/zinmeir/insightforge.git)
   cd insightforge
   ```

2. **Build and spin up the Docker containers:**
   *(Note: Elasticsearch may take 30-60 seconds to fully initialize)*
   ```bash
   docker compose up --build
   ```

3. **Access the application:**
   * **Live Dashboard (Frontend):** Navigate to `http://localhost:3000`
   * **API Swagger Docs (Backend):** Navigate to `http://localhost:8000/docs`
   * **Elasticsearch Node:** Navigate to `http://localhost:9200`

### 🧪 API Ingestion Test
You can simulate a microservice sending a log to the platform by running this `curl` command in your terminal:
```bash
curl -X POST "http://localhost:8000/api/ingest" \
-H "Content-Type: application/json" \
-d '{"level":"ERROR","service":"payment-gateway","message":"CRITICAL: Stripe API timeout detected"}'
```

---

## 🔮 Future Roadmap

The next phase of development focuses on expanding the alerting and integration capabilities:
* **Webhook Integrations:** Expanding the alerting pipeline to push critical alerts directly to Slack and PagerDuty via webhooks.
* **Advanced Aggregations:** Adding Kibana-style pie charts to the React UI to break down error rates by microservice.
* **Authentication:** Implementing JWT-based auth on the FastAPI backend to secure the ingestion endpoint.

---

<div align="center">
  <i>Built by <a href="https://github.com/zinmeir">Muhammad Shaheer Akhtar</a></i>
</div>
