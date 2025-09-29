from fastapi import APIRouter, Request, Depends, HTTPException, Header, status, Form
from fastapi.responses import ORJSONResponse

from rich.console import Console

from typing import Optional, Dict, List, Annotated

from sqlmodel import select

from datetime import datetime

from app.config import debug
from app.models import Doctors, User
from app.db.main import SessionDep
from app.core.auth import gen_token, JWTBearer, decode, generate_csrf_token, validate_csrf_token, decode_token
from app.core.interfaces.oauth import OauthRepository
from app.core.interfaces.users import UserRepository
from app.core.interfaces.emails import EmailService
from app.schemas.users import UserAuth
from app.schemas.auth import TokenUserResponse, TokenDoctorsResponse, OauthCodeInput
from app.schemas.medica_area import DoctorAuth, DoctorResponse
from app.storage import storage

console = Console()

auth = JWTBearer()

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)

oauth_router = APIRouter(
    prefix="/oauth",
    tags=["oauth"]
)

@router.get("/scopes", response_model=Dict[str, List[str]])
async def get_scopes(request: Request, _=Depends(auth)):
    scopes = request.state.scopes
    return ORJSONResponse({
        "scopes": scopes,
    })

@router.post("/decode/")
async def decode_hex(data: OauthCodeInput):
    bytes_code = bytes.fromhex(data.code)
    return decode(bytes_code, dict)

@router.post("/doc/login", response_model=TokenDoctorsResponse)
async def doc_login(session: SessionDep, credentials: Annotated[DoctorAuth, Form(...)]) -> ORJSONResponse:
    statement = select(Doctors).where(Doctors.email == credentials.email)
    result = session.exec(statement)
    doc: Doctors = result.first()
    if not doc:
        raise HTTPException(status_code=404, detail="Invalid credentials")

    if not doc.check_password(credentials.password):
        raise HTTPException(status_code=404, detail="Invalid credentials")

    doc_data = {
        "sub": str(doc.id),
        "scopes": ["doc"]
    }

    if doc.is_active:
        doc_data["scopes"].append("active")

    token = gen_token(doc_data)
    refresh_token = gen_token(doc_data, refresh=True)
    csrf_token = generate_csrf_token()

    doc.last_login = datetime.now()

    response = ORJSONResponse(
        TokenDoctorsResponse(
            access_token=token,
            token_type="Bearer",
            doc=DoctorResponse(
                id=doc.id,
                username=doc.name,
                last_name=doc.last_name,
                first_name=doc.first_name,
                dni=doc.dni,
                telephone=doc.telephone,
                email=doc.email,
                speciality_id=doc.speciality_id,
                is_active=doc.is_active,
                is_admin=doc.is_admin,
                is_superuser=doc.is_superuser,
                last_login=doc.last_login,
                date_joined=doc.date_joined,
                address=doc.address
            ),
            refresh_token=refresh_token
        ).model_dump()
    )

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=False,
        secure=not debug, 
        samesite="None",
        max_age=15 * 60,
        path="/"
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=not debug,
        samesite="None",
        max_age=24 * 60 * 60,
        path="/"
    )
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        secure=not debug,
        samesite="None",
        max_age=24 * 60 * 60,
        path="/"
    )

    return response

@router.post("/login", response_model=TokenUserResponse)
async def login(session: SessionDep, credentials: Annotated[UserAuth, Form(...)]) -> ORJSONResponse:
    console.print(credentials)
    statement = select(User).where(User.email == credentials.email)
    result = session.exec(statement)
    user: User = result.first()
    console.print(user)
    if not user:
        raise HTTPException(status_code=404, detail="Invalid credentials payload")

    if not user.check_password(credentials.password):
        raise HTTPException(status_code=400, detail="Invalid credentials payload")

    user_data = {
        "sub": str(user.id),
        "scopes": []
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
    csrf_token = generate_csrf_token()

    user.last_login = datetime.now()

    session.add(user)
    session.commit()
    session.refresh(user)

    response = ORJSONResponse(
        TokenUserResponse(
            access_token=token,
            token_type="Bearer",
            refresh_token=refresh_token,
        ).model_dump()
    )

    # Cookies seguras
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=False,
        secure=not debug,
        samesite="None",
        max_age=15 * 60,
        path="/"
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=not debug,
        samesite="None",
        max_age=24 * 60 * 60,
        path="/"
    )
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        secure=not debug,
        samesite="None",
        max_age=24 * 60 * 60,
        path="/"
    )

    return response

