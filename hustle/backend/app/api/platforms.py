from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from ..core.database import get_db
from ..models import Platform
from ..schemas import PlatformResponse

router = APIRouter()

@router.get("/", response_model=List[PlatformResponse])
def get_platforms(db: Session = Depends(get_db)):
    platforms = db.query(Platform).all()
    return platforms

@router.get("/{platform_id}", response_model=PlatformResponse)
def get_platform(platform_id: int, db: Session = Depends(get_db)):
    platform = db.query(Platform).filter(Platform.platform_id == platform_id).first()
    if not platform:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="平台不存在"
        )
    return platform
