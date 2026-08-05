"""
Day 1 Homework: Lakebase-Powered AI Support App by Nana Adwoa Aforo Osei

Fetches LAKEBASE_URL from the Databricks secret scope/key named in
LAKEBASE_SECRET_SCOPE / LAKEBASE_SECRET_KEY (set via app.yaml), matching
the same pattern lakebase.py uses for the Massive app. Uses psycopg (v3)
instead of psycopg2 to avoid the OpenSSL FIPS self-test crash some
environments hit with psycopg2-binary. Secret values are base64-encoded
by the Databricks secrets API on read, so they're decoded here.
"""
import os
import base64
from flask import Flask, render_template, request, redirect, url_for, flash
from sqlalchemy import create_engine, text
from databricks.sdk import WorkspaceClient

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me")


def get_engine():
    scope = os.environ["LAKEBASE_SECRET_SCOPE"]
    key = os.environ["LAKEBASE_SECRET_KEY"]
    w = WorkspaceClient()
    raw = w.secrets.get_secret(scope=scope, key=key).value
    lakebase_url = base64.b64decode(raw).decode()
    sa_url = lakebase_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(sa_url, pool_pre_ping=True)


engine = get_engine()


@app.route("/")
def index():
    status_filter = request.args.get("status")
    query = "SELECT ticket_id, title, status, created_by, created_at FROM tickets"
    params = {}
    if status_filter:
        query += " WHERE status = :status"
        params["status"] = status_filter
    query += " ORDER BY created_at DESC"

    with engine.connect() as conn:
        tickets = conn.execute(text(query), params).mappings().all()
        stats = conn.execute(text(
            "SELECT status, COUNT(*) AS n FROM tickets GROUP BY status"
        )).mappings().all()

    return render_template("support_index.html", tickets=tickets, stats=stats, status_filter=status_filter)


@app.route("/tickets/new", methods=["POST"])
def create_ticket():
    title = request.form.get("title", "").strip()
    created_by = request.form.get("created_by", "").strip()

    if not title or not created_by:
        flash("Title and your name are both required.", "error")
        return redirect(url_for("index"))

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tickets (title, status, created_by) VALUES (:title, 'open', :created_by)"),
            {"title": title, "created_by": created_by},
        )
    flash("Ticket created.", "success")
    return redirect(url_for("index"))


@app.route("/ticket/<int:ticket_id>")
def view_ticket(ticket_id):
    with engine.connect() as conn:
        ticket = conn.execute(
            text("SELECT * FROM tickets WHERE ticket_id = :id"), {"id": ticket_id}
        ).mappings().first()
        messages = conn.execute(
            text("SELECT * FROM ticket_messages WHERE ticket_id = :id ORDER BY created_at"),
            {"id": ticket_id},
        ).mappings().all()

    if ticket is None:
        flash("Ticket not found.", "error")
        return redirect(url_for("index"))

    return render_template("support_ticket.html", ticket=ticket, messages=messages)


@app.route("/ticket/<int:ticket_id>/messages", methods=["POST"])
def add_message(ticket_id):
    message_text = request.form.get("message_text", "").strip()
    author = request.form.get("author", "").strip()

    if not message_text or not author:
        flash("Message and author are both required.", "error")
        return redirect(url_for("view_ticket", ticket_id=ticket_id))

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO ticket_messages (ticket_id, message_text, author) VALUES (:tid, :text, :author)"),
            {"tid": ticket_id, "text": message_text, "author": author},
        )
    return redirect(url_for("view_ticket", ticket_id=ticket_id))


@app.route("/ticket/<int:ticket_id>/status", methods=["POST"])
def update_status(ticket_id):
    new_status = request.form.get("status")
    allowed = {"open", "in_progress", "resolved"}
    if new_status not in allowed:
        flash("Invalid status.", "error")
        return redirect(url_for("view_ticket", ticket_id=ticket_id))

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE tickets SET status = :status WHERE ticket_id = :id"),
            {"status": new_status, "id": ticket_id},
        )
    flash("Status updated.", "success")
    return redirect(url_for("view_ticket", ticket_id=ticket_id))


@app.route("/ticket/<int:ticket_id>/delete", methods=["POST"])
def delete_ticket(ticket_id):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM ticket_messages WHERE ticket_id = :id"), {"id": ticket_id})
        conn.execute(text("DELETE FROM tickets WHERE ticket_id = :id"), {"id": ticket_id})
    flash("Ticket deleted.", "success")
    return redirect(url_for("index"))


@app.route("/healthz")
def healthz():
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)
