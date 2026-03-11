import hmac
import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional
import urllib.parse

from fastapi import FastAPI, HTTPException, Request, Depends, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sys
from pathlib import Path

# Добавляем путь к основному проекту
sys.path.append(str(Path(__file__).parent.parent))

from config import TOKEN as BOT_TOKEN, DATABASE_URL
from sql_app import models
from sql_app.database import Session, engine

# Создаем таблицы, если их нет
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Telegram Web App для учета контингента")

# Разрешаем CORS для разработки
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем статические файлы
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# Создаем папки, если их нет
STATIC_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ========== ВРЕМЕННО: УПРОЩЕННАЯ ВАЛИДАЦИЯ ==========

async def get_current_user(authorization: Optional[str] = Header(None)):
    """
    ВРЕМЕННО: Упрощенная проверка для разработки
    """
    if not authorization or not authorization.startswith('tg '):
        # Для теста возвращаем тестового пользователя
        return {
            "id": 123456789,
            "first_name": "Test",
            "last_name": "User",
            "username": "test_user"
        }
    
    try:
        init_data = authorization[3:]
        parsed_data = {}
        for item in init_data.split('&'):
            if '=' in item:
                key, value = item.split('=', 1)
                parsed_data[key] = urllib.parse.unquote(value)
        
        # Извлекаем пользователя
        if 'user' in parsed_data:
            return json.loads(parsed_data['user'])
        else:
            return {
                "id": 123456789,
                "first_name": "Telegram",
                "last_name": "User",
                "username": "tg_user"
            }
    except Exception as e:
        print(f"Error parsing user data: {e}")
        return {
            "id": 123456789,
            "first_name": "Fallback",
            "last_name": "User",
            "username": "fallback"
        }

# ========== МОДЕЛИ PYDANTIC ==========

class UserInfo(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None

class GroupResponse(BaseModel):
    id: int
    cipher: str
    department_id: int
    department_name: str

class ContingentResponse(BaseModel):
    date: str
    count: int

class AddDataRequest(BaseModel):
    group_id: int
    date: str  # YYYY-MM-DD
    count: int

# ========== API ЭНДПОИНТЫ ==========

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Главная страница Web App"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/me", response_model=UserInfo)
async def get_me(user: dict = Depends(get_current_user)):
    """Возвращает информацию о текущем пользователе"""
    return user

@app.get("/api/departments")
async def get_departments(user: dict = Depends(get_current_user)):
    """Получить список отделений"""
    session = Session()
    try:
        departments = session.query(models.Departments).all()
        return [{"id": d.id, "name": d.name} for d in departments]
    finally:
        session.close()

@app.get("/api/groups/{department_id}")
async def get_groups(department_id: int, user: dict = Depends(get_current_user)):
    """Получить группы отделения"""
    session = Session()
    try:
        groups = session.query(models.Group).filter(
            models.Group.id_departments == department_id
        ).all()
        
        result = []
        for g in groups:
            dept = session.query(models.Departments).filter(
                models.Departments.id == g.id_departments
            ).first()
            result.append({
                "id": g.id,
                "cipher": g.cipher,
                "department_id": g.id_departments,
                "department_name": dept.name if dept else "Неизвестно"
            })
        return result
    finally:
        session.close()

@app.get("/api/data/{group_id}")
async def get_group_data(group_id: int, user: dict = Depends(get_current_user)):
    """Получить данные контингента для группы"""
    session = Session()
    try:
        data = session.query(models.Contingent).filter(
            models.Contingent.id_groups == group_id
        ).order_by(models.Contingent.date.desc()).all()
        
        return [
            {
                "date": item.date.strftime("%d.%m.%Y"),
                "count": item.number_of_students
            }
            for item in data
        ]
    finally:
        session.close()

@app.post("/api/add")
async def add_data(
    request: AddDataRequest,
    user: dict = Depends(get_current_user)
):
    """Добавить запись контингента"""
    session = Session()
    try:
        # Проверяем, существует ли группа
        group = session.query(models.Group).filter(
            models.Group.id == request.group_id
        ).first()
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        
        # Парсим дату
        try:
            record_date = datetime.strptime(request.date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        
        # Создаем запись
        new_record = models.Contingent(
            id_groups=request.group_id,
            date=record_date,
            number_of_students=request.count
        )
        session.add(new_record)
        session.commit()
        
        return {"status": "success", "message": "Data added successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

@app.get("/api/health")
async def health():
    """Проверка статуса сервера"""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}