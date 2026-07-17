from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class JobAssignment(Base):
    __tablename__ = 'job_assignments'
    __table_args__ = (UniqueConstraint('job_id','user_id',name='uq_job_assignment'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'),index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'),index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime,default=datetime.utcnow)

