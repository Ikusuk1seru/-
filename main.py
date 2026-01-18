from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, and_
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session
from pydantic import BaseModel, field_validator, ConfigDict
from datetime import datetime, timedelta
from typing import List, Optional
import nest_asyncio


# --- 1. CONFIG & DATABASE SETUP ---
DATABASE_URL = "sqlite:///./test.db"

# Створення рушія БД
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Оголошення Base для моделей
Base = declarative_base()
nest_asyncio.apply()

# --- 2. MODELS (SQLAlchemy) ---
class Resource(Base):
    __tablename__ = "resources"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    
    bookings = relationship("Booking", back_populates="resource")

class Booking(Base):
    __tablename__ = "bookings"
    
    id = Column(Integer, primary_key=True, index=True)
    resource_id = Column(Integer, ForeignKey("resources.id"), nullable=False)
    customer_name = Column(String, nullable=False)
    start_at = Column(DateTime, nullable=False)
    end_at = Column(DateTime, nullable=False)
    status = Column(String, default="active")
    created_at = Column(DateTime, default=datetime.utcnow)

    resource = relationship("Resource", back_populates="bookings")

# --- 3. SCHEMAS (Pydantic v2) ---
class ResourceBase(BaseModel):
    name: str
    type: str
    is_active: bool = True

class ResourceCreate(ResourceBase):
    pass

class ResourceUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None

class ResourceResponse(ResourceBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class BookingCreate(BaseModel):
    resource_id: int
    customer_name: str
    start_at: datetime
    end_at: datetime

    @field_validator('end_at')
    @classmethod
    def check_dates(cls, v, values):
        if 'start_at' in values.data and v <= values.data['start_at']:
            raise ValueError('end_at must be greater than start_at')
        return v

class BookingResponse(BaseModel):
    id: int
    resource_id: int
    customer_name: str
    start_at: datetime
    end_at: datetime
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- 4. APP & DEPENDENCIES ---
# Створюємо таблиці в БД
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Booking Slots API")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- 5. ROUTES ---

# === Resources ===
@app.post("/resources", response_model=ResourceResponse)
def create_resource(resource: ResourceCreate, db: Session = Depends(get_db)):
    db_resource = Resource(**resource.model_dump())
    db.add(db_resource)
    db.commit()
    db.refresh(db_resource)
    return db_resource

@app.get("/resources/{resource_id}", response_model=ResourceResponse)
def get_resource(resource_id: int, db: Session = Depends(get_db)):
    res = db.query(Resource).filter(Resource.id == resource_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Resource not found")
    return res

@app.patch("/resources/{resource_id}", response_model=ResourceResponse)
def update_resource(resource_id: int, update_data: ResourceUpdate, db: Session = Depends(get_db)):
    res = db.query(Resource).filter(Resource.id == resource_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Resource not found")
    
    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(res, key, value)
    
    db.commit()
    db.refresh(res)
    return res

# === Bookings ===
@app.post("/bookings", response_model=BookingResponse)
def create_booking(booking: BookingCreate, db: Session = Depends(get_db)):
    # 1. Перевірка ресурсу
    resource = db.query(Resource).filter(Resource.id == booking.resource_id).first()
    if not resource or not resource.is_active:
        raise HTTPException(status_code=400, detail="Resource not found or inactive")

    # 2. Перевірка конфліктів
    conflict = db.query(Booking).filter(
        Booking.resource_id == booking.resource_id,
        Booking.status == "active",
        and_(
            Booking.start_at < booking.end_at,
            Booking.end_at > booking.start_at
        )
    ).first()

    if conflict:
        raise HTTPException(status_code=409, detail="Time slot already booked")

    new_booking = Booking(**booking.model_dump(), status="active")
    db.add(new_booking)
    db.commit()
    db.refresh(new_booking)
    return new_booking

@app.get("/bookings", response_model=List[BookingResponse])
def get_bookings(
    resource_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Booking)
    
    if resource_id:
        query = query.filter(Booking.resource_id == resource_id)
    if date_from:
        query = query.filter(Booking.start_at >= date_from)
    if date_to:
        query = query.filter(Booking.end_at <= date_to)
    if status:
        query = query.filter(Booking.status == status)
        
    return query.order_by(Booking.start_at).all()

@app.post("/bookings/{booking_id}/cancel", response_model=BookingResponse)
def cancel_booking(booking_id: int, db: Session = Depends(get_db)):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    booking.status = "canceled"
    db.commit()
    db.refresh(booking)
    return booking

# === Availability ===
@app.get("/resources/{resource_id}/availability")
def get_availability(
    resource_id: int,
    date: str,
    slot_minutes: int = 30,
    work_start: str = "09:00",
    work_end: str = "18:00",
    db: Session = Depends(get_db)
):
    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
        start_t = datetime.strptime(work_start, "%H:%M").time()
        end_t = datetime.strptime(work_end, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date/time format")

    day_start = datetime.combine(target_date, start_t)
    day_end = datetime.combine(target_date, end_t)

    bookings = db.query(Booking).filter(
        Booking.resource_id == resource_id,
        Booking.status == "active",
        Booking.end_at > day_start,
        Booking.start_at < day_end
    ).order_by(Booking.start_at).all()

    available_slots = []
    current_slot = day_start

    while current_slot + timedelta(minutes=slot_minutes) <= day_end:
        slot_end = current_slot + timedelta(minutes=slot_minutes)
        is_free = True
        
        for b in bookings:
            if current_slot < b.end_at and slot_end > b.start_at:
                is_free = False
                break
        
        if is_free:
            available_slots.append({
                "start": current_slot.isoformat(),
                "end": slot_end.isoformat()
            })
        
        current_slot += timedelta(minutes=slot_minutes)

    return {"resource_id": resource_id, "date": date, "available_slots": available_slots}

import nest_asyncio
import uvicorn

nest_asyncio.apply()

if __name__ == "__main__":
    # Запускаємо сервер
    uvicorn.run(app, host="127.0.0.1", port=8000)