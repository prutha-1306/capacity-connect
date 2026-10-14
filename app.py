"""Capacity Connect - SIH26075. Flask + SQLite learning platform."""
import os, re, sqlite3, uuid
from datetime import datetime, timedelta
from functools import wraps
from flask import (Flask, g, render_template, request, redirect, url_for,
                   session, flash, abort, send_from_directory)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from seed_data import COURSES

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "capacity_connect.db")
UPLOADS = os.path.join(BASE, "uploads")
os.makedirs(UPLOADS, exist_ok=True)
PASS_MARK = 60
ALLOWED = {"pdf": {"pdf"}, "ppt": {"ppt", "pptx"}}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, password TEXT, role TEXT, created_at TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS courses(id INTEGER PRIMARY KEY, title TEXT, description TEXT, category TEXT, trainer_id INTEGER);
CREATE TABLE IF NOT EXISTS materials(id INTEGER PRIMARY KEY, course_id INTEGER, kind TEXT, title TEXT, content TEXT);
CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY, course_id INTEGER, text TEXT, a TEXT, b TEXT, c TEXT, d TEXT, answer TEXT);
CREATE TABLE IF NOT EXISTS enrollments(user_id INTEGER, course_id INTEGER, enrolled_at TEXT, PRIMARY KEY(user_id, course_id));
CREATE TABLE IF NOT EXISTS done(user_id INTEGER, material_id INTEGER, PRIMARY KEY(user_id, material_id));
CREATE TABLE IF NOT EXISTS doubts(id INTEGER PRIMARY KEY, course_id INTEGER, user_id INTEGER, question TEXT, answer TEXT, created_at TEXT, answered_at TEXT);
CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, user_id INTEGER, course_id INTEGER, score INTEGER, total INTEGER, taken_at TEXT);
"""

# ---------- db ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()

def q(sql, args=(), one=False):
    cur = db().execute(sql, args)
    rows = cur.fetchall()
    db().commit()
    if one:
        return rows[0] if rows else None
    return rows

def now():
    return datetime.now().isoformat(timespec="seconds")

def init_db():
    with app.app_context():
        db().executescript(SCHEMA)
        cols = {r["name"] for r in db().execute("PRAGMA table_info(users)")}
        if "created_at" not in cols:
            db().execute("ALTER TABLE users ADD COLUMN created_at TEXT")
        if "active" not in cols:
            db().execute("ALTER TABLE users ADD COLUMN active INTEGER DEFAULT 1")
        db().execute("UPDATE users SET created_at=? WHERE created_at IS NULL OR created_at=''", (now(),))
        db().execute("UPDATE users SET active=1 WHERE active IS NULL")
        db().commit()
        if q("SELECT 1 FROM users", one=True):
            return
        for n, e, p, r in [("Admin", "admin@demo.com", "admin123", "admin"),
                           ("Dr. Meera Rao", "trainer@demo.com", "trainer123", "trainer"),
                           ("Rahul Sharma", "trainee@demo.com", "trainee123", "trainee")]:
            q("INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,?,?)",
              (n, e, generate_password_hash(p), r, now()))
        tid = q("SELECT id FROM users WHERE role='trainer'", one=True)["id"]
        for title, desc, cat, mats, qs in COURSES:
            cid = db().execute("INSERT INTO courses(title,description,category,trainer_id) VALUES(?,?,?,?)",
                               (title, desc, cat, tid)).lastrowid
            for k, t, c in mats:
                db().execute("INSERT INTO materials(course_id,kind,title,content) VALUES(?,?,?,?)", (cid, k, t, c))
            for row in qs:
                db().execute("INSERT INTO questions(course_id,text,a,b,c,d,answer) VALUES(?,?,?,?,?,?,?)", (cid, *row))
        seed_demo()
        db().commit()

DEMO = [  # (name, email, [(course_id, fraction of lessons done, quiz score out of 3 or None)])
    ("Priya Nair", "priya@demo.com", [(1, 1.0, 3), (2, 1.0, 2), (4, 0.5, None)]),
    ("Amit Verma", "amit@demo.com", [(1, 1.0, 1), (3, 0.5, None)]),
    ("Sneha Iyer", "sneha@demo.com", [(5, 1.0, 3), (2, 1.0, 3), (1, 0.5, None)]),
    ("Karan Mehta", "karan@demo.com", [(3, 1.0, 2)]),
    ("Rahul Sharma", "trainee@demo.com", [(1, 1.0, 3), (2, 0.5, None), (3, 0.5, None), (5, 0.0, None)]),
]

def seed_demo():
    """Sample learners so dashboards and reports look realistic on a fresh database."""
    ago = lambda d: (datetime.now() - timedelta(days=d)).isoformat(timespec="seconds")
    for i, (name, email, plan) in enumerate(DEMO):
        u = q("SELECT id FROM users WHERE email=?", (email,), True)
        if u:
            uid = u["id"]
        else:
            uid = db().execute("INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,'trainee',?)",
                               (name, email, generate_password_hash("trainee123"), ago(60 - i * 9))).lastrowid
        for cid, frac, score in plan:
            db().execute("INSERT OR IGNORE INTO enrollments VALUES(?,?,?)", (uid, cid, ago(30 - i * 3)))
            mids = [r["id"] for r in db().execute("SELECT id FROM materials WHERE course_id=? ORDER BY id", (cid,))]
            for m in mids[:round(len(mids) * frac)]:
                db().execute("INSERT OR IGNORE INTO done VALUES(?,?)", (uid, m))
            if score is not None:
                db().execute("INSERT INTO attempts(user_id,course_id,score,total,taken_at) VALUES(?,?,?,3,?)",
                             (uid, cid, score, ago(12 - i * 2)))
    pri = q("SELECT id FROM users WHERE email='priya@demo.com'", one=True)["id"]
    ami = q("SELECT id FROM users WHERE email='amit@demo.com'", one=True)["id"]
    db().execute("INSERT INTO doubts(course_id,user_id,question,answer,created_at,answered_at) VALUES(1,?,?,?,?,?)",
                 (pri, "What is the difference between a list and a tuple?",
                  "Lists can be changed after creation (mutable); tuples cannot (immutable). Use tuples for fixed data.", ago(5), ago(4)))
    db().execute("INSERT INTO doubts(course_id,user_id,question,created_at) VALUES(3,?,?,?)",
                 (ami, "When should I use a LEFT JOIN instead of an INNER JOIN?", ago(1)))

# ---------- template helpers ----------
ICONS = {"programming": "bi-code-slash", "web": "bi-globe2", "data": "bi-bar-chart-line-fill",
         "design": "bi-palette-fill", "cloud": "bi-cloud-fill", "soft": "bi-chat-heart-fill"}
KINDS = {"note": "bi-journal-text", "video": "bi-play-circle-fill", "pdf": "bi-file-earmark-pdf-fill", "ppt": "bi-file-earmark-slides-fill"}

@app.template_filter("cat_icon")
def cat_icon(c):
    c = (c or "").lower()
    return next((v for k, v in ICONS.items() if k in c), "bi-journal-bookmark-fill")

@app.template_filter("kind_icon")
def kind_icon(k):
    return KINDS.get(k, "bi-file-earmark")

@app.template_filter("initials")
def initials(n):
    return "".join(w[0] for w in (n or "?").split()[:2]).upper()

@app.template_filter("fmt")
def fmt(s, with_time=False):
    try:
        return datetime.fromisoformat(s).strftime("%b %d, %Y" + (" \u2022 %I:%M %p" if with_time else ""))
    except Exception:
        return s or "-"

@app.template_filter("yt")
def yt_embed(url):
    m = re.search(r"(?:v=|youtu\.be/|embed/)([\w-]{11})", url or "")
    return f"https://www.youtube.com/embed/{m.group(1)}" if m else url

def login_required(role=None):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **kw):
            u = session.get("user")
            if not u:
                flash("Please log in to continue.", "warning")
                return redirect(url_for("login"))
            if role and u["role"] != role:
                abort(403)
            return f(*a, **kw)
        return wrapper
    return deco

# ---------- core queries ----------
def counts(uid, cid):
    t = q("SELECT COUNT(*) n FROM materials WHERE course_id=?", (cid,), True)["n"]
    d = q("SELECT COUNT(*) n FROM done d JOIN materials m ON m.id=d.material_id "
          "WHERE d.user_id=? AND m.course_id=?", (uid, cid), True)["n"]
    return d, t

def progress(uid, cid):
    d, t = counts(uid, cid)
    return int(d * 100 / t) if t else 0

def best(uid, cid):
    return q("SELECT MAX(score*100/total) p FROM attempts WHERE user_id=? AND course_id=? AND total>0",
             (uid, cid), True)["p"]

def enrolled(uid, cid):
    return q("SELECT 1 FROM enrollments WHERE user_id=? AND course_id=?", (uid, cid), True) is not None

def has_cert(uid, cid):
    b = best(uid, cid)
    return b is not None and b >= PASS_MARK and progress(uid, cid) == 100

def user_certs(uid):
    out = []
    for c in q("SELECT c.* FROM courses c JOIN enrollments e ON e.course_id=c.id WHERE e.user_id=?", (uid,)):
        if has_cert(uid, c["id"]):
            a = q("SELECT taken_at FROM attempts WHERE user_id=? AND course_id=? AND total>0 AND score*100/total>=? "
                  "ORDER BY id LIMIT 1", (uid, c["id"], PASS_MARK), True)
            out.append(dict(c, issued=a["taken_at"]))
    return out

def summary(uid):
    mine = []
    for c in q("SELECT c.*, u.name trainer FROM courses c JOIN enrollments e ON e.course_id=c.id "
               "LEFT JOIN users u ON u.id=c.trainer_id WHERE e.user_id=?", (uid,)):
        d, t = counts(uid, c["id"])
        mine.append(dict(c, done=d, total=t, progress=int(d * 100 / t) if t else 0, best=best(uid, c["id"])))
    sk = {}
    for c in mine:
        if c["best"] is not None:
            sk.setdefault(c["category"], []).append(c["best"])
    skills = {k: round(sum(v) / len(v)) for k, v in sk.items()}
    done, total = sum(c["done"] for c in mine), sum(c["total"] for c in mine)
    return dict(mine=mine, skills=skills, certs=user_certs(uid), done=done, total=total,
                overall=int(done * 100 / total) if total else 0,
                courses_done=sum(1 for c in mine if c["total"] and c["progress"] == 100))

def rank_course(c, skills):
    weak = {k for k, v in skills.items() if v < 70}
    if c["category"] in weak:
        return 0, f"Recommended: strengthens your weaker area, {c['category']}"
    if c["category"] in skills:
        return 1, f"Recommended: builds on your progress in {c['category']}"
    return 2, "A new skill area to explore"

def purge_course(cid):
    for t in ("materials", "questions", "enrollments", "attempts", "doubts"):
        q(f"DELETE FROM {t} WHERE course_id=?", (cid,))
    q("DELETE FROM courses WHERE id=?", (cid,))

# ---------- auth ----------
@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("dashboard"))
    feat = q("SELECT c.*, u.name trainer, (SELECT COUNT(*) FROM materials m WHERE m.course_id=c.id) lessons, "
             "(SELECT COUNT(*) FROM enrollments e WHERE e.course_id=c.id) learners "
             "FROM courses c LEFT JOIN users u ON u.id=c.trainer_id ORDER BY learners DESC, c.id LIMIT 6")
    stats = dict(courses=q("SELECT COUNT(*) n FROM courses", one=True)["n"],
                 learners=q("SELECT COUNT(*) n FROM users WHERE role='trainee'", one=True)["n"],
                 lessons=q("SELECT COUNT(*) n FROM materials", one=True)["n"])
    return render_template("home.html", courses=feat, stats=stats)

@app.route("/course/<int:cid>")
def course_detail(cid):
    c = q("SELECT c.*, u.name trainer FROM courses c LEFT JOIN users u ON u.id=c.trainer_id WHERE c.id=?", (cid,), True) or abort(404)
    mats = q("SELECT kind,title FROM materials WHERE course_id=?", (cid,))
    nq = q("SELECT COUNT(*) n FROM questions WHERE course_id=?", (cid,), True)["n"]
    learners = q("SELECT COUNT(*) n FROM enrollments WHERE course_id=?", (cid,), True)["n"]
    me = session.get("user")
    return render_template("course_detail.html", c=c, mats=mats, nq=nq, learners=learners, mark=PASS_MARK,
                           is_enrolled=bool(me and me["role"] == "trainee" and enrolled(me["id"], cid)),
                           is_owner=bool(me and me["role"] == "trainer" and me["id"] == c["trainer_id"]))

# ---------- doubts (ask the trainer) ----------
@app.context_processor
def nav_counts():
    u = session.get("user")
    if u and u["role"] == "trainer":
        n = q("SELECT COUNT(*) n FROM doubts d JOIN courses c ON c.id=d.course_id "
              "WHERE c.trainer_id=? AND d.answer IS NULL", (u["id"],), True)["n"]
        return {"open_doubts": n}
    return {}

@app.post("/doubt/<int:cid>")
@login_required("trainee")
def ask_doubt(cid):
    uid = session["user"]["id"]
    if not enrolled(uid, cid):
        abort(403)
    text = request.form.get("question", "").strip()
    if text:
        q("INSERT INTO doubts(course_id,user_id,question,created_at) VALUES(?,?,?,?)", (cid, uid, text, now()))
        flash("Your doubt was sent to the trainer.", "success")
    return redirect(url_for("learn", cid=cid) + "#doubts")

@app.route("/doubts")
@login_required("trainer")
def doubts():
    rows = q("SELECT d.*, c.title, u.name trainee FROM doubts d JOIN courses c ON c.id=d.course_id "
             "JOIN users u ON u.id=d.user_id WHERE c.trainer_id=? ORDER BY (d.answer IS NULL) DESC, d.id DESC",
             (session["user"]["id"],))
    return render_template("doubts.html", rows=rows, open_n=sum(1 for r in rows if r["answer"] is None))

@app.post("/doubts/<int:did>/reply")
@login_required("trainer")
def reply_doubt(did):
    q("SELECT d.id FROM doubts d JOIN courses c ON c.id=d.course_id WHERE d.id=? AND c.trainer_id=?",
      (did, session["user"]["id"]), True) or abort(404)
    text = request.form.get("answer", "").strip()
    if text:
        q("UPDATE doubts SET answer=?, answered_at=? WHERE id=?", (text, now(), did))
        flash("Reply sent to the trainee.", "success")
    return redirect(url_for("doubts"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = q("SELECT * FROM users WHERE email=?", (request.form["email"].strip().lower(),), True)
        if u and check_password_hash(u["password"], request.form["password"]):
            if not u["active"]:
                flash("This account has been deactivated. Contact your administrator.", "danger")
            else:
                session["user"] = {"id": u["id"], "name": u["name"], "role": u["role"]}
                return redirect(url_for("dashboard"))
        else:
            flash("Incorrect email or password.", "danger")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        role = f.get("role") if f.get("role") in ("trainer", "trainee") else "trainee"
        try:
            q("INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,?,?)",
              (f["name"].strip(), f["email"].strip().lower(), generate_password_hash(f["password"]), role, now()))
            flash("Account created. You can log in now.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("That email is already registered.", "danger")
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/profile")
@login_required()
def profile():
    u = q("SELECT * FROM users WHERE id=?", (session["user"]["id"],), True)
    s = None
    n = q("SELECT COUNT(*) n FROM courses WHERE trainer_id=?", (u["id"],), True)["n"] if u["role"] == "trainer" else None
    return render_template("profile.html", acct=u, s=s, n=n)

@app.route("/files/<name>")
@login_required()
def files(name):
    return send_from_directory(UPLOADS, name, as_attachment=bool(request.args.get("dl")))

# ---------- dashboards ----------
@app.route("/dashboard")
@login_required()
def dashboard():
    u = session["user"]
    if u["role"] == "admin":
        return redirect(url_for("admin"))
    if u["role"] == "trainer":
        courses = q("SELECT c.*, (SELECT COUNT(*) FROM enrollments e WHERE e.course_id=c.id) learners, "
                    "(SELECT COUNT(*) FROM materials m WHERE m.course_id=c.id) lessons, "
                    "(SELECT COUNT(*) FROM questions x WHERE x.course_id=c.id) qn FROM courses c WHERE trainer_id=?", (u["id"],))
        learners = q("SELECT COUNT(DISTINCT e.user_id) n FROM enrollments e JOIN courses c ON c.id=e.course_id WHERE c.trainer_id=?", (u["id"],), True)["n"]
        avg = q("SELECT AVG(a.score*100.0/a.total) v FROM attempts a JOIN courses c ON c.id=a.course_id WHERE c.trainer_id=? AND a.total>0", (u["id"],), True)["v"]
        recent = q("SELECT a.*, c.title, us.name trainee FROM attempts a JOIN courses c ON c.id=a.course_id "
                   "JOIN users us ON us.id=a.user_id WHERE c.trainer_id=? ORDER BY a.id DESC LIMIT 6", (u["id"],))
        return render_template("trainer_dashboard.html", courses=courses, learners=learners,
                               avg=round(avg) if avg is not None else None, recent=recent, mark=PASS_MARK)
    s = summary(u["id"])
    recent = q("SELECT a.*, c.title FROM attempts a JOIN courses c ON c.id=a.course_id WHERE a.user_id=? ORDER BY a.id DESC LIMIT 5", (u["id"],))
    return render_template("trainee_dashboard.html", s=s, recent=recent, mark=PASS_MARK)

# ---------- trainee ----------
@app.route("/courses")
@login_required("trainee")
def courses():
    uid = session["user"]["id"]
    s = summary(uid)
    mine = {c["id"] for c in s["mine"]}
    rows = []
    for c in q("SELECT c.*, u.name trainer, (SELECT COUNT(*) FROM materials m WHERE m.course_id=c.id) lessons "
               "FROM courses c LEFT JOIN users u ON u.id=c.trainer_id"):
        d = dict(c, enrolled=c["id"] in mine)
        d["rank"], d["reason"] = rank_course(c, s["skills"])
        rows.append(d)
    rows.sort(key=lambda d: (d["enrolled"], d["rank"]))
    return render_template("courses.html", rows=rows, cats=sorted({r["category"] for r in rows}))

@app.post("/enroll/<int:cid>")
@login_required("trainee")
def enroll(cid):
    # courses only exist if a trainer created them, so enrolment is limited to trainer-created courses
    c = q("SELECT c.id FROM courses c JOIN users u ON u.id=c.trainer_id WHERE c.id=? AND u.role='trainer'", (cid,), True)
    if not c:
        abort(404)
    q("INSERT OR IGNORE INTO enrollments VALUES(?,?,?)", (session["user"]["id"], cid, now()))
    flash("You are enrolled. Happy learning!", "success")
    return redirect(url_for("learn", cid=cid))

@app.route("/learn/<int:cid>")
@login_required("trainee")
def learn(cid):
    uid = session["user"]["id"]
    c = q("SELECT c.*, u.name trainer FROM courses c LEFT JOIN users u ON u.id=c.trainer_id WHERE c.id=?", (cid,), True) or abort(404)
    if not enrolled(uid, cid):
        flash("Enroll in this course first.", "warning")
        return redirect(url_for("courses"))
    mats = [dict(m, done=q("SELECT 1 FROM done WHERE user_id=? AND material_id=?", (uid, m["id"]), True) is not None)
            for m in q("SELECT * FROM materials WHERE course_id=?", (cid,))]
    d, t = counts(uid, cid)
    nq = q("SELECT COUNT(*) n FROM questions WHERE course_id=?", (cid,), True)["n"]
    my_doubts = q("SELECT * FROM doubts WHERE user_id=? AND course_id=? ORDER BY id DESC", (uid, cid))
    return render_template("learn.html", c=c, mats=mats, d=d, t=t, p=progress(uid, cid), b=best(uid, cid), nq=nq, mark=PASS_MARK, my_doubts=my_doubts)

@app.post("/complete/<int:mid>")
@login_required("trainee")
def complete(mid):
    m = q("SELECT * FROM materials WHERE id=?", (mid,), True) or abort(404)
    q("INSERT OR IGNORE INTO done VALUES(?,?)", (session["user"]["id"], mid))
    return redirect(url_for("learn", cid=m["course_id"]) + f"#m{mid}")

@app.route("/quiz/<int:cid>", methods=["GET", "POST"])
@login_required("trainee")
def quiz(cid):
    uid = session["user"]["id"]
    c = q("SELECT * FROM courses WHERE id=?", (cid,), True) or abort(404)
    if not enrolled(uid, cid):
        return redirect(url_for("courses"))
    if progress(uid, cid) < 100:
        flash("Complete all lessons before taking the quiz.", "warning")
        return redirect(url_for("learn", cid=cid))
    if q("SELECT 1 FROM attempts WHERE user_id=? AND course_id=?", (uid, cid), True):
        flash("You have already completed this quiz.", "info")
        return redirect(url_for("learn", cid=cid))
    qs = q("SELECT * FROM questions WHERE course_id=?", (cid,))
    if request.method == "POST" and qs:
        score = sum(1 for x in qs if request.form.get(f"q{x['id']}") == x["answer"])
        q("INSERT INTO attempts(user_id,course_id,score,total,taken_at) VALUES(?,?,?,?,?)", (uid, cid, score, len(qs), now()))
        pct = score * 100 // len(qs)
        if pct >= PASS_MARK:
            flash(f"You scored {score}/{len(qs)} ({pct}%). You passed. Your certificate is ready.", "success")
        else:
            flash(f"You scored {score}/{len(qs)} ({pct}%). You need {PASS_MARK}% to pass.", "warning")
        return redirect(url_for("learn", cid=cid))
    return render_template("quiz.html", c=c, qs=qs)

@app.route("/certificates")
@login_required("trainee")
def certificates():
    return render_template("certificates.html", certs=user_certs(session["user"]["id"]))

@app.route("/certificate/<int:cid>")
@login_required("trainee")
def certificate(cid):
    uid = session["user"]["id"]
    c = q("SELECT * FROM courses WHERE id=?", (cid,), True) or abort(404)
    if not has_cert(uid, cid):
        flash("Finish the course and pass the quiz to unlock your certificate.", "warning")
        return redirect(url_for("learn", cid=cid))
    t = q("SELECT name FROM users WHERE id=?", (c["trainer_id"],), True)
    return render_template("certificate.html", c=c, score=best(uid, cid), trainer=t["name"] if t else "",
                           date=datetime.now().strftime("%d %B %Y"), cert_id=f"CC-{cid:03d}-{uid:04d}")

# ---------- trainer ----------
def own_course(cid):
    c = q("SELECT * FROM courses WHERE id=?", (cid,), True)
    if not c or c["trainer_id"] != session["user"]["id"]:
        abort(404)
    return c

@app.route("/course/new", methods=["GET", "POST"])
@login_required("trainer")
def course_new():
    if request.method == "POST":
        f = request.form
        cid = db().execute("INSERT INTO courses(title,description,category,trainer_id) VALUES(?,?,?,?)",
                           (f["title"], f["description"], f["category"], session["user"]["id"])).lastrowid
        db().commit()
        flash("Course created. Now add lessons and quiz questions.", "success")
        return redirect(url_for("manage", cid=cid))
    return render_template("course_new.html")

@app.route("/manage/<int:cid>")
@login_required("trainer")
def manage(cid):
    c = own_course(cid)
    mats = q("SELECT * FROM materials WHERE course_id=?", (cid,))
    qs = q("SELECT * FROM questions WHERE course_id=?", (cid,))
    perf = []
    for s in q("SELECT u.id,u.name,u.email FROM users u JOIN enrollments e ON e.user_id=u.id WHERE e.course_id=?", (cid,)):
        n = q("SELECT COUNT(*) n FROM attempts WHERE user_id=? AND course_id=?", (s["id"], cid), True)["n"]
        perf.append(dict(s, progress=progress(s["id"], cid), best=best(s["id"], cid), attempts=n, cert=has_cert(s["id"], cid)))
    return render_template("manage.html", c=c, mats=mats, qs=qs, perf=perf, mark=PASS_MARK)

@app.post("/manage/<int:cid>/edit")
@login_required("trainer")
def edit_course(cid):
    own_course(cid)
    f = request.form
    q("UPDATE courses SET title=?, description=?, category=? WHERE id=?", (f["title"], f["description"], f["category"], cid))
    flash("Course details updated.", "success")
    return redirect(url_for("manage", cid=cid))

@app.post("/manage/<int:cid>/remove")
@login_required("trainer")
def remove_course(cid):
    own_course(cid)
    purge_course(cid)
    flash("Course deleted.", "success")
    return redirect(url_for("dashboard"))

@app.post("/manage/<int:cid>/material")
@login_required("trainer")
def add_material(cid):
    own_course(cid)
    f, kind = request.form, request.form["kind"]
    content = f.get("content", "").strip()
    if kind in ALLOWED:
        file = request.files.get("file")
        ext = file.filename.rsplit(".", 1)[-1].lower() if file and "." in file.filename else ""
        if ext not in ALLOWED[kind]:
            flash("Please choose a valid " + "/".join(sorted(ALLOWED[kind])).upper() + " file.", "danger")
            return redirect(url_for("manage", cid=cid))
        content = f"{uuid.uuid4().hex[:10]}_{secure_filename(file.filename)}"
        file.save(os.path.join(UPLOADS, content))
    elif kind not in ("note", "video") or not content:
        flash("Please fill in the lesson content.", "danger")
        return redirect(url_for("manage", cid=cid))
    q("INSERT INTO materials(course_id,kind,title,content) VALUES(?,?,?,?)", (cid, kind, f["title"], content))
    flash("Lesson added.", "success")
    return redirect(url_for("manage", cid=cid))

@app.post("/manage/<int:cid>/question")
@login_required("trainer")
def add_question(cid):
    own_course(cid)
    f = request.form
    q("INSERT INTO questions(course_id,text,a,b,c,d,answer) VALUES(?,?,?,?,?,?,?)",
      (cid, f["text"], f["a"], f["b"], f["c"], f["d"], f["answer"]))
    flash("Quiz question added.", "success")
    return redirect(url_for("manage", cid=cid))

@app.post("/manage/<int:cid>/delete/<kind>/<int:item>")
@login_required("trainer")
def delete_item(cid, kind, item):
    own_course(cid)
    if kind in ("materials", "questions"):
        q(f"DELETE FROM {kind} WHERE id=? AND course_id=?", (item, cid))
    return redirect(url_for("manage", cid=cid))

# ---------- admin ----------
@app.route("/admin")
@login_required("admin")
def admin():
    users = q("SELECT * FROM users ORDER BY role, name")
    courses = []
    for c in q("SELECT c.*, u.name trainer, (SELECT COUNT(*) FROM enrollments e WHERE e.course_id=c.id) learners, "
               "(SELECT COUNT(*) FROM materials m WHERE m.course_id=c.id) lessons FROM courses c LEFT JOIN users u ON u.id=c.trainer_id"):
        enr = [r["user_id"] for r in q("SELECT user_id FROM enrollments WHERE course_id=?", (c["id"],))]
        certs = sum(1 for uid in enr if has_cert(uid, c["id"]))
        avg = q("SELECT AVG(score*100.0/total) v FROM attempts WHERE course_id=? AND total>0", (c["id"],), True)["v"]
        courses.append(dict(c, certs=certs, avg=round(avg) if avg is not None else None))
    roles = {r: sum(1 for u in users if u["role"] == r) for r in ("admin", "trainer", "trainee")}
    stats = dict(users=len(users), courses=len(courses), enrollments=sum(c["learners"] for c in courses),
                 certs=sum(c["certs"] for c in courses))
    return render_template("admin.html", users=users, courses=courses, roles=roles, stats=stats)

def _not_self(uid):
    if uid == session["user"]["id"]:
        flash("You can't change your own account here.", "warning")
        return False
    return True

@app.post("/admin/user/add")
@login_required("admin")
def admin_user_add():
    f = request.form
    role = f.get("role") if f.get("role") in ("admin", "trainer", "trainee") else "trainee"
    try:
        q("INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,?,?)",
          (f["name"].strip(), f["email"].strip().lower(), generate_password_hash(f["password"]), role, now()))
        flash("Account created.", "success")
    except sqlite3.IntegrityError:
        flash("That email is already registered.", "danger")
    return redirect(url_for("admin") + "#users")

@app.post("/admin/user/<int:uid>/role")
@login_required("admin")
def admin_role(uid):
    # Roles are fixed at account creation. Endpoint kept only so older templates never crash.
    flash("Roles can't be changed after an account is created.", "warning")
    return redirect(url_for("admin") + "#users")

@app.post("/admin/user/<int:uid>/toggle")
@login_required("admin")
def admin_toggle(uid):
    if _not_self(uid):
        q("UPDATE users SET active = 1 - COALESCE(active,1) WHERE id=?", (uid,))
    return redirect(url_for("admin") + "#users")

@app.post("/admin/delete/<kind>/<int:item>")
@login_required("admin")
def admin_delete(kind, item):
    if kind == "user" and _not_self(item):
        for t in ("enrollments", "done", "attempts", "doubts"):
            q(f"DELETE FROM {t} WHERE user_id=?", (item,))
        q("DELETE FROM users WHERE id=?", (item,))
    elif kind == "course":
        purge_course(item)
    return redirect(url_for("admin") + ("#courses" if kind == "course" else "#users"))

@app.post("/admin/course/<int:cid>/trainer")
@login_required("admin")
def admin_course_trainer(cid):
    # Trainer assignment is fixed when the course is created. Endpoint kept only so older templates never crash.
    flash("The trainer of a course can't be changed.", "warning")
    return redirect(url_for("admin") + "#courses")

@app.errorhandler(403)
def forbidden(_):
    return render_template("base.html", content="You don't have access to this page."), 403

init_db()

if __name__ == "__main__":
    app.run(debug=True)
