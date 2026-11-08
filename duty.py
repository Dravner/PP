#!/usr/bin/env python3
"""Дежурный по репозиторию. Логика из src/main.ipynb, запуск без Jupyter."""
import argparse
import asyncio
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import httpx
import httpx2
import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "workspace/duty"
PINS = ROOT / "pins.json"
ACCEPT = ROOT / "data/acceptance"
CALLS_LOG = ROOT / "results/calls.jsonl"
CALLS = []
CALLS_LOCK = threading.Lock()
COST_TZ = ZoneInfo("Europe/Moscow")
MODE = "dry"
ACTIONS = []
HTTP = None
HEADERS = {}
KEY = GITHUB_TOKEN = REPO = OWNER = NAME = README = ""
BASE_URL = "https://openrouter.ai/api/v1"
GITHUB_MCP = "http://127.0.0.1:8082/"
SEED = {"issues": {}}
KEY_OF = {}
TRUTH = {}

CHEAP, MID, STRONG = "openai/gpt-4o-mini", "anthropic/claude-haiku-4.5", "anthropic/claude-sonnet-4.6"


SHORT = {CHEAP: "mini", MID: "haiku", STRONG: "sonnet"}


def pmap(fn, items, workers=6):
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(fn, items))


def cache_marks(messages):
    out = [dict(m) for m in messages]
    for i in {0, len(out) - 1}:
        if isinstance(out[i].get("content"), str) and out[i]["content"]:
            out[i]["content"] = [{"type": "text", "text": out[i]["content"], "cache_control": {"type": "ephemeral"}}]
    return out


def chat(messages, model, tag, tools=None, tool_choice=None, max_tokens=4000):
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens,
            "messages": cache_marks(messages) if model.startswith("anthropic/") else messages}
    if tools:
        body["tools"] = tools
    if tool_choice:
        body["tool_choice"] = tool_choice

    started = time.perf_counter()
    for attempt in range(5):
        r = HTTP.post(f"{BASE_URL}/chat/completions", json=body, headers=HEADERS)
        if r.status_code == 200 and r.json().get("choices"):
            break
        time.sleep(2 * (attempt + 1))

    else:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    latency_s = time.perf_counter() - started
    usage = r.json().get("usage") or {}
    message = r.json()["choices"][0]["message"]
    tools_called = [
        call["function"]["name"]
        for call in (message.get("tool_calls") or [])
    ]
    record = {
        "tag": tag,
        "model": SHORT.get(model, model),
        "prompt": usage.get("prompt_tokens", 0),
        "cached": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
        "tools_called": tools_called,
        "completion": usage.get("completion_tokens", 0),
        "cost": usage.get("cost") or 0.0,
        "timestamp": datetime.now(COST_TZ).isoformat(),
        "latency_s": latency_s,
    }

    with CALLS_LOCK:
        CALLS.append(record)
        with CALLS_LOG.open("a", encoding="utf-8") as log:
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
    return message


def structured(messages, model, schema, tag):
    tool = {"type": "function", "function": {"name": "submit", "description": "Submit the result.",
                                             "parameters": schema.model_json_schema()}}
    msg = chat(messages, model, tag, tools=[tool], tool_choice={"type": "function", "function": {"name": "submit"}})
    return schema.model_validate_json(msg["tool_calls"][0]["function"]["arguments"])


def spent(prefix):
    return sum(c["cost"] for c in CALLS if c["tag"].startswith(prefix))


def spent_today():
    today = datetime.now(COST_TZ).date()

    with CALLS_LOCK:
        if not CALLS_LOG.exists():
            return 0.0

        total = 0.0
        with CALLS_LOG.open(encoding="utf-8") as log:
            for line in log:
                if not line.strip():
                    continue

                record = json.loads(line)
                timestamp = record.get("timestamp")

                if not timestamp:
                    continue

                called_at = datetime.fromisoformat(timestamp)
                if called_at.tzinfo is None:
                    raise ValueError("В timestamp отсутствует часовая зона")

                if called_at.astimezone(COST_TZ).date() == today:
                    total += record.get("cost") or 0.0

        return total


