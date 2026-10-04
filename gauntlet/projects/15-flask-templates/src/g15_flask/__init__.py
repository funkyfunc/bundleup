"""Gauntlet 15: Flask templates and static files."""
from flask import Flask, render_template

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html", name="gauntlet")


def main() -> int:
    client = app.test_client()
    page = client.get("/")
    assert page.status_code == 200 and b"Hello gauntlet" in page.data, page.data
    css = client.get("/static/style.css")
    assert css.status_code == 200 and b"teal" in css.data
    css.close()
    print("GAUNTLET OK 15-flask-templates")
    return 0
