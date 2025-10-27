import asyncio
import logging
import json
from contextlib import asynccontextmanager
from typing import List
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from database import get_db, get_async_db, engine, Base, ASYNC_DATABASE_URL
from models import Inventory, InventoryCreate, InventoryUpdate, InventoryResponse
from notify import PostgresNotifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Error sending message to WebSocket: {e}")
                disconnected.append(connection)
                
        for connection in disconnected:
            self.active_connections.remove(connection)
            
manager = ConnectionManager()
notifier = None

async def handle_postgres_notification(data: dict):
    await manager.broadcast(data)
    
async def start_postgres_listener():
    try:
        await notifier.listen_to_change('inventory_channel')
        await notifier.start_listening()
    except Exception as e:
        logger.error(f"Error in PostgreSQL listener: {e}")
    
@asynccontextmanager
async def lifespan(app: FastAPI):
    global notifier
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")
    
    notifier = PostgresNotifier(ASYNC_DATABASE_URL.replace("+asyncpg", ""))
    notifier.add_listener(handle_postgres_notification)
    task = asyncio.create_task(start_postgres_listener())
    yield
    task.cancel()
    if notifier:
        await notifier.disconnect()
        
app = FastAPI(title = "Inventory Tracker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")