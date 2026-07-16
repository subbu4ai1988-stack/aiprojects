from pydantic import BaseModel, ConfigDict, Field


class Login(BaseModel):
    email: str
    password: str


class JobIn(BaseModel):
    title: str = Field(min_length=2)
    department: str = ""
    location: str = ""
    description: str = Field(min_length=10)
    status: str = "draft"
    ranking_params: dict = {}


class JobOut(JobIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class AnswerIn(BaseModel):
    question: str
    answer: str = Field(min_length=1)


class InterviewAnswers(BaseModel):
    answers: list[AnswerIn]

