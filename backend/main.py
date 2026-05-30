import os
import time
import asyncio
from datetime import datetime, timezone
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from elasticsearch import AsyncElasticsearch
from elasticsearch.exceptions import ConnectionError

app = FastAPI(title="InsightForge API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ES_URL = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
es = AsyncElasticsearch(ES_URL)
INDEX_NAME = "insightforge-logs"

# In-memory mock alert store for the UI
active_alerts = []

class LogEntry(BaseModel):
    level: str = Field(..., pattern="^(INFO|WARN|ERROR|CRITICAL)$")
    service: str
    message: str
    timestamp: str | None = None

async def init_elasticsearch():
    """Retry logic for connecting to ES on startup and creating the index with mappings."""
    retries = 5
    while retries > 0:
        try:
            if await es.ping():
                print("✅ Successfully connected to Elasticsearch")
                
                # Define mapping for optimized aggregations and full-text search
                mapping = {
                    "mappings": {
                        "properties": {
                            "timestamp": {"type": "date"},
                            "level": {"type": "keyword"},
                            "service": {"type": "keyword"},
                            "message": {"type": "text"}
                        }
                    }
                }
                
                exists = await es.indices.exists(index=INDEX_NAME)
                if not exists:
                    await es.indices.create(index=INDEX_NAME, body=mapping)
                    print(f"✅ Created index: {INDEX_NAME}")
                break
        except ConnectionError:
            print(f"⏳ Waiting for Elasticsearch... ({retries} retries left)")
            retries -= 1
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    await init_elasticsearch()

@app.on_event("shutdown")
async def shutdown_event():
    await es.close()

async def evaluate_alerts(log: dict):
    """Configurable Alerting Pipeline evaluator."""
    if log["level"] == "CRITICAL":
        active_alerts.insert(0, {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trigger": "CRITICAL_LOG",
            "service": log["service"],
            "detail": log["message"]
        })
    # Keep only the latest 20 alerts
    if len(active_alerts) > 20:
        active_alerts.pop()

async def async_write_to_es(log_document: dict):
    """Background task to write to Elasticsearch gracefully."""
    await es.index(index=INDEX_NAME, document=log_document)

@app.post("/api/ingest")
async def ingest_log(log: LogEntry, background_tasks: BackgroundTasks):
    log_doc = log.dict()
    if not log_doc.get("timestamp"):
        log_doc["timestamp"] = datetime.now(timezone.utc).isoformat()
        
    # Process alerts asynchronously
    await evaluate_alerts(log_doc)
    
    # Delegate ES write to background task for maximum throughput
    background_tasks.add_task(async_write_to_es, log_doc)
    
    return {"status": "accepted"}

@app.get("/api/logs")
async def get_logs(limit: int = 50, service: str = None, keyword: str = None):
    query = {"bool": {"must": []}}
    
    if service:
        query["bool"]["must"].append({"term": {"service": service}})
    if keyword:
        query["bool"]["must"].append({"match": {"message": keyword}})
        
    if not query["bool"]["must"]:
        query = {"match_all": {}}
        
    try:
        res = await es.search(
            index=INDEX_NAME,
            query=query,
            sort=[{"timestamp": {"order": "desc"}}],
            size=limit
        )
        logs = [hit["_source"] for hit in res["hits"]["hits"]]
        return {"logs": logs, "alerts": active_alerts}
    except Exception as e:
        return {"logs": [], "alerts": active_alerts, "error": str(e)}
