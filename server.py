from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import date, datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import os, json, base64, uuid, asyncpg

load_dotenv()
app = FastAPI()

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)

# Static
app.mount("/zyro", StaticFiles(directory=".", html=True), name="zyro")
app.mount("/media", StaticFiles(directory="media"), name="media")
os.makedirs("media", exist_ok=True)

# DB
DATABASE_URL = os.getenv("SUPABASE_DB_URL")
pool = None

async def get_db():
    global pool
    if not pool:
        pool = await asyncpg.create_pool(DATABASE_URL)
    return pool

@app.on_event("startup")
async def startup():
    db = await get_db()
    async with db.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY, password TEXT, email TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS relations (
            user1 TEXT, user2 TEXT, status TEXT, date TEXT
        );
        CREATE TABLE IF NOT EXISTS recent_chats (
            user1 TEXT, user2 TEXT, last_opened TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY, sender TEXT, receiver TEXT,
            type TEXT, message TEXT, time TEXT
        );
        """)

# Models
class SignUpRequest(BaseModel):
    username: str
    email: str
    password: str

class FriendRequest(BaseModel):
    friend: str

# WebSocket
active_connections = {}

@app.websocket("/ws/{username}")
async def ws(ws: WebSocket, username: str):
    await ws.accept()
    active_connections[username] = ws
    try:
        while True:
            data = json.loads(await ws.receive_text())
            sender, receiver = data["sender"], data["receiver"]
            msg_type, message = data["type"], data["message"]
            time_now = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d/%m/%Y %I:%M/%p")

            db = await get_db()
            async with db.acquire() as conn:
                if msg_type == "media":
                    header, encoded = message.split(",", 1)
                    ext = {
                        "image/jpeg": ".jpg", "image/png": ".png",
                        "video/mp4": ".mp4", "video/webm": ".webm"
                    }.get(header.split(":")[1].split(";")[0], ".bin")
                    filename = f"{uuid.uuid4()}{ext}"
                    with open(f"media/{filename}", "wb") as f:
                        f.write(base64.b64decode(encoded))
                    message = filename

                await conn.execute("""
                    INSERT INTO messages (sender, receiver, message, type, time)
                    VALUES ($1, $2, $3, $4, $5)
                """, sender, receiver, message, msg_type, time_now)

            await ws.send_text(json.dumps({
                "sender": sender, "receiver": receiver, "message": message, "type": msg_type
            }))
            if receiver in active_connections:
                await active_connections[receiver].send_text(json.dumps({
                    "sender": sender, "receiver": receiver, "message": message,
                    "type": msg_type, "timestamp": time_now
                }))
    except Exception as e:
        print("WebSocket Error:", e)
    finally:
        active_connections.pop(username, None)

# Signup
@app.post("/signup")
async def signup(data: SignUpRequest):
    db = await get_db()
    async with db.acquire() as conn:
        exists = await conn.fetchrow("SELECT * FROM users WHERE username=$1 OR email=$2", data.username, data.email)
        if exists:
            return {"message": "Username or Email already exists"}
        await conn.execute("INSERT INTO users (username, password, email) VALUES ($1, $2, $3)",
                           data.username, data.password, data.email)

    resp = RedirectResponse(f"/{data.username}", status_code=302)
    resp.set_cookie("username", data.username)
    resp.set_cookie("email", data.email)
    return resp

@app.post("/signin")
async def signin(data: SignUpRequest):
    db = await get_db()
    async with db.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE username=$1", data.username)
        if not user:
            return {"success": False, "message": "User not found"}
        if user["email"] != data.email:
            return {"success": False, "message": "Invalid email"}
        if user["password"] != data.password:
            return {"success": False, "message": "Incorrect password"}

    resp = RedirectResponse(f"/{data.username}", status_code=302)
    resp.set_cookie("username", data.username)
    resp.set_cookie("email", data.email)
    return resp

@app.get("/get-messages")
async def get_messages(request: Request, friend: str, offset: int = 0):
    username = request.cookies.get("username")
    db = await get_db()
    async with db.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM messages
            WHERE (sender=$1 AND receiver=$2) OR (sender=$2 AND receiver=$1)
            ORDER BY id DESC LIMIT 30 OFFSET $3
        """, username, friend, offset)
    messages = list(reversed([dict(r) for r in rows]))
    return {"success": True, "messages": messages}

