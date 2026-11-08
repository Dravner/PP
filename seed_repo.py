# -*- coding: utf-8 -*-
"""Подготовка учебного репозитория для семинара 4: код «Ромашки», метки и десять задач.

    python seed_repo.py            залить шаблон, создать метки и задачи (повторный запуск ничего не дублирует)
    python seed_repo.py --with-ci  то же и файл .github/workflows/tests.yml: токену нужно право Workflows
    python seed_repo.py --reset    вернуть репозиторий к началу семинара: закрыть пулл-реквесты бота, удалить его ветки,
                                   снять метки, удалить комментарии и заново открыть задачи

Берёт из .env рядом со скриптом GITHUB_TOKEN и GITHUB_REPO вида owner/name. Репозиторий создайте заранее
на github.com, пустым или с README. Номера созданных задач сохраняются в .duty_seed.json: ноутбук по ним
сверяет триаж с правильными ответами.
"""
import base64, json, os, sys, time
from pathlib import Path
import httpx

HERE = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
except ImportError:
    pass
TOKEN, REPO = os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPO")
assert TOKEN and REPO, "в .env нужны GITHUB_TOKEN и GITHUB_REPO=owner/name"
API = f"https://api.github.com/repos/{REPO}"
GH = httpx.Client(headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
                           "X-GitHub-Api-Version": "2022-11-28"}, timeout=30)
SEED = HERE / ".duty_seed.json"
LABELS = {"bug": "d73a4a", "question": "d876e3", "enhancement": "a2eeef", "duplicate": "cfd3d7",
          "needs-info": "fbca04", "bot": "5436a3"}


def call(method, url, ok=(200, 201, 204), **kw):
    r = GH.request(method, url if url.startswith("http") else API + url, **kw)
    if r.status_code not in ok:
        raise SystemExit(f"{method} {url}: HTTP {r.status_code} {r.text[:300]}")
    return r.json() if r.content else {}


def template_files(with_ci):
    root = HERE / "template"
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and "__pycache__" not in rel and (with_ci or not rel.startswith(".github/")):
            yield rel, p.read_bytes()


def push_code(with_ci):
    repo = call("GET", "")
    branch = repo["default_branch"]
    ref = GH.get(f"{API}/git/ref/heads/{branch}")
    if ref.status_code != 200:
        call("PUT", "/contents/README.md", json={"message": "README", "content": base64.b64encode((HERE / "template" / "README.md").read_bytes()).decode()})
        ref = GH.get(f"{API}/git/ref/heads/{branch}")
    head = ref.json()["object"]["sha"]
    base_tree = call("GET", f"/git/commits/{head}")["tree"]["sha"]
    existing = {t["path"] for t in call("GET", f"/git/trees/{base_tree}?recursive=1")["tree"]}
    files = list(template_files(with_ci))
    if all(path in existing for path, _ in files):
        print("код уже в репозитории")
        return branch
    tree = [{"path": path, "mode": "100644", "type": "blob",
             "sha": call("POST", "/git/blobs", json={"content": base64.b64encode(data).decode(), "encoding": "base64"})["sha"]}
            for path, data in files]
    new_tree = call("POST", "/git/trees", json={"base_tree": base_tree, "tree": tree})["sha"]
    commit = call("POST", "/git/commits", json={"message": "Ромашка: код магазина и тесты", "tree": new_tree, "parents": [head]})["sha"]
    call("PATCH", f"/git/refs/heads/{branch}", json={"sha": commit})
    print(f"залито файлов: {len(files)} в ветку {branch}")
    return branch


def make_labels():
    have = {l["name"] for l in call("GET", "/labels?per_page=100")}
    for name, color in LABELS.items():
        if name not in have:
            call("POST", "/labels", json={"name": name, "color": color})
    print("метки:", ", ".join(LABELS))


def make_issues():
    issues = json.loads((HERE / "data" / "issues.json").read_text(encoding="utf-8"))
    have = {i["title"]: i["number"] for i in call("GET", "/issues?state=all&per_page=100") if "pull_request" not in i}
    seed = {}
    for issue in issues:
        if issue["title"] in have:
            seed[issue["key"]] = have[issue["title"]]
            continue
        seed[issue["key"]] = call("POST", "/issues", json={"title": issue["title"], "body": issue["body"]})["number"]
        time.sleep(1)
    SEED.write_text(json.dumps({"repo": REPO, "issues": seed}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("задачи:", ", ".join(f"#{n} {k}" for k, n in seed.items()))


def reset():
    seed = json.loads(SEED.read_text(encoding="utf-8"))["issues"]
    me = GH.get("https://api.github.com/user").json().get("login")
    for pr in call("GET", "/pulls?state=open&per_page=100"):
        if pr["head"]["ref"].startswith("fix/issue-"):
            call("PATCH", f"/pulls/{pr['number']}", json={"state": "closed"})
    for ref in call("GET", "/git/matching-refs/heads/fix/issue-"):
        call("DELETE", f"/git/{ref['ref']}")
    for number in seed.values():
        for c in call("GET", f"/issues/{number}/comments?per_page=100"):
            if c["user"]["login"] == me:
                call("DELETE", f"/issues/comments/{c['id']}")
        call("PATCH", f"/issues/{number}", json={"state": "open", "labels": []})
    print("репозиторий возвращён к началу семинара")


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset()
    else:
        push_code("--with-ci" in sys.argv)
        make_labels()
        make_issues()
