import hashlib
import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .admin_models import JobAssignment
from .database import get_db
from .models import Application, Candidate, Interview, Job, User

SECRET='local-development-secret-change-in-production'
router=APIRouter(prefix='/api',tags=['administration'])


class UserIn(BaseModel):
    email: str=Field(min_length=5)
    password: str=Field(min_length=8)
    role: str='recruiter'


class AssignmentsIn(BaseModel):
    user_ids: list[int]


class StatusIn(BaseModel):
    status: str


def hash_password(password: str)->str:
    return hashlib.pbkdf2_hmac('sha256',password.encode(),b'recruitai-local',120_000).hex()


def session_user(authorization: Annotated[str|None,Header()]=None,db:Session=Depends(get_db))->User:
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401,'Authentication required')
    try: email=jwt.decode(authorization[7:],SECRET,algorithms=['HS256'])['sub']
    except (JWTError,KeyError): raise HTTPException(401,'Invalid token')
    user=db.scalar(select(User).where(User.email==email))
    if not user: raise HTTPException(401,'Unknown user')
    return user


def require_admin(user:User=Depends(session_user))->User:
    if user.role!='admin': raise HTTPException(403,'Administrator access required')
    return user


def accessible_jobs(db:Session,user:User)->list[Job]:
    jobs=list(db.scalars(select(Job).order_by(Job.id.desc())))
    if user.role=='admin': return jobs
    assigned=set(db.scalars(select(JobAssignment.job_id).where(JobAssignment.user_id==user.id)))
    any_assignments=set(db.scalars(select(JobAssignment.job_id)))
    return [job for job in jobs if job.id in assigned or job.id not in any_assignments]


def has_job_access(db:Session,user:User,job_id:int)->bool:
    return any(job.id==job_id for job in accessible_jobs(db,user))


@router.get('/me')
def me(user:User=Depends(session_user)):
    return {'id':user.id,'email':user.email,'role':user.role}


@router.get('/dashboard/metrics')
def dashboard(db:Session=Depends(get_db),user:User=Depends(session_user)):
    jobs=accessible_jobs(db,user);job_ids=[job.id for job in jobs]
    applications=list(db.scalars(select(Application).where(Application.job_id.in_(job_ids)))) if job_ids else []
    stages={stage:0 for stage in ['applied','screening','interview','offer','rejected']}
    for application in applications: stages[application.status]=stages.get(application.status,0)+1
    interviews=list(db.scalars(select(Interview).where(Interview.application_id.in_([a.id for a in applications])))) if applications else []
    scores=[a.match_score for a in applications]
    return {'jobs':{'total':len(jobs),'open':sum(j.status=='open' for j in jobs),'draft':sum(j.status=='draft' for j in jobs)},'applications':{'total':len(applications),'stages':stages,'average_match_score':round(sum(scores)/len(scores),1) if scores else 0},'interviews':{'total':len(interviews),'completed':sum(i.status=='analyzed' for i in interviews),'in_progress':sum(i.status in {'invited','prepared','in_progress'} for i in interviews)},'offer_rate':round(100*stages.get('offer',0)/len(applications),1) if applications else 0}


@router.get('/admin/users')
def users(db:Session=Depends(get_db),_:User=Depends(require_admin)):
    return [{'id':u.id,'email':u.email,'role':u.role} for u in db.scalars(select(User).order_by(User.id))]


@router.post('/admin/users')
def create_user(payload:UserIn,db:Session=Depends(get_db),_:User=Depends(require_admin)):
    if payload.role not in {'admin','recruiter','hiring_manager'}: raise HTTPException(400,'Unsupported role')
    if db.scalar(select(User).where(User.email==payload.email)): raise HTTPException(409,'Email already exists')
    user=User(email=payload.email,password_hash=hash_password(payload.password),role=payload.role);db.add(user);db.commit();db.refresh(user)
    return {'id':user.id,'email':user.email,'role':user.role}


@router.get('/admin/jobs/{job_id}/assignments')
def assignments(job_id:int,db:Session=Depends(get_db),_:User=Depends(require_admin)):
    return {'user_ids':list(db.scalars(select(JobAssignment.user_id).where(JobAssignment.job_id==job_id)))}


@router.put('/admin/jobs/{job_id}/assignments')
def update_assignments(job_id:int,payload:AssignmentsIn,db:Session=Depends(get_db),_:User=Depends(require_admin)):
    if not db.get(Job,job_id): raise HTTPException(404,'Job not found')
    existing=list(db.scalars(select(JobAssignment).where(JobAssignment.job_id==job_id)))
    for row in existing: db.delete(row)
    valid=set(db.scalars(select(User.id).where(User.id.in_(payload.user_ids)))) if payload.user_ids else set()
    for user_id in valid: db.add(JobAssignment(job_id=job_id,user_id=user_id))
    db.commit();return {'job_id':job_id,'user_ids':sorted(valid)}


@router.patch('/applications/{application_id}/status')
def update_application_status(application_id:int,payload:StatusIn,db:Session=Depends(get_db),user:User=Depends(session_user)):
    allowed={'applied','screening','interview','offer','rejected'}
    if payload.status not in allowed: raise HTTPException(400,'Unsupported application status')
    application=db.get(Application,application_id)
    if not application: raise HTTPException(404,'Application not found')
    if not has_job_access(db,user,application.job_id): raise HTTPException(403,'Job access denied')
    application.status=payload.status;db.commit();return {'id':application.id,'status':application.status}