@oauth_router.get("/{service}/")
async def oauth_login(service: str):
    try:
        match service:
            case "google":
                return OauthRepository.google_oauth()
            case _:
                raise HTTPException(status_code=501, detail="Not Implemented")
    except Exception as e:
        console.print_exception(show_locals=True)
        raise HTTPException(status_code=500, detail=str(e))

@oauth_router.get("/webhook/google_callback")
async def google_callback(request: Request):
    try:
        params: dict = dict(request.query_params)
        data, exist, response = OauthRepository.google_callback(params.get("code"))
        if not exist:
            EmailService.send_welcome_email(
                email=data.get("email"),
                first_name=data.get("given_name"),
                last_name=data.get("family_name")
            )
            EmailService.send_google_account_linked_password(email=data.get("email"), first_name=data.get("given_name"),
                                                             last_name=data.get("family_name"),
                                                             raw_password=data.get("id"))

        return response
    except Exception as e:
        console.print_exception(show_locals=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/refresh", response_model=TokenUserResponse, name="refresh_token")
async def refresh(request: Request, user: User = Depends(auth)) -> ORJSONResponse:
    validate_csrf_token(request)

    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            refresh_token = auth_header.split(" ")[1]
        else:
            raise HTTPException(status_code=401, detail="Missing refresh token")

    try:
        old_payload = decode_token(refresh_token)
        if old_payload.get("type") != "refresh_token":
            raise ValueError("Invalid refresh token")
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    user_id = old_payload["sub"]
    old_jti = old_payload["jti"]
    ban_set = storage.get(key=user_id, table_name="ban-token") or set()
    if isinstance(ban_set, str): 
        ban_set = {ban_set}
    ban_set.add(old_jti)
    storage.set(key=user_id, value=ban_set, table_name="ban-token")

    if isinstance(user, Doctors):
        doc_data = {
            "sub": str(user.id),
            "scopes": ["doc"]
        }
        if user.is_active:
            doc_data["scopes"].append("active")

        new_token = gen_token(doc_data)
        new_refresh_token = gen_token(doc_data, refresh=True)

        response = ORJSONResponse(
            TokenDoctorsResponse(
                access_token=new_token,
                token_type="Bearer",
                doc=DoctorResponse(
                    id=user.id,
                    username=user.name,
                    last_name=user.last_name,
                    first_name=user.first_name,
                    dni=user.dni,
                    telephone=user.telephone,
                    email=user.email,
                    speciality_id=user.speciality_id,
                    is_active=user.is_active,
                    is_admin=user.is_admin,
                    is_superuser=user.is_superuser,
                    last_login=user.last_login,
                    date_joined=user.date_joined,
                ),
                refresh_token=new_refresh_token
            ).model_dump()
        )
    else:
        user_data = {
            "sub": str(user.id),
            "scopes": []
        }
        if user.is_admin:
            user_data["scopes"].append("admin")
        if user.is_superuser:
            user_data["scopes"].append("superuser")
        else:
            user_data["scopes"].append("user")
        if user.is_active:
            user_data["scopes"].append("active")
        if "google" in request.state.scopes:
            user_data["scopes"].append("google")

        new_token = gen_token(user_data)
        new_refresh_token = gen_token(user_data, refresh=True)

        response = ORJSONResponse(
            TokenUserResponse(
                access_token=new_token,
                token_type="bearer",
                refresh_token=new_refresh_token,
            ).model_dump()
        )

    # Setea nuevas cookies
    response.set_cookie(
        key="access_token",
        value=new_token,
        httponly=False,
        secure=not debug,
        samesite="None",
        max_age=15 * 60,
        path="/"
    )
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=not debug,
        samesite="None",
        max_age=24 * 60 * 60,
        path="/"
    )

    return response

@router.delete("/logout")
async def logout(request: Request, authorization: Optional[str] = Header(None), _=Depends(auth)) -> ORJSONResponse:
    validate_csrf_token(request)

    session_user = request.state.user
    user_id = str(session_user.id)

    access_token = request.cookies.get("access_token") or (authorization.split(" ")[1] if authorization else None)
    refresh_token = request.cookies.get("refresh_token")

    ban_set = storage.get(key=user_id, table_name="ban-token") or set()
    if isinstance(ban_set, str): 
        ban_set = {ban_set}

    if access_token:
        access_payload = decode_token(access_token)
        ban_set.add(access_payload["jti"])
    if refresh_token:
        refresh_payload = decode_token(refresh_token)
        ban_set.add(refresh_payload["jti"])

    storage.set(key=user_id, value=ban_set, table_name="ban-token")

    response = ORJSONResponse({"msg": "logged out"})

    # Borra cookies
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    response.delete_cookie("csrf_token", path="/")

    return response