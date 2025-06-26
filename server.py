from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import date
from datetime import datetime
from zoneinfo import ZoneInfo
import uvicorn #server to run this web
import sqlite3 #database
import json #json database
app = FastAPI()

#CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SignUpRequest(BaseModel):
    username: str
    email: str
    password: str

class FriendRequest(BaseModel):
    friend: str
# Serve static files (like index.html)
app.mount("/zyro", StaticFiles(directory=".", html=True), name="zyro")

conn = sqlite3.connect('users.db', check_same_thread=False)
db = conn.cursor()

db.execute("CREATE TABLE IF NOT EXISTS users (username TEXT, password TEXT, email TEXT)")
db.execute("CREATE TABLE IF NOT EXISTS relations (user1 TEXT, user2 TEXT, status TEXT, date TEXT)")
db.execute("CREATE TABLE IF NOT EXISTS recent_chats (user1 TEXT, user2 TEXT, last_opened TEXT)")
db.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT, receiver TEXT, type TEXT DEFAULT 'text', message TEXT, time TEXT)")

conn.commit()
#with open("messages.json", "w") as f:
    
    
active_connections = {}

@app.get("/")
async def read_root(request: Request):
    username = request.cookies.get("username")
    return RedirectResponse(url=f"/{username}")

@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    await websocket.accept()
    active_connections[username] = websocket
    try:
      while True:
        data = await websocket.receive_text()
        msg = json.loads(data)
        msg_type = msg["type"]
        sender = msg["sender"]
        receiver = msg["receiver"]
        message = msg["message"]
        time_now = datetime.now(ZoneInfo("Asia/Kolkata"))
        #time_iso = datetime.now().replace(microsecond=0).isoformat()
        time_iso = time_now.strftime("%d/%m/%Y %I:%M/%p")
        
        if msg_type in ["text", "media"]:
            db.execute("INSERT INTO messages (sender, receiver, message, type, time) VALUES (?, ?, ?, ?, ?)", (sender, receiver, message, msg_type, time_iso))
            conn.commit()
          
        await websocket.send_text(json.dumps({"sender": sender, "receiver": receiver, "message": message, "type": msg_type}))
        if receiver in active_connections:
          await active_connections[receiver].send_text(json.dumps({"sender": sender, "receiver": receiver, "message": message, "timestamp": time_iso, "type": msg_type}))
    except Exception as e:
        print("Error: ", e)
    finally:
        if username in active_connections:
          active_connections.pop(username, None)
            
@app.get("/get-messages")
def get_messages(request: Request, friend: str, offset: int = 0):
    username = request.cookies.get("username")
    messages = db.execute("SELECT * FROM messages WHERE (sender = ? AND receiver = ?) OR (sender = ? AND receiver = ?) ORDER BY id DESC LIMIT 30 OFFSET ?", (username, friend, friend, username, offset)).fetchall()
    messages = messages[::-1]
    if messages:
      return JSONResponse(status_code=200, content={"success": True, "messages": [{"sender": message[1], "receiver": message[2], "type": message[3], "message": message[4], "timestamp": message[5]} for message in messages]})
    else:
      return JSONResponse(status_code=200, content={"success": False, "message": "No messages found"})


#signup page
@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    with open("signup.html", "r") as f:
        return HTMLResponse(content=f.read())

#signin page
@app.get("/signin", response_class=HTMLResponse)
def signin_page(request: Request):
    with open("signin.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/signout")
def signout(request: Request):
    response = RedirectResponse(url="/signin", status_code=302)
    response.delete_cookie(key="username", path="/")
    response.delete_cookie(key="email", path="/")
    return response
    
@app.get("/cookies")
def get_cookies(request: Request):
    username = request.cookies.get("username")
    email = request.cookies.get("email")
    if (username and email):
        return {"success": True, "username": username, "email": email}
    return {"success": False}