class MCP:
    def __init__(self, server, timeout=120):
        self.timeout = timeout
        self.loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.ready = concurrent.futures.Future()
        self.held = asyncio.run_coroutine_threadsafe(self._hold(server), self.loop)
        self.client = self.ready.result(timeout)
        self.tools = self._run(self.client.list_tools()).tools

    async def _hold(self, server):
        self.stop = asyncio.Event()
        try:
            async with Client(server() if callable(server) else server) as client:
                self.ready.set_result(client)
                await self.stop.wait()
        except BaseException as e:
            if not self.ready.done():
                self.ready.set_exception(e)
            raise

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(self.timeout)

    def call(self, name, args=None):
        result = self._run(self.client.call_tool(name, args or {}))
        text = "\n".join(getattr(c, "text", None) or getattr(getattr(c, "resource", None), "text", None) or ""
                         for c in result.content)
        return f"error: {text}" if result.is_error else text

    def close(self):
        self.loop.call_soon_threadsafe(self.stop.set)
        try:
            self.held.result(30)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)


def github(tools=None, toolsets=None, readonly=False):
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    if tools:
        headers["X-MCP-Tools"] = ",".join(tools)
    if toolsets:
        headers["X-MCP-Toolsets"] = toolsets
    if readonly:
        headers["X-MCP-Readonly"] = "true"
    return MCP(lambda: streamable_http_client(GITHUB_MCP, http_client=httpx2.AsyncClient(headers=headers, timeout=60)))


def gh_file(gh, path):
    raw = gh.call("get_file_contents", {"owner": OWNER, "repo": NAME, "path": path})
    if raw.startswith("error:"):
        raise RuntimeError(raw)
    return raw.split("\n", 1)[1] if raw.startswith("successfully downloaded") else raw


def as_openai_tools(tools, allow=None):
    return [{"type": "function", "function": {"name": t.name, "description": t.description or "", "parameters": t.input_schema}}
            for t in tools if allow is None or t.name in allow]


DUTY_TOOLS = ["list_issues", "issue_read", "get_file_contents", "get_repository_tree", "create_branch",
              "push_files", "create_pull_request", "add_issue_comment", "issue_write"]


ANSWER_TOOLS = ["get_file_contents", "get_repository_tree"]


