from pydantic import BaseModel, field_validator, ConfigDict
from datetime import datetime
from typing import Optional

# --- Resource Schemas ---
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

# --- Booking Schemas ---
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