@app.post("/signup")
async def signup(data: SignUpRequest):
    username = data.username
    password = data.password 
    email = data.email

    username_exists = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    email_exists = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    if (username_exists and email_exists):
        return {"message": "Name and Email already exists"}
    if username_exists:
        return {"message": "Name already exists"}
    if email_exists:
        return {"message": "Email already exists"}

    db.execute("INSERT INTO users (username, password, email) VALUES (?, ?, ?)", (username, password, email))
    conn.commit()
    all_users = db.execute("SELECT * FROM users").fetchall()
    with open("users.json", "w") as f:
        json.dump([{"username": u[0], "password": u[1], "email": u[2]} for u in all_users], f, indent=4)

    response = RedirectResponse(url=f"/{username}", status_code=302)
    response.set_cookie(key="username", value=username, httponly=False)
    response.set_cookie(key="email", value=email, httponly=False) #http only True when we dont want to access it from js
    return response

@app.post("/signin")
def signin(data: SignUpRequest):
    username = data.username
    email = data.email
    password = data.password

    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    email_db = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.commit()

    try:
        username_db = user[0]
        username_valid = True
    except:
        username_valid = False
    try:
        email_db = email_db[2]
        email_valid = True
    except:
        email_valid = False
    try:
        stored_password = user[1]
    except:
        stored_password = None

    if (not username_valid and not email_valid):
        return {"success": False, "message": "User and Email Not found"}

    elif username_valid and not email_valid:
        return {"success": False, "message": "Email is invalid"}
    elif not username_valid and email_valid:
        return {"success": False, "message": "Username is invalid"}
    elif stored_password != password:
        return {"success": False, "message": "Password is incorrect"}

    response = RedirectResponse(url=f"/{username}", status_code=302)
    response.set_cookie(key="username", value=username, httponly=False)
    response.set_cookie(key="email", value=email, httponly=False) 
    return response

@app.get("/search")
def search_users(request: Request, query: str):
    #current user
    username = request.cookies.get("username")
    user_friends = []

    #if current user not logged in
    if (not username):
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})

    #get all users by query
    users = db.execute("SELECT username FROM users WHERE username LIKE ? AND username != ?", (f"%{query}%", username)).fetchall()
    #if not users
    if (not users):
        return JSONResponse(status_code=200, content={"success": False, "message": "No users found"})

    for (other_user,) in users:
        relation_pending = db.execute("SELECT * FROM relations WHERE user1 = ? AND user2 = ?", (username, other_user)).fetchone()
        relation_accept = db.execute("SELECT * FROM relations WHERE user1 = ? AND user2 = ?", (other_user, username)).fetchone()

        status = "none"
        if (relation_accept and relation_accept[2] == "pending"):
            status = "can_accept"
        elif (relation_pending and relation_pending[2]) == "pending":
            status = "pending"
        elif (relation_pending and relation_pending[2] == "friend") or (relation_accept and relation_accept[2] == "friend"):
            status = "friend"
        user_friends.append({"friend": other_user, "status": status})

    
    return JSONResponse(status_code=200, content={"success": True, "friends": user_friends})

#send friend reuqest
@app.post("/send-friend-req")
def send_friend_req(request: Request, data: FriendRequest):
    friend = data.friend
    username = request.cookies.get("username")
    today = date.today().strftime("%d/%m/%Y")
    db.execute("INSERT INTO relations (user1, user2, status, date) VALUES (?, ?, ?, ?)", (username, friend, "pending", today))
    conn.commit()
    data = db.execute("SELECT * FROM relations").fetchall()
    with open("relations.json", "w") as f:
        json.dump([{"user1": u[0], "user2": u[1], "status": u[2], "date": u[3]} for u in data], f, indent=4)
    return JSONResponse(status_code=200, content={"success": True, "message": "Friend request sent"})

