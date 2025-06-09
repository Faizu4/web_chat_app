
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

app = FastAPI()

# Serve static files (like index.html)
app.mount("/static", StaticFiles(directory="."), name="static")

# Data model for signup
class SignupData(BaseModel):
    name: str
    email: str
    password: str
    confirm_password: str

# In-memory storage (replace with database in production)
users = []

@app.get("/", response_class=HTMLResponse)
async def get_signup_page():
    with open("index.html", "r") as file:
        return HTMLResponse(content=file.read())

@app.post("/signup")
async def signup(data: SignupData):
    # Basic validation
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    
    if not data.email.strip():
        raise HTTPException(status_code=400, detail="Email is required")
    
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="Password must have 8 characters")
    
    if data.password != data.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords don't match")
    
    # Check if email already exists
    for user in users:
        if user["email"] == data.email:
            raise HTTPException(status_code=400, detail="Email already exists")
    
    # Store user (in production, hash the password)
    users.append({
        "name": data.name,
        "email": data.email,
        "password": data.password  # In production, hash this!
    })
    
    return {"message": "User created successfully", "user_id": len(users)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)
