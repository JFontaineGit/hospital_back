from fastapi import APIRouter, Request, Depends, HTTPException, Header, status, Response
from fastapi.responses import ORJSONResponse

from rich import print
from rich.console import Console

from typing import List, Optional

from sqlmodel import select

from app.models.users import User
from app.models.medic_area import Doctors
from app.db.main import SessionDep
from app.core.auth import gen_token, JWTBearer, decode_token
from app.schemas.users import UserAuth, UserRead
from app.schemas.auth import TokenUserResponse, TokenDoctorsResponse
from app.schemas.medica_area import DoctorAuth, DoctorResponse

console = Console()

auth = JWTBearer(auto_error=False)

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)

@router.post("/doc/login", response_model=TokenDoctorsResponse)
async def doc_login(request: Request, session: SessionDep, credentials: DoctorAuth):
    statement = select(Doctors).where(Doctors.email == credentials.email)
    result = session.execute(statement)
    doc: Doctors = result.scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="Invalid credentials")

    if not doc.check_password(credentials.password):
        raise HTTPException(status_code=404, detail="Invalid credentials")

    doc_data = {
        "sub":doc.id,
        "scopes":["doc"]
    }

    token = gen_token(doc_data)
    refresh_token = gen_token(doc_data)

    return ORJSONResponse(
        TokenDoctorsResponse(
            access_token=token,
            token_type="Bearer",
            doc=DoctorResponse(
                id=doc.id,
                name=doc.name,
                lastname=doc.lastname,
                dni=doc.dni,
                telephone=doc.telephone,
                email=doc.email,
                speciality_id=doc.speciality_id
            ),
            refresh_token=refresh_token
        ).model_dump()
    )

@router.post("/login", response_model=TokenUserResponse)
async def login(request: Request, session: SessionDep, credentials: UserAuth):
    statement = select(User).where(User.email == credentials.email)
    result = session.execute(statement)
    user: User = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Invalid credentials payload")

    if not user.check_password(credentials.password):
        raise HTTPException(status_code=400, detail="Invalid credentials payload")

    user_data = {
        "sub":user.id,
        "scopes":[]
    }

    if user.is_admin:
        user_data["scopes"].append("admin")

    if user.is_superuser:
        user_data["scopes"].append("superuser")
    else:
        user_data["scopes"].append("user")

    if user.is_active:
        user_data["scopes"].append("active")

    token = gen_token(user_data)
    refresh_token = gen_token(user_data, refresh=True)

    return ORJSONResponse(
        TokenUserResponse(
            access_token=token,
            token_type="Bearer",
            user=UserRead(
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
            ),
            refresh_token=refresh_token,
        ).model_dump()
    )

@router.get("/refresh", response_model=TokenUserResponse)
async def refresh(request: Request, user: User = Depends(auth)):

    if isinstance(user, Doctors):
        doc_data = {
            "sub":user.id,
            "scopes":["doc"]
        }

        token = gen_token(doc_data)
        refresh_token = gen_token(doc_data)

        return ORJSONResponse(
            TokenDoctorsResponse(
                access_token=token,
                token_type="Bearer",
                doc=DoctorResponse(
                    id=user.id,
                    name=user.name,
                    lastname=user.lastname,
                    dni=user.dni,
                    telephone=user.telephone,
                    email=user.email,
                    speciality_id=user.speciality_id
                ),
                refresh_token=refresh_token
            ).model_dump()
        )

    user_data = {
        "sub":user.id,
        "scopes":[]
    }

    if user.is_admin:
        user_data["scopes"].append("admin")

    if user.is_superuser:
        user_data["scopes"].append("superuser")
    else:
        user_data["scopes"].append("user")

    if user.is_active:
        user_data["scopes"].append("active")

    token = gen_token(user_data)
    refresh_token = gen_token(user_data, refresh=True)

    return ORJSONResponse(
        TokenUserResponse(
            access_token=token,
            token_type="bearer",
            user=UserRead(
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
            ),
            refresh_token=refresh_token,
        ).model_dump()
    )

@router.put("/session")
async def gen_session(request: Request, authorization: Optional[str] = Header(None)):
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No credentials provided or invalid format"
        )

    token = authorization.split(" ")[1]

    payload = decode_token(token)

    response = ORJSONResponse({
        "session": True,
        "state":"gen_session"
    })

    response.set_cookie(
        key="session",
        value=token,
        max_age=payload.get("exp", 3600),
        expires=payload.get("exp", 3600),
        httponly=False,
        samesite="lax"
    )

    return response

@router.delete("/logout")
async def logout(request: Request, user: User = Depends(auth)):
    session = request.cookies.get("session", None)
    if session is None:
        raise HTTPException(status_code=404, detail="Invalid session cookie")

    response = ORJSONResponse({
        "session": session,
        "state": "logout"
    })

    response.delete_cookie("session")

    return response