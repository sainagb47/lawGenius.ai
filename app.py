import os, logging, json
from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect, url_for, flash
from dotenv import load_dotenv
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from gtts import gTTS

# ---------------- Load Env ----------------
load_dotenv()

app = Flask(__name__, static_url_path="/static")
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "dev-secret-change-me")

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- Redis / Gemini ----------------
from upstash_redis import Redis
import google.generativeai as genai

redis_client = Redis(
    url=os.getenv("https://smashing-kodiak-12048.upstash.io"),
    token=os.getenv("AS8QAAIncDJhNmYxOGUxOGE3MjY0OWVjYjRjODkyMThkZTAzODU2OHAyMTIwNDg")
)

genai.configure(api_key=os.getenv("AIzaSyAmWacf2rtIGjuSp4ImDFHQcoDpwneLT1w"))
GEMINI_MODEL_NAME = "gemini-2.0-flash"

# ---------------- Imports ----------------
from views.chatbotLegalv2 import process_input, create_new_chat, get_chat_list, load_chat
from views.judgmentPred import extract_text_from_file, predict_verdict
from views.docGen import generate_legal_document   # ✅ ensure function name matches

# ---------------- User Store ----------------
USERS_FILE = os.path.join("data", "users.json")
os.makedirs("data", exist_ok=True)

def load_users():
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated

# ---------------- Auth Routes ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"].lower().strip()
        password = request.form["password"]
        users = load_users()
        if email in users:
            flash("Email already registered", "warning")
            return redirect(url_for("login"))
        users[email] = {"password": generate_password_hash(password)}
        save_users(users)
        session["user"] = email
        return redirect(url_for("index"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].lower().strip()
        password = request.form["password"]
        users = load_users()
        user = users.get(email)

        if not user or not check_password_hash(user["password"], password):
            flash("Invalid credentials", "danger")
            return redirect(url_for("login"))

        # ✅ Login success
        session["user"] = email

        # --- Generate welcome audio ---
        audio_dir = os.path.join("static", "audio")
        os.makedirs(audio_dir, exist_ok=True)
        tts_file = os.path.join(audio_dir, "welcome.mp3")

        if not os.path.exists(tts_file):
            tts = gTTS("Welcome to AskLegal.ai")
            tts.save(tts_file)

        # Flag to play audio once after login
        session["play_audio"] = True
        return redirect(url_for("index"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

# ---------------- Main Pages ----------------
@app.route("/")
@login_required
def index():
    raw_chat_names = get_chat_list()
    chat_list = []
    for name in raw_chat_names:
        chat_data = load_chat(name)
        chat_list.append({
            "name": name,
            "title": (chat_data["past"][0] if chat_data["past"] else "New chat")
        })

    # check if audio should be played
    play_audio = session.pop("play_audio", False)

    return render_template("index.html", chat_list=chat_list, play_audio=play_audio)

@app.route("/predict_page")
@login_required
def predict_page():
    return render_template("predict.html")

@app.route("/generate_page")
@login_required
def generate_page():
    return render_template("generate.html")

# ---------------- API Routes ----------------
@app.route("/chat", methods=["POST"])
@login_required
def chat():
    data = request.json
    response, source = process_input(data["chat_name"], data["user_input"], return_source=True)
    return jsonify({"response": response, "source": source})

@app.route("/predict", methods=["POST"])
@login_required
def predict():
    file = request.files.get("file")
    file_type = request.form.get("file_type")
    text = extract_text_from_file(file, file_type)
    result = predict_verdict(text)
    return jsonify({"text": text, "result": result})

@app.route("/generate_document", methods=["POST"])
@login_required
def generate_document():
    data = request.json
    file_path, file_name = generate_legal_document(data["doc_prompt"])
    return jsonify({"download_url": f"/download/{file_name}"})

@app.route("/download/<filename>")
def download_file(filename):
    return send_from_directory("static/generated_docs", filename, as_attachment=True)

# ---------------- Run ----------------
if __name__ == "__main__":
    app.run(debug=True)
