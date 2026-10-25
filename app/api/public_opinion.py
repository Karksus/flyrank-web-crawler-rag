import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_active_user
from app.db.session import get_db
from app.models.company import Company
from app.models.user import User
from app.schemas.public_opinion import PublicOpinionResponse
from app.services.public_opinion import public_opinion_service

router = APIRouter(prefix="/companies", tags=["public-opinion"])
logger = logging.getLogger(__name__)


@router.get("/{company_id}/public-opinion", response_model=PublicOpinionResponse)
async def get_public_opinion(
    company_id: int,
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if not settings.PUBLIC_OPINION_ENABLED:
        raise HTTPException(status_code=503, detail="Public opinion checks are disabled")

    company = (
        db.query(Company)
        .filter(Company.id == company_id, Company.user_id == current_user.id)
        .first()
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    try:
        return await public_opinion_service.check(
            company_id=company.id,
            company_name=company.name,
            domain=company.domain,
            refresh=refresh,
        )
    except Exception:
        logger.exception(
            "Public opinion check failed for company %s (%s)",
            company.id,
            company.domain,
        )
        raise HTTPException(
            status_code=502,
            detail="Could not complete the public opinion check. Please try again.",
        )
