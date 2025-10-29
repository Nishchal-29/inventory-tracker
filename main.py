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
        await notifier.listen_to_channel('inventory_channel')
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

@app.get("/")
async def root():
    # Serve the main page
    with open("static/index.html", "r") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/api/inventory", response_model=List[InventoryResponse])
async def get_inventory(db: AsyncSession = Depends(get_async_db)):
    # Get all inventory items
    result = await db.execute(select(Inventory).order_by(Inventory.updated_at.desc()))
    items = result.scalars().all()
    return items

@app.post("/api/inventory", response_model=InventoryResponse)
async def create_inventory_item(item: InventoryCreate, db: AsyncSession = Depends(get_async_db)):
    # Create a new inventory item
    db_item = Inventory(**item.dict())
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item

@app.put("/api/inventory/{item_id}", response_model=InventoryResponse)
async def update_inventory_item(item_id: int, item_update: InventoryUpdate, db: AsyncSession = Depends(get_async_db)):
    # Update an inventory item's quantity
    result = await db.execute(select(Inventory).where(Inventory.id == item_id))
    db_item = result.scalar_one_or_none()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")
    db_item.quantity = item_update.quantity
    await db.commit()
    await db.refresh(db_item)
    return db_item

@app.delete("/api/inventory/{item_id}")
async def delete_inventory_item(item_id: int, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Inventory).where(Inventory.id == item_id))
    db_item = result.scalar_one_or_none()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")
    await db.delete(db_item)
    await db.commit()
    return {"message" : "item deleted successfully"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)