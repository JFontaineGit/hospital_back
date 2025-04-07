from fastapi import APIRouter, Request, Depends
from fastapi.responses import ORJSONResponse

from sqlalchemy import select

from typing import List

from rich import print
from rich.console import Console

from app.schemas.users import UserRead, UserCreate, UserDelete, UserUpdate
from app.models.users import User
from app.db.main import SessionDep

console = Console()

router = APIRouter(
    tags=["users"],
    responses={404: {"description": "Not found"}},
    prefix="/users",
    default_response_class=ORJSONResponse,
)

@router.get("/", response_model=List[UserRead])
async def get_users(request: Request, session: SessionDep):
    statement = select(User)
    result: List[User] = session.execute(statement).scalars().all()
    users = []
    #print(result)
    for user in result:
        users.append(
            UserRead(
                id=user.id,
                is_active=user.is_active,
                is_admin=user.is_admin,
                is_superuser=user.is_superuser,
                last_login=user.last_login,
                date_joined=user.date_joined,
                username=user.name,
                email=user.email,
                first_name=user.first_name,
                last_name=user.last_name,
            ).model_dump()
        )

    return ORJSONResponse(users)

@router.post("/add/", response_model=UserRead)
async def add_user(request: Request, session: SessionDep, user: UserCreate):
    try:
        user_db = User(
            email=user.email,
            name=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )
        user_db.set_password(user.password)
        session.add(user_db)
        session.commit()
        session.refresh(user_db)
        return ORJSONResponse(
            UserRead(
                id=user_db.id,
                is_active=user_db.is_active,
                is_admin=user_db.is_admin,
                is_superuser=user_db.is_superuser,
                last_login=user_db.last_login,
                date_joined=user_db.date_joined,
                username=user_db.name,
                email=user_db.email,
                first_name=user_db.first_name,
                last_name=user_db.last_name,
            ).model_dump()
        )
    except Exception as e:
        console.print_exception(show_locals=True)
        return ORJSONResponse({"error": str(e)})

@router.delete("/delete/{user_id}/", response_model=UserDelete)
async def delete_user(request: Request, user_id: str, session: SessionDep):
    try:
        statement = select(User).where(User.id == user_id)
        user: User = session.execute(statement).scalars().first()
        session.delete(user)
        session.commit()
        #session.refresh(user)
        user_deleted = UserDelete(
            id=user.id,
            username=user.name,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
        )
        return ORJSONResponse(user_deleted.model_dump())
    except Exception:
        console.print_exception(show_locals=True)
        return ORJSONResponse({"error": "User not found"}, status_code=404)