#accept friend request
@app.post("/accept-friend-req")
def accept_friend_req(request: Request, data: FriendRequest):
    username = request.cookies.get("username")
    friend = data.friend
    today = date.today().strftime("%d/%m/%Y")
    db.execute("UPDATE relations SET status = ?, date = ? WHERE user1 = ? AND user2 = ?", ("friend", today, friend, username))
    conn.commit()
    data = db.execute("SELECT * FROM relations").fetchall()
    with open("relations.json", "w") as f:
        json.dump([{"user1": u[0], "user2": u[1], "status": u[2], "date": u[3]} for u in data], f, indent=4)
    return JSONResponse(status_code=200, content={"success": True, "message": f"{username} and {friend} are now friends"})

@app.post("/unfriend")
def remove_friend(request: Request, data: FriendRequest):
    username = request.cookies.get("username")
    friend = data.friend
    db.execute("DELETE FROM relations WHERE (user1 = ? AND user2 = ?) OR (user1 = ? AND user2 = ?)", (username, friend, friend, username))
    conn.commit()
    data = db.execute("SELECT * FROM relations").fetchall()
    with open("relations.json", "w") as f:
        json.dump([{"user1": u[0], "user2": u[1], "status": u[2], "date": u[3]} for u in data], f, indent=4)
    return JSONResponse(status_code=200, content={"success": True, "message": f"{username} and {friend} are no longer friends"})

@app.get("/friends")
def get_friends(request: Request):
    username = request.cookies.get("username")
    friends_db = db.execute("SELECT * FROM relations WHERE (user1 = ? AND status = ?) OR (user2 = ? AND status = ?)", (username, "friend", username, "friend")).fetchall()
    friends = [{"friend": u[0] if u[0] != username else u[1]} for u in friends_db]
    
    return JSONResponse(status_code=200, content={"success": True, "friends": friends})

@app.post("/update-recent-chats")
def recent_chats(request: Request, friend: str):
    username = request.cookies.get("username")
   # friend = data.friend
    today = date.today().strftime("%d/%m/%Y")
    recent_chats_exists = db.execute("SELECT * FROM recent_chats WHERE user1 = ? AND user2 = ?", (username, friend)).fetchone()
    if (recent_chats_exists):
        return JSONResponse(status_code=200, content={"success": False, "message": "Recent chat already exists"})
    db.execute("INSERT INTO recent_chats (user1, user2, last_opened) VALUES (?, ?, ?)", (username, friend, today))
    return JSONResponse(status_code=200, content={"success": True, "message": f"{friend} added to recent chats"})

@app.get("/get-recent-chats")
def get_recent_chats(request: Request):
    username = request.cookies.get("username")
    recent_chats = db.execute("SELECT * FROM recent_chats WHERE user1 = ?", (username,)).fetchall()
    if (not recent_chats):
        return JSONResponse(status_code=200, content={"success": False, "message": "No recent chats found"})
    return JSONResponse(status_code=200, content={"success": True, "recent_chats": recent_chats})
    
@app.post("/remove-recent-chats")
def delete_recent_chats(request: Request, data: FriendRequest):
    username = request.cookies.get("username")
    friend = data.friend
    db.execute("DELETE FROM recent_chats WHERE user1 = ? AND user2 = ?", (username, friend))
    return JSONResponse(status_code=200, content={"success": True, "message": f"{friend} removed from recent chats"})
    
    
#notificaitons
@app.get("/notifications")
def notifications(request: Request):
    username = request.cookies.get("username")
    notifications = db.execute("SELECT * FROM relations WHERE (user1 = ? AND status = ?) OR (user2 = ? AND status = ?)", (username, "pending", username, "pending")).fetchall()
    return JSONResponse(status_code=200, content={"success": True, "notification": notifications})

#chat page
@app.get("/{full_path:path}", response_class = HTMLResponse)
def spa_router(full_path: str, request: Request):
    username = request.cookies.get("username")
    if (not username):
        return RedirectResponse(url="/signin", status_code=302)
    with open("main.html", "r") as f:
        return HTMLResponse(content=f.read().replace("{{username}}", username))
    
#user home page
@app.get("/{username}")
def user_home(username: str):
    with open("main.html", "r") as f:
        content = f.read().replace("{{username}}", username)
        return HTMLResponse(content=content)
        
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)