@app.post("/send-friend-req")
async def send_friend_req(request: Request, data: FriendRequest):
    username = request.cookies.get("username")
    today = date.today().strftime("%d/%m/%Y")
    db = await get_db()
    async with db.acquire() as conn:
        await conn.execute(
            "INSERT INTO relations (user1, user2, status, date) VALUES ($1, $2, 'pending', $3)",
            username, data.friend, today
        )
    return {"success": True, "message": "Friend request sent"}

@app.post("/accept-friend-req")
async def accept_friend_req(request: Request, data: FriendRequest):
    username = request.cookies.get("username")
    today = date.today().strftime("%d/%m/%Y")
    db = await get_db()
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE relations SET status='friend', date=$1 WHERE user1=$2 AND user2=$3",
            today, data.friend, username
        )
    return {"success": True, "message": f"{username} and {data.friend} are now friends"}

@app.post("/unfriend")
async def unfriend(request: Request, data: FriendRequest):
    username = request.cookies.get("username")
    db = await get_db()
    async with db.acquire() as conn:
        await conn.execute(
            "DELETE FROM relations WHERE (user1=$1 AND user2=$2) OR (user1=$2 AND user2=$1)",
            username, data.friend
        )
    return {"success": True, "message": f"Unfriended {data.friend}"}

@app.get("/friends")
async def friends(request: Request):
    username = request.cookies.get("username")
    db = await get_db()
    async with db.acquire() as conn:
        friends = await conn.fetch("""
            SELECT * FROM relations WHERE (user1=$1 OR user2=$1) AND status='friend'
        """, username)
    return {
        "success": True,
        "friends": [{"friend": f["user2"] if f["user1"] == username else f["user1"]} for f in friends]
    }

@app.get("/notifications")
async def notifications(request: Request):
    username = request.cookies.get("username")
    db = await get_db()
    async with db.acquire() as conn:
        notifs = await conn.fetch("""
            SELECT * FROM relations WHERE (user1=$1 OR user2=$1) AND status='pending'
        """, username)
    return {"success": True, "notification": [dict(n) for n in notifs]}

@app.get("/search")
async def search(request: Request, query: str):
    username = request.cookies.get("username")
    db = await get_db()
    async with db.acquire() as conn:
        users = await conn.fetch(
            "SELECT username FROM users WHERE username ILIKE $1 AND username != $2",
            f"%{query}%", username
        )

        result = []
        for u in users:
            friend = u["username"]
            rel1 = await conn.fetchrow("SELECT status FROM relations WHERE user1=$1 AND user2=$2", username, friend)
            rel2 = await conn.fetchrow("SELECT status FROM relations WHERE user1=$1 AND user2=$2", friend, username)
            status = "none"
            if rel2 and rel2["status"] == "pending":
                status = "can_accept"
            elif rel1 and rel1["status"] == "pending":
                status = "pending"
            elif (rel1 and rel1["status"] == "friend") or (rel2 and rel2["status"] == "friend"):
                status = "friend"
            result.append({"friend": friend, "status": status})
    return {"success": True, "friends": result}

@app.post("/update-recent-chats")
async def update_recent(request: Request, friend: str):
    username = request.cookies.get("username")
    today = date.today().strftime("%d/%m/%Y")
    db = await get_db()
    async with db.acquire() as conn:
        check = await conn.fetchrow("SELECT * FROM recent_chats WHERE user1=$1 AND user2=$2", username, friend)
        if not check:
            await conn.execute("INSERT INTO recent_chats (user1, user2, last_opened) VALUES ($1, $2, $3)",
                               username, friend, today)
            return {"success": True, "message": "Chat added"}
        return {"success": False, "message": "Already exists"}

@app.get("/get-recent-chats")
async def get_recent(request: Request):
    username = request.cookies.get("username")
    db = await get_db()
    async with db.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM recent_chats WHERE user1=$1", username)
    return {"success": True, "recent_chats": [dict(r) for r in rows]}

@app.post("/remove-recent-chats")
async def remove_recent(request: Request, data: FriendRequest):
    username = request.cookies.get("username")
    db = await get_db()
    async with db.acquire() as conn:
        await conn.execute("DELETE FROM recent_chats WHERE user1=$1 AND user2=$2", username, data.friend)
    return {"success": True, "message": "Chat removed"}

# SPA routes
@app.get("/{full_path:path}", response_class=HTMLResponse)
async def fallback(full_path: str, request: Request):
    username = request.cookies.get("username")
    if not username:
        return RedirectResponse("/signin")
    with open("main.html") as f:
        return HTMLResponse(f.read().replace("{{username}}", username))

@app.get("/{username}")
async def user_home(username: str):
    with open("main.html") as f:
        return HTMLResponse(f.read().replace("{{username}}", username))

# Run
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=5000, reload=True)