def fingerprint(tools):
    return {t.name: hashlib.sha256(json.dumps([t.description, t.input_schema], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
            for t in tools}


def check_pins(tools, label):
    pins = json.loads(PINS.read_text(encoding="utf-8")) if PINS.exists() else {}
    now = fingerprint(tools)
    if label not in pins:
        pins[label] = now
        PINS.write_text(json.dumps(pins, indent=1), encoding="utf-8")
        return f"{label}: закрепили {len(now)} описаний"
    changed = sorted(n for n in set(now) | set(pins[label]) if now.get(n) != pins[label].get(n))
    if changed:
        raise RuntimeError(f"{label}: изменились описания {changed}. Прочитайте их и закрепите заново, удалив запись из {PINS}")
    return f"{label}: описания совпадают"


def open_issues(gh):
    raw = gh.call("list_issues", {"owner": OWNER, "repo": NAME, "state": "OPEN", "perPage": 100,
                                  "fields": ["number", "title", "body", "labels"]})
    issues = [{"number": i["number"], "title": i["title"], "body": i.get("body") or "",
               "labels": [l if isinstance(l, str) else l["name"] for l in i.get("labels") or []]}
              for i in parse_github_json(raw, "list_issues")["issues"]]
    return sorted(issues, key=lambda i: i["number"])


class Triage(BaseModel):
    kind: Literal["bug", "question", "feature", "duplicate", "needs_info"] = Field(
        description="bug: wrong behaviour described concretely enough to reproduce; question: asks how to do something; "
                    "feature: asks for new functionality; duplicate: the same problem as an earlier issue; "
                    "needs_info: a complaint without details to reproduce")
    duplicate_of: int | None = Field(None, description="for duplicate: number of the earlier issue with the same problem")
    reason: str = Field(description="one short sentence why")
    plan: str = Field("", description="for bug: the module that is probably wrong and the expected behaviour, one or two sentences")


TRIAGE_SYSTEM = """You triage new GitHub issues of a small Python repository. Read the issue and decide what it is.
A duplicate must describe the same problem as an EARLIER issue from the list, with a smaller number.
Repository overview:
{readme}"""


def triage(issue, issues, model, tag):
    earlier = "\n".join(f"#{o['number']} {o['title']}: {o['body'][:150]}" for o in issues if o["number"] < issue["number"])
    user = f"Issue #{issue['number']}: {issue['title']}\n\n{issue['body']}\n\nEarlier open issues:\n{earlier or '(none)'}"
    return structured([{"role": "system", "content": TRIAGE_SYSTEM.format(readme=README)},
                       {"role": "user", "content": user}], model, Triage, tag)


def triage_right(number, kind, dup=None):
    truth = TRUTH[number]
    want_dup = SEED["issues"].get(truth.get("duplicate_of")) if truth["kind"] == "duplicate" else None
    dup = int(dup) if kind == "duplicate" and dup is not None and dup == dup else None
    return kind == truth["kind"] and dup == want_dup


def pull_repo(gh, dest=WORK / "snapshot"):
    tree = parse_github_json(gh.call("get_repository_tree", {"owner": OWNER, "repo": NAME, "recursive": True}), "get_repository_tree")
    shutil.rmtree(dest, ignore_errors=True)
    for entry in tree["tree"]:
        if entry["type"] == "blob":
            path = dest / entry["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            content = "" if entry.get("size") == 0 else gh_file(gh, entry["path"])
            path.write_text(content, encoding="utf-8")
    return dest


def sandbox_args(work, name):
    return ["run", "-i", "--rm", "--name", name, "--network", "none", "--memory", "512m", "--cpus", "1",
            "--pids-limit", "128", "--read-only", "--tmpfs", "/tmp",
            "-v", f"{work / 'repo'}:/work/repo", "-v", f"{work / 'orig'}:/work/orig:ro",
            "-v", f"{work / 'acceptance'}:/work/acceptance:ro", "romashka-sandbox:1"]


def open_sandbox(snapshot):
    work = WORK / uuid.uuid4().hex[:8]
    shutil.copytree(snapshot, work / "repo")
    shutil.copytree(snapshot, work / "orig")
    (work / "acceptance").mkdir()
    params = StdioServerParameters(command="docker", args=sandbox_args(work, f"sbx-{work.name}"))
    return MCP(lambda: stdio_client(params, errlog=sys.stderr)), work


BUDGET = 0.15


CODER_TOOLS = {"list_files", "read_file", "search", "replace_in_file", "write_file", "run_tests"}


CODER_SYSTEM = """You fix one issue in a Python repository. You work in a sandbox copy of the repository.
1. Find the relevant code with search or list_files and read it.
2. Write a regression test tests/test_issue_{n}.py with unittest that reproduces the problem from the issue.
3. Fix the code with small changes using replace_in_file. Never change existing tests.
4. Run the tests. When everything passes, reply with a short report: what was wrong and what you changed."""


LAST_STEP = "No more tool calls. Reply now with your short report."


BAD_JSON = ("error: the arguments of your call are not valid JSON, most likely your reply was cut by the length limit. "
            "Write less text before the call and send it again.")


def compact_context(messages, max_chars=1200):
    context = [message.copy() for message in messages]
    tool_indexes = [
        i for i, message in enumerate(context)
        if message["role"] == "tool"
    ]

    for i in tool_indexes[:-2]:
        content = context[i]["content"]
        if len(content) > max_chars:
            context[i]["content"] = (
                content[:max_chars] + "\n[Контекст сжат]"
            )

    return context


def agent_loop(system, user, tools, call_tool, model, tag, max_steps=16):
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    seen, version, issue_tag = Counter(), 0, tag.rsplit("|", 1)[0] + "|"
    for step in range(max_steps):
        last = step == max_steps - 1 or spent(issue_tag) > BUDGET
        if last:
            msgs.append({"role": "user", "content": LAST_STEP})
        context = compact_context(msgs)
        msg = chat(context, model, tag, tools=None if last else tools)
        msgs.append({"role": "assistant", **{k: msg[k] for k in ("content", "tool_calls") if msg.get(k)}})
        if last or not msg.get("tool_calls"):
            return msg.get("content") or "", msgs
        for call in msg["tool_calls"]:
            name, raw = call["function"]["name"], call["function"]["arguments"] or "{}"
            seen[name, raw, version] += 1
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                args, result = None, BAD_JSON
            if args is not None and seen[name, raw, version] > 2:
                result = "refused: you already made this exact call twice and nothing changed since. Try another approach."
            elif args is not None:
                try:
                    result = call_tool(name, args)
                except Exception as e:
                    result = f"error: {type(e).__name__}: {e}"
            version += result.startswith("ok")
            msgs.append({"role": "tool", "tool_call_id": call["id"], "content": result})
    return "", msgs


def fix_bug(issue, plan, box, model, tag, feedback=""):
    user = f"Issue #{issue['number']}: {issue['title']}\n\n{issue['body']}\n\nTriage notes: {plan}"
    if feedback:
        user += f"\n\nYour previous attempt was rejected:\n{feedback}\nThe working copy still has your previous changes."
    report, msgs = agent_loop(CODER_SYSTEM.format(n=issue["number"]), user, as_openai_tools(box.tools, CODER_TOOLS),
                              box.call, model, tag)
    return {"report": report, "steps": sum(m["role"] == "assistant" for m in msgs), "msgs": msgs}


class Review(BaseModel):
    approve: bool = Field(description="true only if the change fixes the issue and nothing unrelated is changed")
    problems: list[str] = Field(default_factory=list, description="concrete problems, empty if approved")


REVIEW_SYSTEM = """You review a change to a Python repository made for one issue. Tests were already checked by code,
their results are given. Your job is the meaning of the change: does the diff fix the problem described in the issue,
including every case mentioned there, without breaking the documented behaviour and without unrelated changes
(new parameters, changed signatures, reformatting). Approve only if all of that holds."""


def checks(box):
    tests, regression = box.call("run_tests"), box.call("new_tests_on_original")
    return {"tests_ok": tests.startswith("exit code 0"), "tests": tests,
            "regression_ok": re.match(r"exit code [1-9]", regression) is not None and "no new test files" not in regression}


def review(issue, diff, check, model, tag):
    facts = (f"Test suite after the change: {'passes' if check['tests_ok'] else 'FAILS'}.\n"
             f"New regression test: {'fails on the original code and passes now, so it reproduces the problem' if check['regression_ok'] else 'does not reproduce the problem'}.")
    user = f"Issue #{issue['number']}: {issue['title']}\n\n{issue['body']}\n\n{facts}\n\nDiff:\n{diff[:6000]}"
    return structured([{"role": "system", "content": REVIEW_SYSTEM}, {"role": "user", "content": user}], model, Review, tag)


def gate(check, verdict):
    problems = []
    if not check["tests_ok"]:
        problems.append("The test suite fails:\n" + check["tests"][-1000:])
    if not check["regression_ok"]:
        problems.append("Add a regression test tests/test_issue_<N>.py that fails on the original code and passes after the fix.")
    if verdict is not None and not verdict.approve:
        problems += verdict.problems or ["The reviewer did not approve the change."]
    return not problems, "\n".join(problems)


def solve(issue, plan, team, tag, snapshot):
    box, work = open_sandbox(snapshot)
    try:
        feedback, steps = "", 0
        for attempt in range(1, 3):
            out = fix_bug(issue, plan, box, team["coder"], f"{tag}|coder", feedback)
            steps += out["steps"]
            check, diff = checks(box), box.call("diff")
            verdict = review(issue, diff, check, team["reviewer"], f"{tag}|review") if team.get("reviewer") else None
            ok, feedback = gate(check, verdict)
            if ok or spent(tag + "|") > BUDGET:
                break
        key, accepted = KEY_OF.get(issue["number"]), None
        if key and (ACCEPT / f"{key}.py").exists():
            shutil.copy(ACCEPT / f"{key}.py", work / "acceptance" / f"{key}.py")
            accepted = box.call("run_acceptance", {"name": key}).startswith("exit code 0")
        return {"ok": ok, "accepted": accepted, "attempts": attempt, "steps": steps, "diff": diff, "report": out["report"],
                "feedback": feedback, "files": json.loads(box.call("changed_files"))}
    finally:
        box.close()
        shutil.rmtree(work, ignore_errors=True)


SIGN = "\n\n_Комментарий оставил дежурный бот курса по ИИ-агентам._"


def open_pr(gh, issue, result):
    n, branch = issue["number"], f"fix/issue-{issue['number']}"
    files = [{"path": p, "content": c} for p, c in result["files"].items()]
    gh_write(gh, "create_branch", {"branch": branch, "from_branch": "main"})
    gh_write(gh, "push_files", {"branch": branch, "files": files, "message": f"Fix #{n}: {issue['title']}"})
    body = f"Fixes #{n}\n\n{result['report']}\n\nПроверки: тесты проходят, новый тест воспроизводит баг.{SIGN}"
    pr = gh_write(gh, "create_pull_request", {"title": f"Fix #{n}: {issue['title']}", "head": branch, "base": "main", "body": body})
    found = re.search(r'/pull/(\d+)|"number":\s*(\d+)', pr)
    number = next((g for g in found.groups() if g), "?") if found else "?"
    gh_write(gh, "add_issue_comment", {"issue_number": n, "body": f"Предлагаю исправление в #{number}.{SIGN}"})
    return int(number) if number.isdigit() else None


ANSWER_SYSTEM = """You answer a question asked in a GitHub issue of the repository {repo}. Read the files you need
with the tools. Answer in the language of the question, briefly, with exact commands. Say only what the repository says."""


REPLIES = {
    "feature": ("enhancement", "Спасибо за идею. Это новая функция, а не ошибка: передаю команде, решение примут люди."),
    "duplicate": ("duplicate", "Похоже, это та же проблема, что в #{dup}. Следите за той задачей, эту закроет человек после проверки."),
    "needs_info": ("needs-info", "Чтобы разобраться, нужны подробности: что лежит в корзине, какой промокод, какую сумму вы ждали и какую видите."),
}


def respond(gh, issue, verdict, team, tag, fix=None):
    labels = set(issue["labels"]) | {"bot"}
    if verdict.kind == "question":
        reader = github(tools=ANSWER_TOOLS)
        answer, _ = agent_loop(ANSWER_SYSTEM.format(repo=REPO), f"{issue['title']}\n\n{issue['body']}", as_openai_tools(reader.tools),
                               lambda name, args: reader.call(name, {**args, "owner": OWNER, "repo": NAME}), team["answer"], f"{tag}|answer")
        reader.close()
        gh_write(gh, "add_issue_comment", {"issue_number": issue["number"], "body": answer + SIGN})
        labels.add("question")
    elif verdict.kind in REPLIES:
        label, text = REPLIES[verdict.kind]
        gh_write(gh, "add_issue_comment", {"issue_number": issue["number"], "body": text.format(dup=verdict.duplicate_of) + SIGN})
        labels.add(label)
    elif fix and not fix["ok"]:
        gh_write(gh, "add_issue_comment", {"issue_number": issue["number"], "body":
                 "Не смог починить автоматически, нужен человек. Что осталось нерешённым:\n\n" + fix["feedback"][:1500] + SIGN})
    labels |= {"bug"} if verdict.kind == "bug" else set()
    gh_write(gh, "issue_write", {"method": "update", "issue_number": issue["number"], "labels": sorted(labels)})


TEAMS = {
    "Sonnet без ревьюера": {
        "triage": STRONG,
        "coder": STRONG,
        "reviewer": None,
        "answer": STRONG,
    },
    "команда": {
        "triage": MID,
        "coder": STRONG,
        "reviewer": CHEAP,
        "answer": CHEAP,
    },
    "всё на mini": {
        "triage": CHEAP,
        "coder": CHEAP,
        "reviewer": CHEAP,
        "answer": CHEAP,
    },
}


def on_duty(team, name):
    gh = github(tools=DUTY_TOOLS)
    snapshot = None
    try:
        print(check_pins(gh.tools, "github"))
        todo = [i for i in open_issues(gh) if "bot" not in i["labels"]]
        snapshot = pull_repo(gh, WORK / f"snapshot-{uuid.uuid4().hex[:6]}")
        verdicts = pmap(lambda i: triage(i, todo, team["triage"], f"{name}|#{i['number']}|triage"), todo)
        bugs = [(i, v) for i, v in zip(todo, verdicts) if v.kind == "bug"]
        fixes = dict(zip([i["number"] for i, _ in bugs],
                         pmap(lambda iv: solve(iv[0], iv[1].plan, team, f"{name}|#{iv[0]['number']}", snapshot), bugs, 3)))
        rows = []
        for issue, verdict in zip(todo, verdicts):
            fix = fixes.get(issue["number"])
            if fix and fix["ok"]:
                open_pr(gh, issue, fix)
            respond(gh, issue, verdict, team, f"{name}|#{issue['number']}", fix)
            rows.append({"состав": name, "задача": issue["number"], "ключ": KEY_OF.get(issue["number"], ""), "триаж": verdict.kind,
                         "дубликат": verdict.duplicate_of,
                         "проверки": fix["ok"] if fix else None, "приёмка": fix["accepted"] if fix else None,
                         "попыток": fix["attempts"] if fix else 0, "центов": round(spent(f"{name}|#{issue['number']}|") * 100, 2)})
        return pd.DataFrame(rows)
    finally:
        if snapshot is not None:
            shutil.rmtree(snapshot, ignore_errors=True)
        gh.close()


def summary(df):
    out = []
    for name, d in df.groupby("состав", sort=False):
        right = sum(triage_right(r["задача"], r["триаж"], r["дубликат"]) for _, r in d.iterrows())
        fixed = int(((d["проверки"] == True) & (d["приёмка"] == True)).sum())
        false_pr = int(((d["проверки"] == True) & (d["приёмка"] != True)).sum())
        cents = d["центов"].sum()
        out.append({"состав": name, "триаж верно": right, "починено из 6": fixed, "ложных PR": false_pr,
                    "центов за прогон": round(cents, 1), "центов за починенный баг": round(cents / max(fixed, 1), 1)})
    return pd.DataFrame(out)


def parse_github_json(raw, tool):
    if raw.startswith("error:"):
        raise RuntimeError(f"{tool}: {raw}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{tool} вернул не JSON. Повторите запуск; ответ: {raw[:200]}") from exc


def gh_write(gh, name, args):
    ACTIONS.append({"tool": name, **args})
    if MODE == "dry":
        return "dry run"
    if MODE != "ask":
        raise RuntimeError("Допустимы только режимы dry и ask")
    print(f"\n{name}: {json.dumps(args, ensure_ascii=False, indent=2)}")
    if input("Выполнить? [y/N] ").strip().lower() not in ("y", "д", "да", "yes"):
        raise RuntimeError("Действие отменено пользователем")
    result = gh.call(name, {"owner": OWNER, "repo": NAME, **args})
    if result.startswith("error:"):
        raise RuntimeError(result)
    return result


def match_seed(issues, truth):
    by_title = {issue["title"]: issue["number"] for issue in issues}
    return {item["key"]: by_title[item["title"]] for item in truth if item["title"] in by_title}


def configure(require_model_key=True):
    global KEY, GITHUB_TOKEN, REPO, OWNER, NAME, HTTP, HEADERS, README, SEED, KEY_OF, TRUTH
    load_dotenv(ROOT / ".env", override=False)
    KEY = os.getenv("OPENROUTER_API_KEY", "")
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
    REPO = os.getenv("GITHUB_REPO", "")
    if not GITHUB_TOKEN or REPO.count("/") != 1 or "://" in REPO:
        raise RuntimeError("Заполните GITHUB_TOKEN и GITHUB_REPO=владелец/репозиторий в .env")
    if require_model_key and not KEY:
        raise RuntimeError("Заполните OPENROUTER_API_KEY в .env")
    OWNER, NAME = REPO.split("/")
    CALLS_LOG.parent.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    HTTP = httpx.Client(timeout=180)
    HEADERS = {"Authorization": f"Bearer {KEY}", "X-Title": "hw4-duty"}
    gh = github(tools=DUTY_TOOLS)
    try:
        print(check_pins(gh.tools, "github"))
        README = gh_file(gh, "README.md")
        all_issues = []
        for state in ("OPEN", "CLOSED"):
            raw = gh.call("list_issues", {"owner": OWNER, "repo": NAME, "state": state,
                          "perPage": 100, "fields": ["number", "title", "body", "labels"]})
            all_issues.extend(parse_github_json(raw, "list_issues")["issues"])
        truth = json.loads((ROOT / "data/issues.json").read_text(encoding="utf-8"))
        SEED = {"repo": REPO, "issues": match_seed(all_issues, truth)}
        KEY_OF = {number: key for key, number in SEED["issues"].items()}
        TRUTH = {SEED["issues"][item["key"]]: item for item in truth if item["key"] in SEED["issues"]}
    finally:
        gh.close()


def check_runtime():
    gh = github(tools=DUTY_TOOLS)
    snapshot = None
    box = None
    work = None
    try:
        issues = open_issues(gh)
        snapshot = pull_repo(gh, WORK / f"check-{uuid.uuid4().hex[:8]}")
        box, work = open_sandbox(snapshot)
        tests = box.call("run_tests")
        if not tests.startswith("exit code 0"):
            raise RuntimeError(tests)
        return {"repo": REPO, "open_issues": len(issues), "tests": tests, "model_calls": 0}
    finally:
        if box is not None:
            box.close()
        for folder in (work, snapshot):
            if folder is not None:
                shutil.rmtree(folder, ignore_errors=True)
        gh.close()


def main(argv=None):
    global MODE, BUDGET
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team", choices=list(TEAMS), default="команда")
    parser.add_argument("--mode", choices=("dry", "ask"), default="dry")
    parser.add_argument("--budget", type=float, default=0.15, help="порог расходов задачи в долларах")
    parser.add_argument("--check", action="store_true", help="проверить GitHub и Docker без вызовов моделей")
    parser.add_argument("--compare", action="store_true", help="сравнить три состава на текущих открытых задачах")
    args = parser.parse_args(argv)
    if args.budget <= 0:
        parser.error("--budget должен быть больше нуля")
    if args.compare and args.mode != "dry":
        parser.error("--compare допускается только с --mode dry")
    MODE, BUDGET = args.mode, args.budget
    try:
        configure(require_model_key=not args.check)
        if args.check:
            print(json.dumps(check_runtime(), ensure_ascii=False, indent=2))
            return 0
        run_id = uuid.uuid4().hex[:8]
        names = list(TEAMS) if args.compare else [args.team]
        frames = []
        for name in names:
            prefix = f"{run_id}|{name}"
            print(f"Запуск: {name}; режим: {MODE}")
            frame = on_duty(TEAMS[name], prefix)
            if frame.empty:
                continue
            for index, row in frame.iterrows():
                issue_prefix = f"{prefix}|#{row['задача']}|"
                calls = [call for call in CALLS if call["tag"].startswith(issue_prefix)]
                frame.loc[index, "вызовов"] = len(calls)
                frame.loc[index, "токенов"] = sum(call["prompt"] + call["completion"] for call in calls)
                frame.loc[index, "LLM-секунд"] = sum(call["latency_s"] for call in calls)
            frame["состав"] = name
            frames.append(frame)
        if not frames:
            print("Нет новых открытых задач без метки bot.")
            return 0
        result = pd.concat(frames, ignore_index=True)
        folder = ROOT / "results"
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / f"run_{run_id}.csv"
        result.to_csv(destination, index=False)
        print(result.to_string(index=False))
        print(f"Результат: {destination}")
        if all(number in TRUTH for number in result["задача"]):
            table = summary(result)
            table.to_csv(folder / f"summary_{run_id}.csv", index=False)
            print(table.to_string(index=False))
        return 0
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    finally:
        if HTTP is not None:
            HTTP.close()


if __name__ == "__main__":
    raise SystemExit(main())
