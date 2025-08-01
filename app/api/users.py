import uuid

from fastapi import APIRouter, Request, Depends, HTTPException, status, UploadFile
from fastapi.responses import ORJSONResponse

from sqlalchemy import select

from typing import List

from rich.console import Console

from uuid import UUID

import logging

import sys

from app.schemas.users import UserRead, UserCreate, UserDelete, UserUpdate, UserPasswordUpdate, \
    UserPetitionPasswordUpdate
from app.models import User
from app.core.auth import JWTBearer
from app.db.main import SessionDep
from app.core.interfaces.emails import EmailService
from app.core.auth import encode, decode
from app.storage import storage

logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
handler.setFormatter(formatter)

logger.addHandler(handler)

console = Console()

auth = JWTBearer()

private_router = APIRouter(
    dependencies=[
        Depends(auth)
    ],
    redirect_slashes=True,
)

public_router = APIRouter(
    redirect_slashes=True,
)

@private_router.get("/", response_model=List[UserRead])
async def get_users(session: SessionDep):
    statement = select(User).where(True)
    result: List[User] = session.exec(statement).scalars().all()
    users = []
    console.print(result)
    console.print(User.__table__)
    for user in result:
        console.print(user)
        try:
            console.print(user.id)
        except Exception:
            console.print_exception(show_locals=True)
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
                dni=user.dni,
                address=user.address,
                telephone=user.telephone,
                blood_type=user.blood_type,
                img_profile=user.url_image_profile
            ).model_dump()
        )

    return ORJSONResponse(users)

@private_router.get("/{user_id}/")
async def get_user_by_id(session: SessionDep, user_id: UUID):
    statement = select(User).where(User.id == user_id)
    user: User = session.exec(statement).first()
    if not user:
        raise HTTPException(status_code=404, detail="Not found")

    return ORJSONResponse(
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
            dni=user.dni,
            blood_type=user.blood_type,
            address=user.address,
            telephone=user.telephone,
            img_profile=user.url_image_profile
        ).model_dump()
    )

@private_router.get("/me", response_model=UserRead)
async def me_user(request: Request):
    user: User = request.state.user

    if not isinstance(user, User):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Not authorized: {user}")


    return ORJSONResponse({
        "user":UserRead(
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
            dni=user.dni,
            telephone=user.telephone,
            blood_type=user.blood_type,
            address=user.address,
            img_profile=user.url_image_profile
        ).model_dump(),
    })

@public_router.post("/add/", response_model=UserRead)
async def add_user(session: SessionDep, user: UserCreate, img_profile: UploadFile):
    try:
        user_db = User(
            email=user.email,
            name=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            dni=user.dni,
            address=user.address,
            telephone=user.telephone,
            blood_type=user.blood_type
        )
        user_db.set_password(user.password)
        await user_db.save_profile_image(img_profile)
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
                dni=user_db.dni,
                address=user_db.address,
                telephone=user_db.telephone,
                blood_type=user_db.blood_type,
                img_profile=user_db.url_image_profile
            ).model_dump()
        )
    except Exception as e:
        console.print_exception(show_locals=True)
        return ORJSONResponse({"error": str(e)})

@private_router.delete("/delete/{user_id}/", response_model=UserDelete)
async def delete_user(request: Request, user_id: UUID, session: SessionDep):
    if not request.state.user.is_superuser or str(request.state.user.id) == user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    try:
        statement = select(User).where(User.id == user_id)
        user: User = session.exec(statement).scalar_one_or_none()
        session.delete(user)
        session.commit()
        user_deleted = UserDelete(
            id=user.id,
            username=user.name,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            dni=user.dni,
        )
        return ORJSONResponse(user_deleted.model_dump())
    except Exception:
        console.print_exception(show_locals=True)
        return ORJSONResponse({"error": "User not found"}, status_code=404)

@private_router.patch("/update/{user_id}/", response_model=UserRead)
async def update_user(request: Request, user_id: UUID, session: SessionDep, user_form: UserUpdate, img_profile: UploadFile):

    if not request.state.user.id == user_id and not request.state.user.is_superuser:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="scopes have not un unauthorized")

    statement = select(User).where(User.id == user_id)
    user: User = session.exec(statement).first()

    form_fields: List[str] = user_form.__fields__.keys()

    for field in form_fields:
        value = getattr(user_form, field, None)
        if value is not None and field != "username":
            setattr(user, field, value)
        elif field == "username":
            user.name = user_form.username

    if img_profile:
        await user.save_profile_image(img_profile)

    session.add(user)
    session.commit()
    session.refresh(user)

    return ORJSONResponse(
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
            dni=user.dni,
            blood_type=user.blood_type
        ).model_dump()
    )

@public_router.post("/update/petition/password")
async def update_petition_password(session: SessionDep, data: UserPetitionPasswordUpdate):
    try:
        user = session.exec(
            select(User)\
                .where(User.email == data.email)
        ).first()

        if not user:
            ORJSONResponse({"detail": "Ok 200"}, status_code=200)

        r_cod = encode({"info":"Tu_mama"}).hex()

        storage.set(key=user.email, value=r_cod, table_name="Nose")

        EmailService.send_password_reset_email(user.email, reset_code=r_cod)

    except Exception:
        console.print_exception(show_locals=True)
        return ORJSONResponse({"detail":"Ok 200"}, status_code=200)


@private_router.patch("/update/{user_id}/password", response_model=UserRead)
async def update_user_password(request: Request, user_id: UUID, session: SessionDep, user_form: UserPasswordUpdate):

    if not request.state.user.id == user_id and not request.state.user.is_superuser:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="scopes have not un unauthorized")

    result = session.exec(
        select(User).where(User.id == user_id)
    )

    user: User = result.first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.set_password(user_form.password)
    session.add(user)
    session.commit()
    session.refresh(user)

    return ORJSONResponse(
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
            dni=user.dni,
            blood_type=user.blood_type,
            telephone=user.telephone,
            address=user.address,
            img_profile=user.url_image_profile
        ).model_dump()
    )

@private_router.patch("/ban/{user_id}/", response_model=UserRead)
async def ban_user(request: Request, user_id: UUID, session: SessionDep):
    if not request.state.user.is_superuser:
        raise HTTPException(status_code=403, detail="Not authorized")

    statement = select(User).where(User.id == user_id)
    user: User = session.exec(statement).scalars().first()

    user.is_active = True
    session.commit()
    session.refresh(user)

    return ORJSONResponse({
        "user":UserRead(
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
            dni=user.dni,
            blood_type=user.blood_type,
            img_profile=user.url_image_profile
        ),
        "message":f"User {user.name} has been banned."
    })

@private_router.patch("/unban/{user_id}/", response_model=UserRead)
async def unban_user(request: Request, user_id: UUID, session: SessionDep):
    if not request.state.user.is_superuser:
        raise HTTPException(status_code=403, detail="Not authorized")

    statement = select(User).where(User.id == user_id)
    user: User = session.exec(statement).scalars().first()

    user.is_banned = False
    session.commit()
    session.refresh(user)

    return ORJSONResponse({
        "user":UserRead(
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
            dni=user.dni,
            blood_type=user.blood_type,
            img_profile=user.url_image_profile
        ),
        "message":f"User {user.name} has been unbanned."
    })

router = APIRouter(
    tags=["users"],
    prefix="/users",
    default_response_class=ORJSONResponse,
)

router.include_router(private_router)
router.include_router(public_router)